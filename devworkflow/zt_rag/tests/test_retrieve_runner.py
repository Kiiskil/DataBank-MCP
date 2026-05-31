"""Retrieve-only polku ja index_guard."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from devworkflow.zt_rag.index_guard import (
    check_manifest_fingerprint,
    manifest_has_active_sources,
)
from devworkflow.zt_rag.retrieve_runner import run_retrieve
from devworkflow.zt_rag.retrieve_schema import chunk_for_response, error_payload
from devworkflow.zt_rag.storage_layout import StoragePaths


class TestRetrieveSchema(unittest.TestCase):
    def test_error_payload(self) -> None:
        out = error_payload("empty_question", "Question must not be empty")
        self.assertEqual(out["schema_version"], 1)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "empty_question")

    def test_chunk_for_response_score(self) -> None:
        ch = chunk_for_response(
            {
                "chunk_id": "id1",
                "text": "body",
                "title": "T",
                "section": "S",
                "heading_path": "A > B",
                "source_id": "sid",
                "page": 1,
                "lang": "fi",
                "score": 0.5,
            }
        )
        self.assertEqual(ch["score"], 0.5)
        self.assertEqual(ch["heading_path"], "A > B")


class TestIndexGuard(unittest.TestCase):
    def test_no_manifest_skips_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = StoragePaths.create(root=Path(tmp))
            paths.ensure()
            self.assertFalse(manifest_has_active_sources(paths))
            fp = check_manifest_fingerprint(paths)
            self.assertFalse(fp.ok)
            self.assertEqual(fp.error, "index_not_published")


class TestRunRetrieve(unittest.TestCase):
    def test_empty_question(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = StoragePaths.create(root=Path(tmp))
            paths.ensure()
            out = run_retrieve(paths, "   ")
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "empty_question")

    @patch("devworkflow.zt_rag.retrieve_runner.load_context_blocks")
    @patch("devworkflow.zt_rag.retrieve_runner.check_manifest_fingerprint")
    @patch("devworkflow.zt_rag.retrieve_runner.check_published_index")
    def test_success_shape(
        self,
        mock_pub: MagicMock,
        mock_fp: MagicMock,
        mock_load: MagicMock,
    ) -> None:
        from devworkflow.zt_rag.index_guard import FingerprintCheck, PublishedIndexCheck

        mock_idx = MagicMock()
        mock_pub.return_value = PublishedIndexCheck(
            ok=True,
            index=mock_idx,
            meta={
                "index_version": 2,
                "embedding_model": "test-model",
                "source_fingerprint": "fp1",
            },
        )
        mock_fp.return_value = FingerprintCheck(ok=True, skipped=True)
        mock_load.return_value = (
            [
                {
                    "chunk_id": "c1",
                    "text": "dnf install foo",
                    "title": "Guide",
                    "section": "Packages",
                    "heading_path": "Packages",
                    "source_id": "s1",
                    "page": None,
                    "lang": "en",
                    "score": 0.9,
                }
            ],
            mock_idx,
        )

        with tempfile.TemporaryDirectory() as tmp:
            paths = StoragePaths.create(root=Path(tmp))
            out = run_retrieve(paths, "dnf install", top_n=3)

        self.assertTrue(out["ok"])
        self.assertEqual(out["schema_version"], 1)
        self.assertEqual(len(out["chunks"]), 1)
        self.assertEqual(out["chunks"][0]["score"], 0.9)
        self.assertEqual(out["telemetry"]["query_policy"], "fast")
        mock_load.assert_called_once()
        self.assertTrue(
            mock_load.call_args.kwargs.get("attach_rerank_scores")
        )


if __name__ == "__main__":
    unittest.main()
