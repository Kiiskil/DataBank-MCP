"""Hybridihaku: BM25 + vektori + RRF + cross-encoder reranking."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import bm25s
import numpy as np
from sentence_transformers import CrossEncoder, SentenceTransformer

from devworkflow.zt_rag.index_publish import load_published_chunk_ids, published_index_dir
from devworkflow.zt_rag.vector_ann import ann_knn_doc_indices, load_ann_index
from devworkflow.zt_rag.storage_layout import StoragePaths
from devworkflow.zt_rag.torch_device import resolve_zt_torch_device, zt_embed_batch_size


def _is_e5_model(name: str) -> bool:
    return "e5" in name.lower()


def _reranker_model_name() -> str:
    return os.environ.get(
        "ZT_RERANKER_MODEL",
        "cross-encoder/ms-marco-MiniLM-L6-v2",
    )


@lru_cache(maxsize=8)
def _encoder(model_name: str, device: str) -> SentenceTransformer:
    return SentenceTransformer(model_name, device=device)


@lru_cache(maxsize=8)
def _cross_encoder(model_name: str, device: str) -> CrossEncoder:
    return CrossEncoder(model_name, device=device)


class PublishedIndex:
    def __init__(self, base: Path):
        self.base = base.resolve()
        self.meta: dict[str, Any] = json.loads(
            (self.base / "meta.json").read_text(encoding="utf-8")
        )
        self.chunk_ids: list[str] = load_published_chunk_ids(self.base, self.meta)
        self.id_to_row: dict[str, int] = {
            cid: i for i, cid in enumerate(self.chunk_ids)
        }
        self.retriever = bm25s.BM25.load(str(self.base / "bm25"), load_corpus=True)
        self.embeddings: np.ndarray = np.load(
            self.base / "embeddings.npy",
            mmap_mode="r",
        )
        self.model_name: str = str(self.meta.get("embedding_model", ""))
        self._encoder = _encoder(self.model_name, resolve_zt_torch_device())
        self._chunks_map: dict[str, dict[str, Any]] | None = None
        emb_n, emb_d = int(self.embeddings.shape[0]), int(self.embeddings.shape[1])
        self._ann_index: Any | None = None
        if len(self.chunk_ids) == emb_n:
            ann = load_ann_index(self.base, self.meta, embedding_dim=emb_d)
            vc = int(self.meta.get("vector_count", 0) or 0)
            if ann is not None and vc == emb_n:
                self._ann_index = ann

    def _build_chunks_map(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        path = self.base / "chunks.jsonl"
        with path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                d = json.loads(line)
                out[str(d["chunk_id"])] = d
        return out

    @property
    def chunks_map(self) -> dict[str, dict[str, Any]]:
        """Yksi läpikäynti chunks.jsonl:stä; jaettu load_chunk- ja verify-polulle."""
        if self._chunks_map is None:
            self._chunks_map = self._build_chunks_map()
        return self._chunks_map

    def load_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        return self.chunks_map.get(chunk_id)

    def load_all_chunks_map(self) -> dict[str, dict[str, Any]]:
        """Sama välimuisti kuin chunks_map (ei toista tiedoston lukua)."""
        return self.chunks_map


def _rrf(rank_lists: list[list[int]], k: int = 60) -> list[int]:
    scores: dict[int, float] = {}
    for lst in rank_lists:
        for rank, doc_i in enumerate(lst):
            scores[doc_i] = scores.get(doc_i, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.keys(), key=lambda x: scores[x], reverse=True)


def open_index(paths: StoragePaths) -> PublishedIndex | None:
    d = published_index_dir(paths)
    if d is None:
        return None
    return PublishedIndex(d)


def _encode_queries_for_retrieval(
    index: PublishedIndex,
    queries: list[str],
) -> np.ndarray:
    """Yksi tai useampi kyselyvektori; e5: ``prompt='query: '`` (ei erillistä tekstiprefiksiä)."""
    if not queries:
        dim = int(index._encoder.get_sentence_embedding_dimension())
        return np.zeros((0, dim), dtype=np.float32)
    kw: dict[str, Any] = {
        "show_progress_bar": False,
        "normalize_embeddings": True,
        "batch_size": max(zt_embed_batch_size(32), len(queries)),
    }
    if _is_e5_model(index.model_name):
        kw["prompt"] = "query: "
    emb = index._encoder.encode(queries, **kw)
    return np.asarray(emb, dtype=np.float32)


def _rerank(
    query: str,
    candidates: list[dict[str, Any]],
    top_n: int,
) -> list[dict[str, Any]]:
    """Cross-encoder reranking: pisteytä query+passage -parit ja palauta top_n."""
    if not candidates:
        return []
    reranker = _cross_encoder(_reranker_model_name(), resolve_zt_torch_device())
    pairs = [(query, str(c.get("text", ""))) for c in candidates]
    scores = reranker.predict(pairs, show_progress_bar=False)
    scored = sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:top_n]]


def hybrid_retrieve(
    index: PublishedIndex,
    query: str,
    top_k_fusion: int = 50,
    top_n: int = 10,
    rerank: bool = True,
    query_embedding: np.ndarray | None = None,
    *,
    rerank_telemetry: list[dict[str, Any]] | None = None,
    telemetry_stage: str = "hybrid_retrieve",
) -> list[dict[str, Any]]:
    ov = os.environ.get("ZT_TOP_K_FUSION", "").strip()
    if ov:
        try:
            top_k_fusion = max(1, int(ov))
        except ValueError:
            pass
    if not index.chunk_ids:
        return []

    q_tokens = bm25s.tokenize([query], stopwords=None)
    _scores, dids = index.retriever.retrieve(
        q_tokens, k=min(top_k_fusion, len(index.chunk_ids))
    )
    arr = np.asarray(dids)
    if arr.ndim == 2:
        arr = arr[0]
    bm25_order = [int(x) for x in arr.flatten()[:top_k_fusion]]

    if query_embedding is not None:
        qv = np.asarray(query_embedding, dtype=np.float32).reshape(-1)
    else:
        q_emb = _encode_queries_for_retrieval(index, [query])
        qv = np.asarray(q_emb[0], dtype=np.float32).reshape(-1)
    E = index.embeddings
    k_vec = min(top_k_fusion, len(index.chunk_ids))
    if index._ann_index is not None and k_vec > 0:
        vec_order = ann_knn_doc_indices(index._ann_index, qv, k_vec)
    else:
        sim = E @ qv
        vec_order = list(np.argsort(-sim).flatten()[:k_vec])

    fused = _rrf([bm25_order, vec_order], k=60)

    pre_rerank_n = min(top_k_fusion, len(fused))
    candidates: list[dict[str, Any]] = []
    for i in fused:
        if i < 0 or i >= len(index.chunk_ids):
            continue
        cid = index.chunk_ids[i]
        row = index.load_chunk(cid)
        if row:
            candidates.append(row)
        if len(candidates) >= pre_rerank_n:
            break

    use_rerank, decision = _rerank_decision(
        requested=rerank,
        candidate_count=len(candidates),
        top_n=top_n,
    )
    if rerank_telemetry is not None and rerank:
        rerank_telemetry.append({"stage": telemetry_stage, **decision})
    if use_rerank and candidates:
        return _rerank(query, candidates, top_n)
    return candidates[:top_n]


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _rerank_decision(
    *,
    requested: bool,
    candidate_count: int,
    top_n: int,
) -> tuple[bool, dict[str, Any]]:
    """Palauttaa (ajetaanko rerank, telemetriadict)."""
    policy = os.environ.get("ZT_RERANK_POLICY", "always").strip().lower() or "always"
    min_gap = _env_int("ZT_RERANK_MIN_GAP", 2)
    default_min = max(top_n + min_gap, top_n + 1)
    min_candidates = _env_int("ZT_RERANK_MIN_CANDIDATES", default_min)

    base: dict[str, Any] = {
        "policy": policy,
        "requested": requested,
        "candidate_count": candidate_count,
        "top_n": top_n,
    }
    if not requested:
        return False, {
            **base,
            "executed": False,
            "skip_reason": "not_requested",
        }
    if policy in ("off", "0", "false", "no"):
        return False, {
            **base,
            "executed": False,
            "skip_reason": "policy_off",
        }
    if policy in ("adaptive", "auto"):
        base_adaptive = {
            **base,
            "min_candidates_threshold": min_candidates,
        }
        ok = candidate_count >= min_candidates
        return ok, {
            **base_adaptive,
            "executed": ok,
            "skip_reason": (
                "adaptive_threshold_met" if ok else "adaptive_below_threshold"
            ),
        }
    return True, {
        **base,
        "executed": True,
        "skip_reason": "policy_always",
    }


def multi_query_retrieve(
    index: PublishedIndex,
    queries: list[str],
    *,
    rerank_query: str,
    top_n: int = 10,
    rerank_telemetry: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Hae usealla alakyselyllä: hybrid per kysely ilman rerankia, RRF yhdistää, yksi rerank."""
    uniq_q: list[str] = []
    seen: set[str] = set()
    for q in queries:
        k = q.strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        uniq_q.append(q.strip())
    if not uniq_q:
        return []

    k_per = _env_int("ZT_MULTI_QUERY_K_PER", 30)
    pool = _env_int("ZT_MULTI_QUERY_POOL", 60)
    fusion_k = _env_int("ZT_MULTI_QUERY_RRF_K", 60)

    if len(uniq_q) == 1:
        return hybrid_retrieve(
            index,
            uniq_q[0],
            top_k_fusion=max(50, k_per),
            top_n=top_n,
            rerank=True,
            rerank_telemetry=rerank_telemetry,
            telemetry_stage="single_query",
        )

    q_matrix = _encode_queries_for_retrieval(index, uniq_q)
    rank_lists: list[list[int]] = []
    for i, q in enumerate(uniq_q):
        rows = hybrid_retrieve(
            index,
            q,
            top_k_fusion=k_per,
            top_n=k_per,
            rerank=False,
            query_embedding=np.asarray(q_matrix[i], dtype=np.float32),
        )
        doc_ranks: list[int] = []
        for row in rows:
            cid = str(row.get("chunk_id", ""))
            di = index.id_to_row.get(cid)
            if di is not None:
                doc_ranks.append(di)
        rank_lists.append(doc_ranks)

    fused_order = _rrf(rank_lists, k=fusion_k)
    candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for di in fused_order:
        if len(candidates) >= pool:
            break
        if di < 0 or di >= len(index.chunk_ids):
            continue
        cid = index.chunk_ids[di]
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        row = index.load_chunk(cid)
        if row:
            candidates.append(row)

    if not candidates:
        return []
    use_rerank, decision = _rerank_decision(
        requested=True,
        candidate_count=len(candidates),
        top_n=top_n,
    )
    if rerank_telemetry is not None:
        rerank_telemetry.append({"stage": "multi_query_final", **decision})
    if use_rerank:
        return _rerank(rerank_query, candidates, top_n)
    return candidates[:top_n]


def infer_pre_rerank_pool_size(rerank_events: list[dict[str, Any]]) -> int:
    """
    Suurin ``candidate_count`` rerank-telemetrian tapahtumista.

    Monikyselyhaussa välivaiheiden (per alakysely, ``rerank=False``) poolikokoja
    ei kirjata — tämä heijastaa yhdistettyä / lopullista rerank-päätöstä.
    """
    m = 0
    for ev in rerank_events:
        c = ev.get("candidate_count")
        if isinstance(c, int):
            m = max(m, c)
    return m


def load_context_blocks(
    paths: StoragePaths,
    *,
    sub_queries: list[str],
    rerank_query: str,
    top_n: int = 10,
    index: PublishedIndex | None = None,
    retrieval_telemetry: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], PublishedIndex | None]:
    idx = index if index is not None else open_index(paths)
    if idx is None:
        return [], None
    rerank_events: list[dict[str, Any]] = []
    rows = multi_query_retrieve(
        idx,
        sub_queries,
        rerank_query=rerank_query,
        top_n=top_n,
        rerank_telemetry=rerank_events,
    )
    if retrieval_telemetry is not None:
        retrieval_telemetry["rerank_events"] = rerank_events
        # Katso infer_pre_rerank_pool_size: ei välikutsujen max poolia multi-queryssä.
        retrieval_telemetry["pre_rerank_pool_size"] = infer_pre_rerank_pool_size(
            rerank_events
        )
    return rows, idx
