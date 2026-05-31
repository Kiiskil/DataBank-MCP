"""Julkaistun indeksin ja manifest-fingerprintin tarkistukset (query + retrieve)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from devworkflow.zt_rag.index_meta import load_published_meta
from devworkflow.zt_rag.retrieval import PublishedIndex, open_index
from devworkflow.zt_rag.source_manifest import Manifest, SourceStatus, manifest_path
from devworkflow.zt_rag.storage_layout import StoragePaths
from devworkflow.zt_rag.versioning import fingerprint_source_hashes


@dataclass(frozen=True)
class PublishedIndexCheck:
    ok: bool
    index: PublishedIndex | None = None
    meta: dict[str, Any] | None = None
    error: str = ""
    message: str = ""


@dataclass(frozen=True)
class FingerprintCheck:
    ok: bool
    skipped: bool = False
    error: str = ""
    message: str = ""
    published: str = ""
    manifest: str = ""


def _manifest_file(paths: StoragePaths) -> Path:
    return manifest_path(paths.manifests)


def manifest_has_active_sources(paths: StoragePaths) -> bool:
    """True jos manifests/sources.json on olemassa ja sisältää aktiivisia lähteitä."""
    mf = _manifest_file(paths)
    if not mf.exists():
        return False
    man = Manifest.load(mf)
    for ent in man.sources.values():
        if ent.status in (SourceStatus.ACTIVE, SourceStatus.UPDATED) and ent.source_hash:
            return True
    return False


def check_published_index(paths: StoragePaths) -> PublishedIndexCheck:
    idx = open_index(paths)
    meta = load_published_meta(paths)
    if idx is None or not meta:
        return PublishedIndexCheck(
            ok=False,
            error="index_not_published",
            message="No published index under ZT_DATA_DIR",
        )
    return PublishedIndexCheck(ok=True, index=idx, meta=meta)


def check_manifest_fingerprint(paths: StoragePaths) -> FingerprintCheck:
    """
    Vertaa manifestin fingerprintia julkaistuun metaan.
    Puuttuva/tyhjä manifest (export-paketti) → skip, ok=True.
    """
    pub = check_published_index(paths)
    if not pub.ok or pub.meta is None:
        return FingerprintCheck(
            ok=False,
            error="index_not_published",
            message="No published index under ZT_DATA_DIR",
        )

    if not manifest_has_active_sources(paths):
        return FingerprintCheck(ok=True, skipped=True)

    man = Manifest.load(_manifest_file(paths))
    active_hashes = {
        e.source_id: e.source_hash
        for e in man.sources.values()
        if e.status in (SourceStatus.ACTIVE, SourceStatus.UPDATED)
        and e.source_hash
    }
    local_fp = fingerprint_source_hashes(active_hashes)
    pub_fp = str(pub.meta.get("source_fingerprint", ""))
    if pub_fp and local_fp and pub_fp != local_fp:
        return FingerprintCheck(
            ok=False,
            error="fingerprint_mismatch",
            message="Published index fingerprint does not match manifest",
            published=pub_fp,
            manifest=local_fp,
        )
    return FingerprintCheck(ok=True, published=pub_fp, manifest=local_fp)
