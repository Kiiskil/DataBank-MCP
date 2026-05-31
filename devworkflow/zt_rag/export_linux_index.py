"""Julkaistun indeksin pakkaus cli-bot-databank-bundleksi (ei lähdetiedostoja)."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from devworkflow.zt_rag.index_publish import (
    CHUNK_IDS_FILE,
    load_published_meta,
    published_index_dir,
)
from devworkflow.zt_rag.storage_layout import StoragePaths
from devworkflow.zt_rag.term_catalog import TERM_CATALOG_FILE
from devworkflow.zt_rag.vector_ann import ANN_INDEX_BASENAME

# Kopioitavat tiedostot juuresta (published index -hakemisto)
_INDEX_ROOT_FILES = (
    "meta.json",
    "chunks.jsonl",
    CHUNK_IDS_FILE,
    "embeddings.npy",
    TERM_CATALOG_FILE,
    ANN_INDEX_BASENAME,
)
_INDEX_DIRS = ("bm25",)


def _sha256_tree(root: Path) -> str:
    """Deterministinen SHA256 kaikista tiedostoista (polku + sisältö)."""
    h = hashlib.sha256()
    for fp in sorted(root.rglob("*")):
        if not fp.is_file():
            continue
        rel = fp.relative_to(root).as_posix().encode("utf-8")
        h.update(rel)
        h.update(b"\0")
        with fp.open("rb") as f:
            while True:
                block = f.read(1024 * 1024)
                if not block:
                    break
                h.update(block)
    return h.hexdigest()


def _copy_index_tree(src: Path, dest: Path) -> list[str]:
    """Kopioi julkaistu indeksi; palauttaa kopioitujen polkujen lista."""
    copied: list[str] = []
    dest.mkdir(parents=True, exist_ok=True)
    for name in _INDEX_ROOT_FILES:
        sp = src / name
        if sp.is_file():
            shutil.copy2(sp, dest / name)
            copied.append(name)
    for dirname in _INDEX_DIRS:
        sd = src / dirname
        if sd.is_dir():
            shutil.copytree(sd, dest / dirname, dirs_exist_ok=True)
            copied.append(f"{dirname}/")
    return copied


def _write_tar_zst(staging: Path, output: Path) -> str:
    """Pakkaa staging-hakemiston .tar.zst (tai .tar.gz ilman zstd)."""
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    zstd = shutil.which("zstd")
    if zstd and str(output).endswith(".zst"):
        tar_path = output.with_suffix(".tar")
        with tarfile.open(tar_path, "w") as tf:
            for item in sorted(staging.iterdir()):
                tf.add(item, arcname=item.name)
        subprocess.run(
            [zstd, "-f", "-q", str(tar_path), "-o", str(output)],
            check=True,
        )
        tar_path.unlink(missing_ok=True)
        return "tar.zst"
    gz_path = (
        output
        if str(output).endswith(".tar.gz")
        else output.with_suffix(".tar.gz")
    )
    with tarfile.open(gz_path, "w:gz") as tf:
        for item in sorted(staging.iterdir()):
            tf.add(item, arcname=item.name)
    return "tar.gz"


def export_linux_index(
    paths: StoragePaths,
    output: Path,
    *,
    version: str,
    databank_id: str = "linux",
) -> dict[str, Any]:
    """
    Pakkaa ``paths.current`` -indeksin cli-botille (vain indexes/ + manifest.json).
    Ei sisällytä sources/, cache/, manifests/.
    """
    idx_dir = published_index_dir(paths)
    meta = load_published_meta(paths)
    if idx_dir is None or not meta:
        return {
            "ok": False,
            "error": "index_not_published",
            "message": "No published index under data dir",
        }

    index_version = meta.get("index_version", "unknown")
    chunk_count = int(meta.get("chunk_ids_count", 0) or 0)
    fingerprint = str(meta.get("source_fingerprint", ""))
    vlabel = f"v{index_version}"

    with tempfile.TemporaryDirectory(prefix="zt-export-") as tmp:
        staging = Path(tmp)
        index_dest = staging / "indexes" / vlabel
        copied_files = _copy_index_tree(idx_dir, index_dest)

        current_link = staging / "indexes" / "current"
        current_link.parent.mkdir(parents=True, exist_ok=True)
        if current_link.exists() or current_link.is_symlink():
            current_link.unlink()
        current_link.symlink_to(vlabel, target_is_directory=True)

        payload_hash = _sha256_tree(staging / "indexes")
        pkg_manifest = {
            "databank_id": databank_id,
            "version": version,
            "index_version": index_version,
            "source_fingerprint": fingerprint,
            "chunk_count": chunk_count,
            "embedding_model": str(meta.get("embedding_model", "")),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "sha256_indexes": payload_hash,
            "zt_data_layout": "indexes/current -> indexes/{version}",
        }
        (staging / "manifest.json").write_text(
            json.dumps(pkg_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        out_requested = output.resolve()
        fmt = _write_tar_zst(staging, out_requested)
        if fmt == "tar.gz":
            out_path = (
                out_requested
                if str(out_requested).endswith(".tar.gz")
                else out_requested.with_suffix(".tar.gz")
            )
        else:
            out_path = out_requested

    archive_sha = hashlib.sha256(out_path.read_bytes()).hexdigest() if out_path.is_file() else ""

    sidecar_path = out_path.with_name(out_path.name + ".package.json")
    sidecar = {
        "databank_id": databank_id,
        "package_version": version,
        "archive_file": out_path.name,
        "format": fmt,
        "sha256_indexes": payload_hash,
        "sha256_archive": archive_sha,
        "source_fingerprint": fingerprint,
        "chunk_count": chunk_count,
    }
    sidecar_path.write_text(
        json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return {
        "ok": True,
        "output": str(out_path),
        "format": fmt,
        "databank_id": databank_id,
        "package_version": version,
        "index_version": index_version,
        "chunk_count": chunk_count,
        "source_fingerprint": fingerprint,
        "sha256_indexes": payload_hash,
        "sha256_archive": archive_sha,
        "copied_files": copied_files,
        "package_sidecar": str(sidecar_path),
    }


def verify_installed_package(
    zt_data_root: Path,
    *,
    package_manifest_path: Path | None = None,
) -> dict[str, Any]:
    """
    Varmista purketun paketin ``manifest.json`` vs. ``indexes/`` (D5).
    ``package_manifest_path``: valinnainen ``*.package.json`` export-sidecar.
    """
    root = zt_data_root.resolve()
    issues: list[str] = []
    pkg_manifest_path = root / "manifest.json"
    if not pkg_manifest_path.is_file():
        return {"ok": False, "error": "missing_manifest", "issues": ["manifest.json"]}

    pkg = json.loads(pkg_manifest_path.read_text(encoding="utf-8"))
    indexes_dir = root / "indexes"
    if not indexes_dir.is_dir():
        issues.append("indexes/")
    else:
        expected = str(pkg.get("sha256_indexes", ""))
        if expected:
            actual = _sha256_tree(indexes_dir)
            if actual != expected:
                issues.append("sha256_indexes mismatch")

    if package_manifest_path and package_manifest_path.is_file():
        sidecar = json.loads(package_manifest_path.read_text(encoding="utf-8"))
        if sidecar.get("source_fingerprint") != pkg.get("source_fingerprint"):
            issues.append("sidecar fingerprint != manifest.json")

    return {
        "ok": not issues,
        "issues": issues,
        "databank_id": pkg.get("databank_id"),
        "version": pkg.get("version"),
    }
