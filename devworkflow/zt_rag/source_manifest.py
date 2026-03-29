"""Lähdemanifesti: totuuslähteet ja elinkaari."""
from __future__ import annotations

import json
import uuid
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class SourceStatus(str, Enum):
    ACTIVE = "active"
    UPDATED = "updated"
    REMOVED = "removed"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class SourceEntry(BaseModel):
    source_id: str
    path: str
    file_type: str
    source_hash: str = ""
    ingest_status: str = "pending"
    parser_state: str = ""
    error_code: str = ""
    indexed_at: str = ""
    indexed_source_hash: str = ""
    chunk_count: int = 0
    status: SourceStatus = SourceStatus.ACTIVE


class Manifest(BaseModel):
    version: int = 1
    sources: dict[str, SourceEntry] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Manifest:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.model_validate(data)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            self.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def upsert_path(self, file_path: Path, file_type: str) -> SourceEntry:
        key = str(file_path.resolve())
        sid = None
        for e in self.sources.values():
            if e.path == key:
                sid = e.source_id
                break
        if sid is None:
            sid = str(uuid.uuid4())[:12]
        ent = SourceEntry(
            source_id=sid,
            path=key,
            file_type=file_type.lower(),
            status=SourceStatus.ACTIVE,
            ingest_status="synced",
        )
        self.sources[sid] = ent
        return ent

    def mark_removed_missing(self, existing_paths: set[str]) -> None:
        for e in self.sources.values():
            if e.path not in existing_paths and e.status == SourceStatus.ACTIVE:
                e.status = SourceStatus.REMOVED


def manifest_path(paths_manifest_dir: Path) -> Path:
    return paths_manifest_dir / "sources.json"
