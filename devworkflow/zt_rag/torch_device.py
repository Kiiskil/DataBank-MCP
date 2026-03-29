"""PyTorch-laite ja embedding-batch-koko ZT-RAG:lle (CPU / ROCm=cuda API).

``ZT_INGEST_REQUIRE_CUDA=1``: ingest (`run_ingest`) epäonnistuu jos ``torch.cuda`` ei ole
käytössä — estää hiljaisen CPU-ingestin GPU-kontissa.
"""
from __future__ import annotations

import os


def resolve_zt_torch_device() -> str:
    """
    ZT_TORCH_DEVICE: auto | cpu | cuda

    ROCm-PyTorchissa ``torch.cuda.is_available()`` on tyypillisesti True (HIP).
    Tuntematon arvo → cpu (turvallinen oletus).
    """
    import torch

    raw = os.environ.get("ZT_TORCH_DEVICE", "auto").strip().lower()
    if raw in ("", "auto"):
        return "cuda" if torch.cuda.is_available() else "cpu"
    if raw == "cpu":
        return "cpu"
    if raw in ("cuda", "gpu"):
        return "cuda" if torch.cuda.is_available() else "cpu"
    return "cpu"


def zt_embed_batch_size(default: int = 32) -> int:
    """
    ZT_EMBED_BATCH: positiivinen kokonaisluku (encode-batch), yliajaa kaiken.

    Ilman yliajoa: CUDA/ROCm (``torch.cuda``) → oletus vähintään 64, muuten ``default``.
    """
    raw = os.environ.get("ZT_EMBED_BATCH", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    if resolve_zt_torch_device() == "cuda":
        return max(64, default)
    return max(1, default)
