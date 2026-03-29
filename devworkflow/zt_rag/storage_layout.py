"""Yhden zt-mcp-instanssin hakemistorakenne."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def data_root() -> Path:
    return Path(os.environ.get("ZT_DATA_DIR", "/data")).resolve()


@dataclass(frozen=True)
class StoragePaths:
    root: Path
    sources: Path
    manifests: Path
    indexes: Path
    staging: Path
    current: Path
    logs: Path
    cache: Path

    @classmethod
    def create(cls, root: Path | None = None) -> StoragePaths:
        r = (root or data_root()).resolve()
        idx = r / "indexes"
        return cls(
            root=r,
            sources=r / "sources",
            manifests=r / "manifests",
            indexes=idx,
            staging=idx / "staging",
            current=idx / "current",
            logs=r / "logs",
            cache=r / "cache",
        )

    def ensure(self) -> None:
        for p in (
            self.root,
            self.sources,
            self.manifests,
            self.staging,
            self.current,
            self.logs,
            self.cache,
        ):
            p.mkdir(parents=True, exist_ok=True)
