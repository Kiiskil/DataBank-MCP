"""Chunk-tietue (ingest + julkaisu); ei parseri-riippuvuuksia."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class ChunkRecord:
    chunk_id: str
    source_id: str
    source_hash: str
    chunk_hash: str
    title: str
    section: str
    page: int | None
    chunk_index: int
    char_start: int
    char_end: int
    text: str
    heading_path: str = ""
    lang: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)
