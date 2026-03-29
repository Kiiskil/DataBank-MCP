"""FAISS HNSW + inner product (normalisoidut embeddingit, sama kuin cosine max)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np

ANN_INDEX_BASENAME = "vectors.faiss"
ANN_BACKEND_META = "faiss_hnsw_ip"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def ann_disabled() -> bool:
    return os.environ.get("ZT_DISABLE_ANN", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def ann_min_chunks() -> int:
    """Alle tämän chunk-määrän ei rakenneta ANN:ia (brute-force riittää)."""
    return _env_int("ZT_ANN_MIN_CHUNKS", 1)


def build_ann_index(embeddings: np.ndarray, dest_dir: Path) -> dict[str, Any] | None:
    """
    Tallentaa ``dest_dir / vectors.faiss``. Palauttaa meta-kentät tai None jos ohitetaan / faiss puuttuu.
    """
    if ann_disabled():
        return None
    n, dim = int(embeddings.shape[0]), int(embeddings.shape[1])
    if n < ann_min_chunks():
        return None
    try:
        import faiss
    except ImportError:
        return None

    m = _env_int("ZT_ANN_HNSW_M", 32)
    ef_construction = _env_int("ZT_ANN_EF_CONSTRUCTION", 200)
    ef_search = _env_int("ZT_ANN_EF_SEARCH", 64)

    E = np.ascontiguousarray(embeddings, dtype=np.float32)
    index = faiss.index_factory(dim, f"HNSW{m},Flat", faiss.METRIC_INNER_PRODUCT)
    index.hnsw.efConstruction = ef_construction
    index.add(E)
    index.hnsw.efSearch = ef_search

    path = dest_dir / ANN_INDEX_BASENAME
    faiss.write_index(index, str(path))
    return {
        "ann_backend": ANN_BACKEND_META,
        "ann_index": ANN_INDEX_BASENAME,
        "ann_space": "inner_product",
        "vector_count": n,
        "embedding_dim": dim,
        "ann_hnsw_M": m,
        "ann_ef_construction": ef_construction,
        "ann_ef_search_default": ef_search,
    }


def load_ann_index(
    base: Path,
    meta: dict[str, Any],
    *,
    embedding_dim: int,
) -> Any | None:
    """Palauttaa faiss.Index tai None (brute-force -polku)."""
    if ann_disabled():
        return None
    if str(meta.get("ann_backend", "")) != ANN_BACKEND_META:
        return None
    rel = meta.get("ann_index")
    if not rel:
        return None
    path = base / str(rel)
    if not path.is_file():
        return None
    try:
        import faiss
    except ImportError:
        return None

    try:
        index = faiss.read_index(str(path))
    except Exception:
        return None
    n_meta = int(meta.get("vector_count", 0) or 0)
    if n_meta > 0 and hasattr(index, "ntotal") and int(index.ntotal) != n_meta:
        return None
    d_meta = int(meta.get("embedding_dim", embedding_dim) or embedding_dim)
    if int(index.d) != d_meta:
        return None
    return index


def ann_knn_doc_indices(ann: Any, query_vec: np.ndarray, k: int) -> list[int]:
    """Yksi kysely → dokumenttirivi-indeksit (int), pituus ≤ k."""
    ef = max(_env_int("ZT_ANN_EF_SEARCH", 64), min(k * 4, 512))
    if hasattr(ann, "hnsw"):
        ann.hnsw.efSearch = ef
    q = np.ascontiguousarray(query_vec.reshape(1, -1), dtype=np.float32)
    _distances, indices = ann.search(q, k)
    row = indices[0]
    return [int(x) for x in row if int(x) >= 0]
