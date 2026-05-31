"""Retrieve-only haku ilman LLM:ää (cli-bot / zt-retrieve)."""
from __future__ import annotations

import os
import time
from typing import Any

from devworkflow.zt_rag.index_guard import check_manifest_fingerprint, check_published_index
from devworkflow.zt_rag.index_meta import published_index_dir
from devworkflow.zt_rag.retrieve_schema import (
    chunk_for_response,
    error_payload,
    success_payload,
)
from devworkflow.zt_rag.retrieval import load_context_blocks
from devworkflow.zt_rag.storage_layout import StoragePaths
from devworkflow.zt_rag.term_catalog import (
    load_term_catalog,
    select_term_hints,
    term_catalog_path_in_index,
)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def run_retrieve(
    paths: StoragePaths,
    question: str,
    *,
    top_n: int = 5,
) -> dict[str, Any]:
    """
    Hybridihaku julkaistusta indeksistä; ei dekomponointia, HyDE:tä eikä LLM-fallbackia.
    Palauttaa retrieve_schema -yhteensopivan dictin (ok true/false).
    """
    q = question.strip()
    if not q:
        return error_payload("empty_question", "Question must not be empty")

    pub = check_published_index(paths)
    if not pub.ok:
        return error_payload(
            pub.error or "index_not_published",
            pub.message or "No published index under ZT_DATA_DIR",
            question=q,
        )

    fp = check_manifest_fingerprint(paths)
    if not fp.ok:
        return error_payload(
            fp.error or "fingerprint_mismatch",
            fp.message or "Published index fingerprint does not match manifest",
            question=q,
        )

    idx = pub.index
    meta = pub.meta or {}
    assert idx is not None

    term_catalog_rows: list[tuple[str, float]] = []
    idx_dir = published_index_dir(paths)
    if idx_dir is not None:
        tcp = term_catalog_path_in_index(idx_dir, meta)
        if tcp is not None:
            term_catalog_rows = load_term_catalog(tcp)
    hint_max = _env_int("ZT_TERM_HINTS_MAX", 24)
    term_hints = select_term_hints(q, term_catalog_rows, max_hints=hint_max)

    retrieval_sink: dict[str, Any] = {}
    t0 = time.perf_counter()
    ctx_rows, _ = load_context_blocks(
        paths,
        sub_queries=[q],
        rerank_query=q,
        top_n=max(1, top_n),
        index=idx,
        retrieval_telemetry=retrieval_sink,
        attach_rerank_scores=True,
    )
    retrieval_ms = int((time.perf_counter() - t0) * 1000)

    chunks = [chunk_for_response(r) for r in ctx_rows]
    return success_payload(
        q,
        chunks,
        meta={
            "index_version": meta.get("index_version"),
            "embedding_model": str(meta.get("embedding_model", "")),
            "source_fingerprint": str(meta.get("source_fingerprint", "")),
            "chunk_count": len(chunks),
        },
        telemetry={
            "query_policy": "fast",
            "pre_rerank_pool_size": retrieval_sink.get("pre_rerank_pool_size", 0),
            "term_hints": term_hints,
            "fingerprint_check_skipped": fp.skipped,
            "timing_ms": {"retrieval": retrieval_ms},
        },
    )
