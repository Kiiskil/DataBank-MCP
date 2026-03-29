"""Retrieval-kontekstin sanitointi (prompt-injektion torjunta)."""
from __future__ import annotations

import re
import unicodedata


_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def sanitize_retrieved_text(text: str, max_len: int = 120_000) -> str:
    """Poista kontrollimerkit, normalisoi ja rajaa pituutta."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = _CTRL.sub("", t)
    if len(t) > max_len:
        t = t[:max_len] + "\n\n[... katkaistu ...]"
    return t


def wrap_source_block(chunk_id: str, title: str, body: str) -> str:
    """Eristä lähde selkeisiin rajamerkkeihin."""
    return (
        f"---BEGIN_SOURCE chunk_id={chunk_id} title={title!r}---\n"
        f"{body}\n"
        f"---END_SOURCE chunk_id={chunk_id}---"
    )
