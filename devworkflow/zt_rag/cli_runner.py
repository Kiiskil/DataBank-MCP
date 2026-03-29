"""
Yhteinen logiikka: MCP-työkalut ja CLI (podman run ... python -m devworkflow.zt_cli).
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic

from devworkflow.zt_rag.ingest import ChunkRecord, ingest_active_sources
from devworkflow.zt_rag.index_publish import (
    build_and_publish,
    load_published_meta,
    published_chunk_count,
    published_index_dir,
)
from devworkflow.zt_rag.parsers import INGEST_SYNC_SUFFIXES, detect_type
from devworkflow.zt_rag.query_rewrite import (
    corpus_aware_rewrite_enabled,
    decompose_search_queries,
    fallback_decompose_queries,
    hard_retrieval_profile_env,
    hyde_enabled,
    hyde_expand,
    query_fallback_enabled,
    query_policy,
    should_trigger_query_fallback,
    skip_query_decompose,
)
from devworkflow.zt_rag.retrieval import load_context_blocks, open_index
from devworkflow.zt_rag.term_catalog import (
    load_term_catalog,
    select_term_hints,
    term_catalog_path_in_index,
    top_terms_as_hints,
)
from devworkflow.zt_rag.sanitize import sanitize_retrieved_text, wrap_source_block
from devworkflow.zt_rag.schemas import ZtAnswer, refusal_payload
from devworkflow.zt_rag.source_manifest import (
    Manifest,
    SourceStatus,
    manifest_path,
)
from devworkflow.zt_rag.storage_layout import StoragePaths
from devworkflow.zt_rag.verify import verify_full_pipeline
from devworkflow.zt_rag.versioning import file_sha256, fingerprint_source_hashes

_SKIP_DIR_SEGMENTS = frozenset({
    ".git",
    ".svn",
    ".hg",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
})


_NO_SYNC_PATHS_HINT = (
    "Anna source_paths tai aseta ZT_DEFAULT_SYNC_PATHS (pilkuilla erotetut hakemistot; "
    "esim. MCP-kontissa mountattu Databank-kerros)."
)


def effective_source_paths(raw: list[str]) -> list[str]:
    """
    Käyttäjän polut tai tyhjänä ZT_DEFAULT_SYNC_PATHS (sama oletus kuin sync + list).
    """
    paths = [str(p).strip() for p in raw if str(p).strip()]
    if paths:
        return paths
    env = os.environ.get("ZT_DEFAULT_SYNC_PATHS", "").strip()
    if not env:
        return []
    return [p.strip() for p in env.split(",") if p.strip()]


def expand_source_paths(raw: list[str]) -> list[Path]:
    out: list[Path] = []
    for r in raw:
        p = Path(r).expanduser().resolve()
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if not f.is_file():
                    continue
                try:
                    rel_parts = f.relative_to(p).parts
                except ValueError:
                    rel_parts = f.parts
                if _SKIP_DIR_SEGMENTS.intersection(rel_parts):
                    continue
                if f.suffix.lower() not in INGEST_SYNC_SUFFIXES:
                    continue
                out.append(f)
        elif p.is_file():
            out.append(p)
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        k = str(p)
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def _mf(paths: StoragePaths) -> Path:
    return manifest_path(paths.manifests)


def _query_log_meta() -> dict[str, Any]:
    """
    Ympäristöstä (Podman -e / host): eräajo ja kyselyn lähde → queries.jsonl.

    ZT_QUERY_LOG_SOURCE — esim. zt_cli, mcp_query_batch, cursor_mcp
    ZT_QUERY_BATCH_FILE — absoluuttinen polku kysymyslistaan (testierä)
    ZT_QUERY_BATCH_RUN_ID — saman eräajon yhteinen tunniste
    """
    m: dict[str, Any] = {}
    src = os.environ.get("ZT_QUERY_LOG_SOURCE", "").strip()
    if src:
        m["query_source"] = src
    bf = os.environ.get("ZT_QUERY_BATCH_FILE", "").strip()
    if bf:
        m["batch_questions_file"] = bf
    rid = os.environ.get("ZT_QUERY_BATCH_RUN_ID", "").strip()
    if rid:
        m["batch_run_id"] = rid
    return m


def _log_query(paths: StoragePaths, payload: dict[str, Any]) -> None:
    logf = paths.logs / "queries.jsonl"
    logf.parent.mkdir(parents=True, exist_ok=True)
    merged = {**_query_log_meta(), **payload}
    with logf.open("a", encoding="utf-8") as f:
        f.write(json.dumps(merged, ensure_ascii=False) + "\n")


def _retrieval_chunk_ids(ctx_rows: list[dict[str, Any]]) -> list[str]:
    return [str(r.get("chunk_id", "") or "") for r in ctx_rows if r.get("chunk_id")]


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _build_context_with_budget(
    rows: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """
    Rajoita prompt-kontekstia:
    - deduplikoi identtiset tekstiblokit
    - cap per chunk
    - cap kokonaismerkkimäärälle
    """
    per_chunk_cap = _env_int("ZT_CONTEXT_MAX_CHUNK_CHARS", 6000)
    total_cap = _env_int("ZT_CONTEXT_MAX_CHARS", 45000)
    max_rows = _env_int("ZT_CONTEXT_MAX_ROWS", max(1, len(rows)))

    blocks: list[str] = []
    kept_rows: list[dict[str, Any]] = []
    seen_bodies: set[str] = set()
    current_chars = 0
    dropped_duplicates = 0
    dropped_budget = 0

    for row in rows:
        if len(kept_rows) >= max_rows:
            dropped_budget += 1
            continue
        raw_body = str(row.get("text", ""))
        body = sanitize_retrieved_text(raw_body, max_len=per_chunk_cap)
        body_key = body.strip().lower()
        if not body_key:
            continue
        if body_key in seen_bodies:
            dropped_duplicates += 1
            continue
        seen_bodies.add(body_key)

        block = wrap_source_block(
            str(row.get("chunk_id", "")),
            str(row.get("title", "")),
            body,
        )
        remaining = total_cap - current_chars
        if remaining <= 0:
            dropped_budget += 1
            break
        if len(block) > remaining:
            if remaining < 256:
                dropped_budget += 1
                break
            block = block[:remaining] + "\n\n[... context budget katkaisi loput ...]"
            blocks.append(block)
            kept_rows.append(row)
            current_chars += len(block)
            break

        blocks.append(block)
        kept_rows.append(row)
        current_chars += len(block)

    stats = {
        "rows_in": len(rows),
        "rows_kept": len(kept_rows),
        "dropped_duplicates": dropped_duplicates,
        "dropped_budget": dropped_budget,
        "chars": current_chars,
        "max_chars": total_cap,
        "max_chunk_chars": per_chunk_cap,
    }
    return "\n\n".join(blocks), kept_rows, stats


def parse_json_response(raw: str) -> dict[str, Any]:
    clean = raw.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        clean = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return json.loads(clean.strip())


def run_list_ingestible(paths: StoragePaths, raw_paths: list[str]) -> dict[str, Any]:
    """
    Listaa ingestoitavat tiedostot (sama skannaus kuin zt_sync_sources), ei manifest-kirjoitusta.
    """
    effective = effective_source_paths(raw_paths)
    if not effective:
        return {"ok": False, "error": "no_paths", "hint": _NO_SYNC_PATHS_HINT}
    expanded = expand_source_paths(effective)
    files: list[dict[str, Any]] = []
    for p in expanded:
        ft = detect_type(p)
        try:
            sz = int(p.stat().st_size)
        except OSError:
            sz = None
        files.append(
            {
                "path": str(p.resolve()),
                "file_type": ft,
                "size_bytes": sz,
            }
        )
    return {
        "ok": True,
        "files": files,
        "count": len(files),
        "scanned_roots": effective,
        "zt_data_dir": str(paths.root),
    }


def run_sync_sources(paths: StoragePaths, raw_paths: list[str]) -> dict[str, Any]:
    effective = effective_source_paths(raw_paths)
    if not effective:
        return {"ok": False, "error": "no_paths", "hint": _NO_SYNC_PATHS_HINT}
    expanded = expand_source_paths(effective)
    mf = _mf(paths)
    man = Manifest.load(mf)
    added: list[str] = []
    for p in expanded:
        ft = detect_type(p)
        if ft == "unknown":
            continue
        ent = man.upsert_path(p, ft)
        try:
            ent.source_hash = file_sha256(p)
        except OSError as e:
            ent.ingest_status = "hash_error"
            ent.error_code = str(e)
        ent.status = SourceStatus.ACTIVE
        added.append(str(p))
    man.save(mf)
    return {"ok": True, "registered": added, "count": len(added)}


def _should_skip_redundant_publish(
    paths: StoragePaths,
    manifest: Manifest,
    chunks: list[ChunkRecord],
    report: dict[str, Any],
    *,
    force_rebuild: bool,
) -> tuple[bool, str]:
    """
    Ohita build_and_publish vain kun lähteet eivät ole muuttuneet (fingerprint)
    ja jokainen aktiivinen lähde tuli pelkästä ingest-cachesta (ei uutta parsintaa).

    Estää virheellisen ohituksen, jos chunkit generoidaan uusilla UUID:illä samasta hashistä.
    """
    if force_rebuild:
        return False, "force_rebuild"
    meta = load_published_meta(paths)
    if not meta:
        return False, "no_published_index"
    active_hashes = {
        e.source_id: e.source_hash
        for e in manifest.sources.values()
        if e.status in (SourceStatus.ACTIVE, SourceStatus.UPDATED)
        and e.source_hash
    }
    fp = fingerprint_source_hashes(active_hashes)
    pub_fp = str(meta.get("source_fingerprint", ""))
    if not pub_fp or fp != pub_fp:
        return False, "fingerprint_mismatch"
    pub_n = published_chunk_count(paths, meta)
    if pub_n <= 0 or len(chunks) != pub_n:
        return False, "chunk_count_mismatch"
    for sid, ent in manifest.sources.items():
        if ent.status not in (SourceStatus.ACTIVE, SourceStatus.UPDATED):
            continue
        src_rep = report["sources"].get(sid)
        if src_rep is None:
            return False, "missing_source_ingest_report"
        if not src_rep.get("skipped_parse"):
            return False, "source_reparsed"
    return True, "unchanged_sources_from_cache"


def run_ingest(paths: StoragePaths, force_rebuild: bool = False) -> dict[str, Any]:
    req = os.environ.get("ZT_INGEST_REQUIRE_CUDA", "").strip().lower()
    if req in ("1", "true", "yes", "on"):
        import torch

        if not torch.cuda.is_available():
            return {
                "ok": False,
                "error": "ingest_requires_cuda",
                "detail": "ZT_INGEST_REQUIRE_CUDA: torch.cuda.is_available() on False (tarkista ROCm-kontti, /dev/kfd, /dev/dri ja ryhmät).",
            }
    mf = _mf(paths)
    man = Manifest.load(mf)
    chunks, rep = ingest_active_sources(paths, man, force_rebuild=force_rebuild)
    if not chunks:
        man.save(mf)
        return {"ok": False, "error": "no_chunks", "report": rep}
    skip_pub, skip_reason = _should_skip_redundant_publish(
        paths, man, chunks, rep, force_rebuild=force_rebuild
    )
    if skip_pub:
        man.save(mf)
        active_hashes = {
            e.source_id: e.source_hash
            for e in man.sources.values()
            if e.status in (SourceStatus.ACTIVE, SourceStatus.UPDATED)
            and e.source_hash
        }
        return {
            "ok": True,
            "ingest_report": rep,
            "publish": {
                "ok": True,
                "skipped": True,
                "reason": skip_reason,
                "source_fingerprint": fingerprint_source_hashes(active_hashes),
            },
        }
    pub = build_and_publish(paths, man, chunks, mf)
    return {"ok": True, "ingest_report": rep, "publish": pub}


def run_verify_coverage(paths: StoragePaths) -> dict[str, Any]:
    mf = _mf(paths)
    man = Manifest.load(mf)
    meta = load_published_meta(paths)
    issues: list[dict[str, Any]] = []
    if not meta:
        return {"ok": False, "issues": [{"type": "no_published_index"}]}
    pub_sources = meta.get("sources", {})
    pub_fp = str(meta.get("source_fingerprint", ""))
    active_hashes = {
        e.source_id: e.source_hash
        for e in man.sources.values()
        if e.status in (SourceStatus.ACTIVE, SourceStatus.UPDATED)
    }
    local_fp = fingerprint_source_hashes(active_hashes)
    if pub_fp and local_fp and pub_fp != local_fp:
        issues.append(
            {
                "type": "fingerprint_mismatch",
                "manifest": local_fp,
                "published": pub_fp,
            }
        )
    for sid, ent in man.sources.items():
        if ent.status in (
            SourceStatus.REMOVED,
            SourceStatus.FAILED,
            SourceStatus.QUARANTINED,
        ):
            continue
        if ent.status not in (SourceStatus.ACTIVE, SourceStatus.UPDATED):
            continue
        ps = pub_sources.get(sid)
        if not ps:
            issues.append({"type": "missing_in_index", "source_id": sid})
            continue
        if ent.source_hash and str(ps.get("hash")) != ent.source_hash:
            issues.append(
                {
                    "type": "hash_mismatch",
                    "source_id": sid,
                    "manifest_hash": ent.source_hash,
                    "index_hash": ps.get("hash"),
                }
            )
    return {"ok": len(issues) == 0, "issues": issues}


def run_status(paths: StoragePaths) -> dict[str, Any]:
    mf = _mf(paths)
    man = Manifest.load(mf)
    meta = load_published_meta(paths)
    return {
        "manifest_sources": len(man.sources),
        "published_meta": meta,
    }


def _prefer_fallback_rows(
    primary: list[dict[str, Any]],
    fallback: list[dict[str, Any]],
) -> bool:
    if not fallback:
        return False
    if not primary:
        return True
    return len(fallback) > len(primary)


def run_query(
    paths: StoragePaths,
    question: str,
    model: str | None = None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    t_decompose_ms = 0
    t_hyde_ms = 0
    t_retrieval_ms = 0
    t_context_build_ms = 0
    t_llm_ms = 0
    t_verify_ms = 0
    question = question.strip()
    if not question:
        return {"error": "tyhjä kysymys"}
    model = model or os.environ.get("ZT_QUERY_MODEL", "claude-sonnet-4-6")
    mf = _mf(paths)
    idx = open_index(paths)
    meta = load_published_meta(paths)
    if idx is None or not meta:
        return refusal_payload()

    man = Manifest.load(mf)
    active_hashes = {
        e.source_id: e.source_hash
        for e in man.sources.values()
        if e.status in (SourceStatus.ACTIVE, SourceStatus.UPDATED)
        and e.source_hash
    }
    local_fp = fingerprint_source_hashes(active_hashes)
    pub_fp = str(meta.get("source_fingerprint", ""))
    if pub_fp and local_fp and pub_fp != local_fp:
        _log_query(
            paths,
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "question": question,
                "result": "fingerprint_drift",
                "published": pub_fp,
                "manifest": local_fp,
                "answer_provenance": "none (ei hakua — indeksi vs manifesti ei täsmää)",
            },
        )
        return {
            **refusal_payload(),
            "_error": "manifest_index_fingerprint_mismatch",
        }

    t_stage = time.perf_counter()
    if skip_query_decompose():
        sq = question.strip()
        sub_queries, rerank_query = [sq], sq
    else:
        sub_queries, rerank_query = decompose_search_queries(question, model)
    t_decompose_ms = int((time.perf_counter() - t_stage) * 1000)

    if hyde_enabled():
        t_stage = time.perf_counter()
        hyde_workers = min(4, max(1, len(sub_queries)))
        with ThreadPoolExecutor(max_workers=hyde_workers) as pool:
            sub_queries = list(pool.map(lambda q: hyde_expand(q, model), sub_queries))
        rerank_query = " ".join(sub_queries).strip() or rerank_query
        t_hyde_ms = int((time.perf_counter() - t_stage) * 1000)

    idx_dir = published_index_dir(paths)
    term_catalog_rows: list[tuple[str, float]] = []
    if idx_dir is not None:
        tcp = term_catalog_path_in_index(idx_dir, meta)
        if tcp is not None:
            term_catalog_rows = load_term_catalog(tcp)
    hint_max = _env_int("ZT_TERM_HINTS_MAX", 24)
    term_hints = select_term_hints(
        question, term_catalog_rows, max_hints=hint_max
    )
    if (
        not term_hints
        and term_catalog_rows
        and corpus_aware_rewrite_enabled()
    ):
        term_hints = top_terms_as_hints(
            term_catalog_rows, max_hints=min(8, hint_max)
        )

    retrieval_sink: dict[str, Any] = {}
    t_stage = time.perf_counter()
    top_n_ctx = int(os.environ.get("ZT_CONTEXT_CHUNKS", "10"))
    ctx_rows, _ = load_context_blocks(
        paths,
        sub_queries=sub_queries,
        rerank_query=rerank_query,
        top_n=top_n_ctx,
        index=idx,
        retrieval_telemetry=retrieval_sink,
    )
    t_retrieval_ms = int((time.perf_counter() - t_stage) * 1000)
    retrieval_attempt_count = 1
    chosen_attempt = "primary"
    fallback_reason = ""
    fallback_queries: list[str] = []
    fallback_sink: dict[str, Any] = {}

    need_fb, fb_trigger = should_trigger_query_fallback(ctx_rows, retrieval_sink)
    if need_fb and query_fallback_enabled():
        fb_sub, fb_rerank = fallback_decompose_queries(
            question,
            model,
            corpus_term_hints=term_hints if term_catalog_rows else None,
        )
        fallback_queries = list(fb_sub)
        t_stage_fb = time.perf_counter()
        with hard_retrieval_profile_env():
            fb_sub_use = fb_sub
            fb_rerank_use = fb_rerank
            if hyde_enabled():
                hyde_workers = min(4, max(1, len(fb_sub_use)))
                with ThreadPoolExecutor(max_workers=hyde_workers) as pool:
                    fb_sub_use = list(
                        pool.map(lambda q: hyde_expand(q, model), fb_sub_use)
                    )
                fb_rerank_use = " ".join(fb_sub_use).strip() or fb_rerank_use
            top_n_fb = int(os.environ.get("ZT_CONTEXT_CHUNKS", str(top_n_ctx)))
            fallback_sink = {}
            ctx_fb, _ = load_context_blocks(
                paths,
                sub_queries=fb_sub_use,
                rerank_query=fb_rerank_use,
                top_n=top_n_fb,
                index=idx,
                retrieval_telemetry=fallback_sink,
            )
        t_retrieval_ms += int((time.perf_counter() - t_stage_fb) * 1000)
        retrieval_attempt_count = 2
        fallback_reason = fb_trigger
        if _prefer_fallback_rows(ctx_rows, ctx_fb):
            ctx_rows = ctx_fb
            retrieval_sink = fallback_sink
            sub_queries = list(fb_sub_use)
            rerank_query = fb_rerank_use
            chosen_attempt = "fallback"

    telemetry = {
        "query_policy": query_policy(),
        "retrieval_attempt_count": retrieval_attempt_count,
        "retrieval_chosen_attempt": chosen_attempt,
        "term_hints": term_hints[:hint_max],
        "timing_ms": {
            "decompose": t_decompose_ms,
            "hyde": t_hyde_ms,
            "retrieval": t_retrieval_ms,
        },
        "rerank": {
            "events": list(retrieval_sink.get("rerank_events") or []),
            "reranker_model": os.environ.get(
                "ZT_RERANKER_MODEL",
                "cross-encoder/ms-marco-MiniLM-L6-v2",
            ),
        },
    }
    if fallback_reason:
        telemetry["fallback_trigger_reason"] = fallback_reason
        telemetry["fallback_queries"] = fallback_queries
        telemetry["fallback_retrieval"] = {
            "pre_rerank_pool_size": fallback_sink.get("pre_rerank_pool_size"),
            "rerank_events": list(fallback_sink.get("rerank_events") or []),
        }
    if os.environ.get("ZT_QUERY_HARD_RETRIEVAL", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        telemetry["retrieval_profile"] = "hard"
    if not ctx_rows:
        _log_query(
            paths,
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "question": question,
                "index_version": meta.get("index_version"),
                "embedding_model": meta.get("embedding_model"),
                "result": "no_retrieval",
                "retrieval_chunk_ids": [],
                "telemetry": telemetry,
                "answer_provenance": "none (haku ei palauttanut chunkkeja)",
            },
        )
        return refusal_payload()

    t_stage = time.perf_counter()
    context_str, kept_ctx_rows, context_stats = _build_context_with_budget(ctx_rows)
    t_context_build_ms = int((time.perf_counter() - t_stage) * 1000)
    telemetry["timing_ms"]["context_build"] = t_context_build_ms
    telemetry["context"] = context_stats

    system = """Olet ZT-RAG-assistentti. Vastaa VAIN JSON-muodossa ilman markdownia.
Skeema: {"answer": "...", "citations": [{"chunk_id": "...", "quote": "tarkka lainaus lähteestä", "book": "...", "chapter": "..."}]}
Jokainen faktuaalinen väite answer-kentässä pitää olla tuettu citations-listalla.
Lainaus quote pitää olla sanatarkasti (tai lähes sanatarkasti) lähdeblokista.
Jos et löydä vastausta kontekstista: {"answer": "Ei löydy lähteistäni.", "citations": []}"""

    user = f"Konteksti:\n{context_str}\n\nKysymys: {question}"
    client = anthropic.Anthropic()
    try:
        t_stage = time.perf_counter()
        resp = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        t_llm_ms = int((time.perf_counter() - t_stage) * 1000)
        telemetry["timing_ms"]["llm_answer"] = t_llm_ms
        raw_text = resp.content[0].text.strip()
        data = parse_json_response(raw_text)
        ans = ZtAnswer.model_validate(data)
    except Exception as e:
        _log_query(
            paths,
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "question": question,
                "index_version": meta.get("index_version"),
                "embedding_model": meta.get("embedding_model"),
                "error": str(e),
                "retrieval_chunk_ids": _retrieval_chunk_ids(ctx_rows),
                "telemetry": telemetry,
                "answer_provenance": "none (LLM JSON -parsinta tai validointi epäonnistui)",
            },
        )
        return refusal_payload()

    t_stage = time.perf_counter()
    ok, reason, detail = verify_full_pipeline(ans, idx, meta, kept_ctx_rows, question)
    t_verify_ms = int((time.perf_counter() - t_stage) * 1000)
    telemetry["timing_ms"]["verify"] = t_verify_ms
    telemetry["timing_ms"]["total"] = int((time.perf_counter() - t0) * 1000)
    out: dict[str, Any] = {
        "answer": ans.model_dump(),
        "verification_ok": ok,
        "verification_reason": reason,
        "verification_detail": detail,
        "index_version": meta.get("index_version"),
        "telemetry": telemetry,
    }
    if not ok:
        out["answer"] = refusal_payload()
    cite_ids = [c.chunk_id for c in ans.citations if c.chunk_id]
    _log_query(
        paths,
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "question": question,
            "sub_queries": sub_queries,
            "index_version": meta.get("index_version"),
            "embedding_model": meta.get("embedding_model"),
            "verification_ok": ok,
            "reason": reason,
            "answer": ans.model_dump(),
            "retrieval_chunk_ids": _retrieval_chunk_ids(kept_ctx_rows),
            "citation_chunk_ids": cite_ids,
            "telemetry": telemetry,
            "answer_provenance": (
                "rag: BM25+embedding-haku → top chunkit kontekstina → Anthropic LLM "
                "→ vastaus + citations (sitaatit viittaavat chunk_id / book / chapter)"
            ),
        },
    )
    return out
