"""BM25 + vektori-indeksin rakentaminen ja atominen julkaisu."""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import bm25s
import numpy as np
from sentence_transformers import SentenceTransformer

from devworkflow.zt_rag.embedding_incremental import (
    encode_corpus_with_hash_reuse,
    load_reusable_vectors_from_published_index,
)
from devworkflow.zt_rag.ingest import ChunkRecord
from devworkflow.zt_rag.query_rewrite import term_catalog_feature_enabled
from devworkflow.zt_rag.term_catalog import (
    TERM_CATALOG_FILE,
    build_term_weights,
    write_term_catalog_jsonl,
)
from devworkflow.zt_rag.source_manifest import Manifest, SourceStatus
from devworkflow.zt_rag.storage_layout import StoragePaths
from devworkflow.zt_rag.torch_device import resolve_zt_torch_device, zt_embed_batch_size
from devworkflow.zt_rag.vector_ann import build_ann_index
from devworkflow.zt_rag.versioning import fingerprint_source_hashes

CHUNK_IDS_FILE = "chunk_ids.txt"


def load_published_chunk_ids(base: Path, meta: dict[str, Any]) -> list[str]:
    """Uusi: ``chunk_ids.txt``; vanha: ``meta["chunk_ids"]``."""
    cfile = meta.get("chunk_ids_file")
    if cfile:
        cf = str(cfile).strip()
        if cf and "/" not in cf and "\\" not in cf and ".." not in cf:
            p = (base.resolve() / cf)
            if p.is_file():
                out: list[str] = []
                with p.open(encoding="utf-8") as f:
                    for line in f:
                        s = line.strip()
                        if s:
                            out.append(s)
                return out
    raw = meta.get("chunk_ids")
    if isinstance(raw, list):
        return [str(x) for x in raw]
    return []


def published_chunk_count(paths: StoragePaths, meta: dict[str, Any]) -> int:
    """Chunkkien lukumäärä julkaistusta indeksistä (tiedosto tai meta)."""
    d = published_index_dir(paths)
    cfile = meta.get("chunk_ids_file")
    if d is not None and cfile:
        cf = str(cfile).strip()
        if cf and "/" not in cf and "\\" not in cf and ".." not in cf:
            p = d / cf
            if p.is_file():
                n = 0
                with p.open(encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            n += 1
                return n
    ids = meta.get("chunk_ids")
    if isinstance(ids, list):
        return len(ids)
    return int(meta.get("chunk_ids_count", 0) or 0)


def _is_e5_model(name: str) -> bool:
    return "e5" in name.lower()


def _embedding_model_name() -> str:
    return os.environ.get(
        "ZT_EMBEDDING_MODEL",
        "intfloat/multilingual-e5-base",
    )


def _next_version(paths: StoragePaths) -> int:
    cur = paths.current
    if cur.is_symlink():
        meta = cur.resolve() / "meta.json"
    elif cur.is_dir():
        meta = cur / "meta.json"
    else:
        return 1
    if not meta.exists():
        return 1
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
        return int(data.get("index_version", 0)) + 1
    except Exception:
        return 1


def build_and_publish(
    paths: StoragePaths,
    manifest: Manifest,
    chunks: list[ChunkRecord],
    manifest_save_path: Path,
) -> dict[str, Any]:
    """
    Rakentaa staging-indeksin ja julkaisee atomisesti (current-symlink).
    """
    paths.ensure()
    if not chunks:
        return {"ok": False, "error": "no_chunks"}

    active_hashes = {
        e.source_id: e.source_hash
        for e in manifest.sources.values()
        if e.status in (SourceStatus.ACTIVE, SourceStatus.UPDATED)
        and e.source_hash
    }
    fp = fingerprint_source_hashes(active_hashes)

    versions_dir = paths.indexes / "versions"
    versions_dir.mkdir(parents=True, exist_ok=True)
    staging_root = paths.staging
    staging_root.mkdir(parents=True, exist_ok=True)

    current_link = paths.current
    current_link.parent.mkdir(parents=True, exist_ok=True)
    next_v = _next_version(paths)

    build_dir = staging_root / f"build_{next_v}_{int(datetime.now(timezone.utc).timestamp())}"
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True)

    corpus = [c.text for c in chunks]
    chunk_ids = [c.chunk_id for c in chunks]

    retriever = bm25s.BM25()
    tokens = bm25s.tokenize(corpus, stopwords=None)
    retriever.index(tokens)
    bm25_dir = build_dir / "bm25"
    retriever.save(str(bm25_dir))

    model_name = _embedding_model_name()
    device = resolve_zt_torch_device()
    model = SentenceTransformer(model_name, device=device)

    reuse: dict[str, np.ndarray] = {}
    cache_disabled = os.environ.get("ZT_DISABLE_EMBED_CACHE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if not cache_disabled:
        prev_dir = published_index_dir(paths)
        if prev_dir is not None:
            reuse = load_reusable_vectors_from_published_index(
                prev_dir,
                expected_embedding_model=model_name,
            )

    embeddings, emb_stats = encode_corpus_with_hash_reuse(
        model,
        model_name=model_name,
        chunks=chunks,
        corpus=corpus,
        reuse_by_hash=reuse,
        e5_passage_prompt=_is_e5_model(model_name),
        batch_size=zt_embed_batch_size(32),
    )
    np.save(build_dir / "embeddings.npy", embeddings)

    ann_fields: dict[str, Any] = {}
    ann_meta = build_ann_index(embeddings, build_dir)
    if ann_meta:
        ann_fields.update(ann_meta)

    (build_dir / CHUNK_IDS_FILE).write_text(
        "\n".join(chunk_ids) + ("\n" if chunk_ids else ""),
        encoding="utf-8",
    )

    chunks_path = build_dir / "chunks.jsonl"
    with chunks_path.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c.to_json_dict(), ensure_ascii=False) + "\n")

    term_catalog_entries = 0
    term_catalog_file_meta = ""
    if term_catalog_feature_enabled():
        tw_path = build_dir / TERM_CATALOG_FILE
        weights = build_term_weights(chunks, manifest)
        term_catalog_entries = write_term_catalog_jsonl(tw_path, weights)
        if term_catalog_entries > 0:
            term_catalog_file_meta = TERM_CATALOG_FILE
        else:
            tw_path.unlink(missing_ok=True)

    meta = {
        "index_version": next_v,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "embedding_model": model_name,
        "st_encode_e5_mode": "prompt" if _is_e5_model(model_name) else "none",
        "source_fingerprint": fp,
        "chunk_ids_file": CHUNK_IDS_FILE,
        "chunk_ids_count": len(chunk_ids),
        **ann_fields,
        "term_catalog_file": term_catalog_file_meta,
        "term_catalog_entries": term_catalog_entries,
        "sources": {
            sid: {
                "hash": manifest.sources[sid].source_hash,
                "chunk_count": manifest.sources[sid].chunk_count,
                "path": manifest.sources[sid].path,
                "status": manifest.sources[sid].status.value,
            }
            for sid in active_hashes
            if sid in manifest.sources
        },
    }
    (build_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    target = versions_dir / f"v{next_v}"
    if target.exists():
        shutil.rmtree(target)
    shutil.move(str(build_dir), str(target))

    new_link = paths.indexes / "current.new"

    def _remove_slot(p: Path) -> None:
        if p.is_symlink() or p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p)

    # Vanha `current` saattaa olla hakemisto (ei symlink) → os.replace epäonnistuu
    _remove_slot(new_link)
    _remove_slot(current_link)

    new_link.symlink_to(target.resolve(), target_is_directory=True)
    os.replace(new_link, current_link)

    manifest.save(manifest_save_path)

    out: dict[str, Any] = {
        "ok": True,
        "index_version": next_v,
        "path": str(target),
        "chunks": len(chunks),
        "source_fingerprint": fp,
        "embedding_incremental": emb_stats,
        "term_catalog_entries": term_catalog_entries,
    }
    if ann_meta:
        out["ann"] = {k: ann_meta[k] for k in ("ann_backend", "ann_index") if k in ann_meta}
    return out


def load_published_meta(paths: StoragePaths) -> dict[str, Any] | None:
    cur = paths.current
    if cur.is_symlink():
        meta = cur.resolve() / "meta.json"
    elif cur.is_dir():
        meta = cur / "meta.json"
    else:
        return None
    if not meta.exists():
        return None
    return json.loads(meta.read_text(encoding="utf-8"))


def published_index_dir(paths: StoragePaths) -> Path | None:
    cur = paths.current
    if cur.is_symlink():
        return cur.resolve()
    if cur.is_dir() and (cur / "meta.json").exists():
        return cur
    return None
