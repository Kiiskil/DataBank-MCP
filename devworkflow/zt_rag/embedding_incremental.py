"""Inkrementaalinen embedding: uudelleenkäyttö chunk_hash + edellinen julkaistu indeksi.

Sama embedding-malli + sama chunk_hash (normalisoidun tekstin sisältöhash) → sama vektori
voidaan kopioida edellisestä ``embeddings.npy``-rivistä ilman uutta ``encode``-kutsua.

Mallin vaihto (``ZT_EMBEDDING_MODEL`` / meta) tyhjentää välimuistin automaattisesti.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer

from devworkflow.zt_rag.ingest import ChunkRecord


def load_reusable_vectors_from_published_index(
    index_dir: Path,
    *,
    expected_embedding_model: str,
) -> dict[str, np.ndarray]:
    """
    Lukee julkaistun indeksin ``chunks.jsonl`` + ``embeddings.npy`` ja rakentaa
    ``chunk_hash -> np.ndarray(shape=(D,), dtype=float32)``.

    Rivijärjestys: i:s ei-tyhjä JSONL-rivi vastaa ``embeddings[i]``:ää (kuten julkaisussa).
    """
    meta_path = index_dir / "meta.json"
    emb_path = index_dir / "embeddings.npy"
    chunks_path = index_dir / "chunks.jsonl"
    if not meta_path.is_file() or not emb_path.is_file() or not chunks_path.is_file():
        return {}
    try:
        meta: dict[str, Any] = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if str(meta.get("embedding_model", "")) != expected_embedding_model:
        return {}
    # Vanhat e5-indeksit (prefiksi merkkijonossa) eivät täsmää prompt-encodeen → ei sekoiteta vektoreita.
    if "e5" in expected_embedding_model.lower():
        if str(meta.get("st_encode_e5_mode", "")) != "prompt":
            return {}
    try:
        E = np.load(emb_path, mmap_mode="r")
    except OSError:
        return {}
    if E.ndim != 2 or E.shape[0] == 0:
        return {}
    out: dict[str, np.ndarray] = {}
    row_i = 0
    try:
        with chunks_path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                if row_i >= E.shape[0]:
                    return {}
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    return {}
                h = str(d.get("chunk_hash", "") or "")
                if h:
                    out[h] = np.asarray(E[row_i], dtype=np.float32).copy()
                row_i += 1
    except OSError:
        return {}
    if row_i != E.shape[0]:
        # Rivimäärä ei täsmää → ei luoteta välimuistiin
        return {}
    if not out:
        return {}
    return out


def encode_corpus_with_hash_reuse(
    model: SentenceTransformer,
    *,
    model_name: str,
    chunks: list[ChunkRecord],
    corpus: list[str],
    reuse_by_hash: dict[str, np.ndarray],
    e5_passage_prompt: bool,
    batch_size: int,
) -> tuple[np.ndarray, dict[str, int]]:
    """
    Täyttää embeddings-matriisin järjestyksessä ``chunks`` / ``corpus``.

    Palauttaa ``(embeddings, stats)`` jossa stats: hits, misses, unique_encoded.
    """
    n = len(chunks)
    dim = int(model.get_sentence_embedding_dimension())
    out = np.zeros((n, dim), dtype=np.float32)

    misses_by_hash: dict[str, list[int]] = {}
    hits = 0

    for i, c in enumerate(chunks):
        vec = reuse_by_hash.get(c.chunk_hash)
        if vec is not None and vec.shape == (dim,):
            out[i] = vec
            hits += 1
        else:
            misses_by_hash.setdefault(c.chunk_hash, []).append(i)

    unique_hashes = list(misses_by_hash.keys())
    texts_to_encode: list[str] = []
    for h in unique_hashes:
        idx0 = misses_by_hash[h][0]
        texts_to_encode.append(corpus[idx0])

    if texts_to_encode:
        enc_kw: dict[str, Any] = {
            "show_progress_bar": False,
            "normalize_embeddings": True,
            "batch_size": batch_size,
        }
        if e5_passage_prompt:
            enc_kw["prompt"] = "passage: "
        new_vecs = model.encode(texts_to_encode, **enc_kw)
        new_arr = np.asarray(new_vecs, dtype=np.float32)
        if new_arr.shape != (len(unique_hashes), dim):
            raise RuntimeError(
                f"encode shape mismatch: got {new_arr.shape}, expected "
                f"({len(unique_hashes)}, {dim})"
            )
        for h, nv in zip(unique_hashes, new_arr):
            for idx in misses_by_hash[h]:
                out[idx] = nv

    misses = sum(len(v) for v in misses_by_hash.values())
    return out, {
        "hits": hits,
        "misses": misses,
        "unique_encoded": len(unique_hashes),
    }
