"""Julkaistun indeksin metatiedot (ei ingest / ei indeksin rakennusta)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from devworkflow.zt_rag.storage_layout import StoragePaths

CHUNK_IDS_FILE = "chunk_ids.txt"


def load_published_chunk_ids(base: Path, meta: dict[str, Any]) -> list[str]:
    """Uusi: ``chunk_ids.txt``; vanha: ``meta["chunk_ids"]``."""
    cfile = meta.get("chunk_ids_file")
    if cfile:
        cf = str(cfile).strip()
        if cf and "/" not in cf and "\\" not in cf and ".." not in cf:
            p = base.resolve() / cf
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


def published_index_dir(paths: StoragePaths) -> Path | None:
    cur = paths.current
    if cur.is_symlink():
        return cur.resolve()
    if cur.is_dir() and (cur / "meta.json").exists():
        return cur
    return None


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
