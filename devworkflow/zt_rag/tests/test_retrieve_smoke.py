"""Retrieve-smoke (mock CI) ja paketin checksum."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from devworkflow.zt_rag.export_linux_index import verify_installed_package
from devworkflow.zt_rag.run_smoke_retrieve import load_smoke_questions, run_smoke_retrieve
from devworkflow.zt_rag.storage_layout import StoragePaths


class TestSmokeQuestions(unittest.TestCase):
    def test_load_questions_count(self) -> None:
        qs = load_smoke_questions()
        self.assertGreaterEqual(len(qs), 10)
        self.assertIn("dnf install", qs[0].lower())


class TestRunSmokeRetrieveMocked(unittest.TestCase):
    @patch("devworkflow.zt_rag.run_smoke_retrieve.run_retrieve")
    def test_all_questions_ok_with_chunks(self, mock_rr: MagicMock) -> None:
        mock_rr.return_value = {
            "ok": True,
            "chunks": [{"chunk_id": "1", "text": "x"}],
            "telemetry": {"pre_rerank_pool_size": 5},
        }
        with tempfile.TemporaryDirectory() as tmp:
            paths = StoragePaths.create(root=Path(tmp))
            report = run_smoke_retrieve(paths, top_n=2, require_chunks=True)
        self.assertTrue(report["ok"])
        self.assertEqual(report["failures"], 0)
        self.assertEqual(mock_rr.call_count, len(load_smoke_questions()))

    @patch("devworkflow.zt_rag.run_smoke_retrieve.run_retrieve")
    def test_failure_when_index_missing(self, mock_rr: MagicMock) -> None:
        mock_rr.return_value = {
            "ok": False,
            "error": "index_not_published",
        }
        with tempfile.TemporaryDirectory() as tmp:
            paths = StoragePaths.create(root=Path(tmp))
            report = run_smoke_retrieve(paths, top_n=2)
        self.assertFalse(report["ok"])
        self.assertGreater(report["failures"], 0)


class TestVerifyPackage(unittest.TestCase):
    def test_verify_indexes_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            indexes = root / "indexes" / "v1"
            indexes.mkdir(parents=True)
            (indexes / "meta.json").write_text("{}", encoding="utf-8")
            from devworkflow.zt_rag.export_linux_index import _sha256_tree

            h = _sha256_tree(root / "indexes")
            (root / "manifest.json").write_text(
                json.dumps({"sha256_indexes": h, "databank_id": "linux"}),
                encoding="utf-8",
            )
            out = verify_installed_package(root)
            self.assertTrue(out["ok"], out.get("issues"))


if __name__ == "__main__":
    unittest.main()
