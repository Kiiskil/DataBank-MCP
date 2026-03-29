"""Normalisointi ja sisältöhashit (lähdeversiointi)."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path


def normalize_for_match(text: str) -> str:
    """NFKC, soft hyphen pois, whitespace yhdeksi."""
    t = unicodedata.normalize("NFKC", text or "")
    t = t.replace("\u00ad", "")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def content_hash(normalized_text: str) -> str:
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def fingerprint_source_hashes(source_id_to_hash: dict[str, str]) -> str:
    """Deterministinen sormenjälki kaikista aktiivisista lähteistä."""
    parts = [f"{sid}:{h}" for sid, h in sorted(source_id_to_hash.items())]
    joined = "|".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
