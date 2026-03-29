"""Yksikkötestit: query-fallback-triggerit, termihakemisto, rewrite-apu."""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
import tempfile
from devworkflow.zt_rag.query_rewrite import (
    hyde_enabled,
    parse_subquery_json,
    should_trigger_query_fallback,
    tech_tokens_from_text,
    temporary_env,
)
from devworkflow.zt_rag.term_catalog import (
    TERM_CATALOG_FILE,
    build_term_weights,
    load_term_catalog,
    select_term_hints,
    term_catalog_path_in_index,
    top_terms_as_hints,
    write_term_catalog_jsonl,
)
from devworkflow.zt_rag.source_manifest import Manifest


class TestQueryFallback(unittest.TestCase):
    def test_parse_subquery_json_array(self) -> None:
        raw = '["a", "b"]'
        self.assertEqual(parse_subquery_json(raw), ["a", "b"])

    def test_trigger_empty_context(self) -> None:
        ok, reason = should_trigger_query_fallback(
            [],
            {"rerank_events": [], "pre_rerank_pool_size": 0},
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "empty_context")

    def test_trigger_small_pool(self) -> None:
        rows = [{"chunk_id": "1"}, {"chunk_id": "2"}]
        te = {
            "pre_rerank_pool_size": 5,
            "rerank_events": [{"candidate_count": 5, "skip_reason": "policy_always"}],
        }
        ok, reason = should_trigger_query_fallback(rows, te)
        self.assertTrue(ok)
        self.assertEqual(reason, "small_pre_rerank_pool")

    def test_no_trigger_ok(self) -> None:
        rows = [{"chunk_id": str(i)} for i in range(5)]
        te = {
            "pre_rerank_pool_size": 40,
            "rerank_events": [{"candidate_count": 40, "skip_reason": "policy_always"}],
        }
        ok, reason = should_trigger_query_fallback(rows, te)
        self.assertFalse(ok)
        self.assertEqual(reason, "none")

    def test_trigger_few_context_rows(self) -> None:
        rows = [{"chunk_id": "1"}]
        te = {
            "pre_rerank_pool_size": 40,
            "rerank_events": [{"candidate_count": 40, "skip_reason": "policy_always"}],
        }
        ok, reason = should_trigger_query_fallback(rows, te)
        self.assertTrue(ok)
        self.assertEqual(reason, "few_context_rows")

    def test_trigger_rerank_adaptive_starved(self) -> None:
        rows = [{"chunk_id": str(i)} for i in range(5)]
        te = {
            "pre_rerank_pool_size": 40,
            "rerank_events": [
                {
                    "candidate_count": 40,
                    "skip_reason": "adaptive_below_threshold",
                }
            ],
        }
        ok, reason = should_trigger_query_fallback(rows, te)
        self.assertTrue(ok)
        self.assertEqual(reason, "rerank_adaptive_starved")

    def test_temporary_env_restores(self) -> None:
        key = "ZT_TMP_ENV_FALLBACK_TEST"
        os.environ.pop(key, None)
        with temporary_env({key: "during"}):
            self.assertEqual(os.environ.get(key), "during")
        self.assertNotIn(key, os.environ)

    def test_hyde_enabled_truthy(self) -> None:
        key = "ZT_ENABLE_HYDE"
        prev = os.environ.get(key)
        try:
            os.environ[key] = "true"
            self.assertTrue(hyde_enabled())
            os.environ[key] = "0"
            self.assertFalse(hyde_enabled())
        finally:
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev


class TestTermCatalog(unittest.TestCase):
    def test_tech_tokens(self) -> None:
        t = tech_tokens_from_text("Run `git rebase` with --onto and API_KEY")
        self.assertTrue(any("git" in x.lower() for x in t))

    def test_build_and_select_hints(self) -> None:
        class _Ch:
            def __init__(self) -> None:
                self.title = "Neural Networks"
                self.section = "Backpropagation"
                self.text = "Use gradient descent with learning_rate"
                self.source_id = "s1"

        man = Manifest()
        w = build_term_weights([_Ch()], man)
        self.assertIn("backpropagation", w)
        catalog = sorted(w.items(), key=lambda x: -x[1])
        hints = select_term_hints(
            "backprop gradient in my network",
            catalog,
            max_hints=8,
        )
        self.assertTrue(hints, "expected at least one corpus hint overlap")
        joined = " ".join(h.lower() for h in hints)
        self.assertTrue(
            "backprop" in joined or "neural" in joined,
            joined,
        )

    def test_write_jsonl_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.jsonl"
            n = write_term_catalog_jsonl(p, {"alpha": 1.0, "beta": 2.0})
            self.assertEqual(n, 2)
            lines = p.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            d0 = json.loads(lines[0])
            self.assertIn("term", d0)
            self.assertIn("weight", d0)

    def test_term_catalog_path_safety(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "idx"
            d.mkdir()
            p = d / TERM_CATALOG_FILE
            p.write_text(
                json.dumps({"term": "x", "weight": 1.0}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            meta_ok = {"term_catalog_file": TERM_CATALOG_FILE}
            got = term_catalog_path_in_index(d, meta_ok)
            self.assertEqual(got, p.resolve())
            self.assertIsNone(term_catalog_path_in_index(d, {"term_catalog_file": "../x"}))
            self.assertIsNone(term_catalog_path_in_index(d, {}))

    def test_load_term_catalog_max_lines(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.jsonl"
            with p.open("w", encoding="utf-8") as f:
                for i in range(5):
                    f.write(
                        json.dumps({"term": f"t{i}", "weight": 1.0}, ensure_ascii=False)
                        + "\n"
                    )
            rows = load_term_catalog(p, max_lines=2)
            self.assertEqual(len(rows), 2)

    def test_top_terms_as_hints(self) -> None:
        cat = [("a", 3.0), ("b", 2.0), ("c", 1.0)]
        h = top_terms_as_hints(cat, max_hints=2)
        self.assertEqual(h, ["a", "b"])


if __name__ == "__main__":
    unittest.main()
