"""
Eval-ajuri: golden-set + queries.jsonl → recall@k ja keskimääräiset vaiheajat.

Käyttö:
  PYTHONPATH=. python -m devworkflow.zt_rag.eval_runner --golden kysymykset.jsonl --query-log /data/logs/queries.jsonl
  PYTHONPATH=. python -m devworkflow.zt_rag.eval_runner --query-log queries.jsonl  # vain tilastot
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _norm_question(q: str) -> str:
    return " ".join(q.strip().lower().split())


def recall_at_k(retrieved: list[str], gold: set[str], k: int) -> float:
    if not gold:
        return 1.0
    topk = set(retrieved[:k])
    return len(topk & gold) / len(gold)


def _timing_keys() -> list[str]:
    return [
        "decompose",
        "hyde",
        "retrieval",
        "context_build",
        "llm_answer",
        "verify",
        "total",
    ]


def aggregate_timing_ms(rows: list[dict[str, Any]]) -> dict[str, Any]:
    keys = _timing_keys()
    samples: dict[str, list[int]] = {k: [] for k in keys}
    for r in rows:
        t = (r.get("telemetry") or {}).get("timing_ms") or {}
        if not isinstance(t, dict):
            continue
        for k in keys:
            v = t.get(k)
            if isinstance(v, (int, float)):
                samples[k].append(int(v))
    out: dict[str, Any] = {}
    for k, vals in samples.items():
        if not vals:
            out[k] = None
            continue
        out[k] = {
            "mean": statistics.mean(vals),
            "median": statistics.median(vals),
            "n": len(vals),
        }
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="ZT-RAG eval-runner (golden + query-loki)")
    p.add_argument(
        "--golden",
        type=Path,
        help='JSONL: {"question": "...", "gold_chunk_ids": ["..."]}',
    )
    p.add_argument(
        "--query-log",
        type=Path,
        help="queries.jsonl (run_query lokittaa telemetryn)",
    )
    p.add_argument(
        "--k",
        type=int,
        default=10,
        help="recall@k (oletus 10)",
    )
    args = p.parse_args()

    out: dict[str, Any] = {
        "metrics_computed_from_query_log": [
            "verification_ok_rate",
            "no_retrieval_count",
            "no_retrieval_rate",
            "fallback_chosen_count",
            "fallback_chosen_rate",
            "timing_ms",
        ],
        "note": (
            "recall@k: --golden + --query-log ja ei-tyhjät gold_chunk_ids; timing_ms query-logista. "
            "citation_precision / refusal_precision / coverage / groundedness_failure_rate eivät "
            "ole tässä ajurissa toteutettu."
        ),
    }

    if args.query_log and args.query_log.exists():
        qrows = _load_jsonl(args.query_log)
        out["query_log_rows"] = len(qrows)
        out["verification_ok_rate"] = (
            sum(1 for r in qrows if r.get("verification_ok")) / len(qrows)
            if qrows
            else None
        )
        out["no_retrieval_count"] = sum(
            1 for r in qrows if r.get("result") == "no_retrieval"
        )
        out["no_retrieval_rate"] = (
            out["no_retrieval_count"] / len(qrows) if qrows else None
        )
        out["fallback_chosen_count"] = sum(
            1
            for r in qrows
            if (r.get("telemetry") or {}).get("retrieval_chosen_attempt")
            == "fallback"
        )
        out["fallback_chosen_rate"] = (
            out["fallback_chosen_count"] / len(qrows) if qrows else None
        )
        out["timing_ms"] = aggregate_timing_ms(qrows)

    if args.golden and args.golden.exists() and args.query_log and args.query_log.exists():
        gold_rows = _load_jsonl(args.golden)
        log_rows = _load_jsonl(args.query_log)
        gold_map: dict[str, dict[str, Any]] = {}
        for r in gold_rows:
            q = r.get("question")
            if isinstance(q, str) and q.strip():
                gold_map[_norm_question(q)] = r

        recalls: list[float] = []
        matched = 0
        for lr in log_rows:
            q = lr.get("question")
            if not isinstance(q, str) or not q.strip():
                continue
            gr = gold_map.get(_norm_question(q))
            if not gr:
                continue
            matched += 1
            gids = gr.get("gold_chunk_ids")
            if not isinstance(gids, list):
                continue
            gold_set = {str(x) for x in gids if x}
            if not gold_set:
                continue
            rids = lr.get("retrieval_chunk_ids") or []
            if not isinstance(rids, list):
                rids = []
            retrieved = [str(x) for x in rids if x]
            recalls.append(recall_at_k(retrieved, gold_set, max(1, args.k)))

        out["golden_eval"] = {
            "k": max(1, args.k),
            "matched_queries": matched,
            "mean_recall_at_k": statistics.mean(recalls) if recalls else None,
            "median_recall_at_k": statistics.median(recalls) if recalls else None,
            "evaluated_pairs": len(recalls),
        }
        ge = out.get("golden_eval") or {}
        if isinstance(ge, dict):
            out["metrics_computed_from_query_log"] = list(
                out["metrics_computed_from_query_log"]
            ) + [
                "golden_eval.mean_recall_at_k",
                "golden_eval.median_recall_at_k",
                "golden_eval.evaluated_pairs",
            ]

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
