"""export_linux_index — pakkaus ilman täyttä BM25/ST-pinoa."""
from __future__ import annotations

import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from devworkflow.zt_rag.export_linux_index import export_linux_index
from devworkflow.zt_rag.index_publish import CHUNK_IDS_FILE
from devworkflow.zt_rag.storage_layout import StoragePaths


def _minimal_published_index(root: Path) -> None:
    vdir = root / "indexes" / "v1"
    vdir.mkdir(parents=True)
    meta = {
        "index_version": 1,
        "source_fingerprint": "fp_test_abc",
        "chunk_ids_count": 1,
        "embedding_model": "test-model",
    }
    (vdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (vdir / "chunks.jsonl").write_text(
        json.dumps(
            {
                "chunk_id": "c1",
                "text": "dnf install",
                "title": "Guide",
                "section": "pkg",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (vdir / CHUNK_IDS_FILE).write_text("c1\n", encoding="utf-8")
    cur = root / "indexes" / "current"
    if cur.exists() or cur.is_symlink():
        cur.unlink()
    cur.symlink_to("v1", target_is_directory=True)


class TestExportLinuxIndex(unittest.TestCase):
    def test_export_creates_archive_with_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            _minimal_published_index(data)
            out_archive = Path(tmp) / "bundle.tar.zst"
            paths = StoragePaths.create(root=data)
            result = export_linux_index(
                paths,
                out_archive,
                version="0.1.0-dev",
                databank_id="linux",
            )
            self.assertTrue(result.get("ok"), result)
            archive_path = Path(result["output"])
            self.assertTrue(archive_path.is_file())
            self.assertEqual(result.get("chunk_count"), 1)

            extract = Path(tmp) / "extracted"
            extract.mkdir()
            import shutil
            import subprocess

            if result.get("format") == "tar.zst":
                if not shutil.which("zstd"):
                    self.skipTest("zstd not installed")
                tar_path = archive_path.with_suffix(".tar")
                subprocess.run(
                    ["zstd", "-d", "-q", str(archive_path), "-o", str(tar_path)],
                    check=True,
                )
                with tarfile.open(tar_path, "r") as tf:
                    tf.extractall(extract, filter="data")
            else:
                with tarfile.open(archive_path, "r:*") as tf:
                    tf.extractall(extract, filter="data")

            manifest = json.loads(
                (extract / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["databank_id"], "linux")
            self.assertEqual(manifest["version"], "0.1.0-dev")
            self.assertEqual(manifest["source_fingerprint"], "fp_test_abc")
            self.assertTrue((extract / "indexes" / "current").exists())
            sidecar_path = Path(result.get("package_sidecar", ""))
            if sidecar_path.is_file():
                sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
                self.assertEqual(sidecar.get("sha256_indexes"), manifest.get("sha256_indexes"))


if __name__ == "__main__":
    unittest.main()
