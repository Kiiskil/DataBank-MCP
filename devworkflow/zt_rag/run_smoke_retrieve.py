#!/usr/bin/env python3
"""
Ajaa retrieve-smoke-kysymyslistan julkaistua indeksiä vasten.

  export ZT_DATA_DIR=/data/zt-rag-linux
  python -m devworkflow.zt_rag.run_smoke_retrieve

CI: mock-testit ajetaan unittestissa; tämä skripti on manuaalinen / integraatio.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from devworkflow.zt_rag.retrieve_runner import run_retrieve
from devworkflow.zt_rag.storage_layout import StoragePaths

_QUESTIONS_FILE = Path(__file__).resolve().parent / "smoke_retrieve_questions.txt"


def load_smoke_questions(path: Path | None = None) -> list[str]:
    p = path or _QUESTIONS_FILE
    lines: list[str] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def run_smoke_retrieve(
    paths: StoragePaths,
    *,
    questions_path: Path | None = None,
    top_n: int = 3,
    require_chunks: bool = False,
) -> dict:
    questions = load_smoke_questions(questions_path)
    results: list[dict] = []
    failures = 0
    empty = 0

    for q in questions:
        out = run_retrieve(paths, q, top_n=top_n)
        row = {
            "question": q,
            "ok": out.get("ok"),
            "error": out.get("error"),
            "chunk_count": len(out.get("chunks") or []) if out.get("ok") else 0,
            "pre_rerank_pool_size": (
                (out.get("telemetry") or {}).get("pre_rerank_pool_size")
                if out.get("ok")
                else None
            ),
        }
        results.append(row)
        if not out.get("ok"):
            failures += 1
        elif not out.get("chunks"):
            empty += 1
            if require_chunks:
                failures += 1

    return {
        "ok": failures == 0,
        "questions": len(questions),
        "failures": failures,
        "empty_results": empty,
        "results": results,
    }


def main() -> None:
    root = Path(os.environ.get("ZT_DATA_DIR", "/data")).resolve()
    paths = StoragePaths.create(root=root)
    os.environ.setdefault("ZT_QUERY_POLICY", "fast")
    require = os.environ.get("ZT_SMOKE_REQUIRE_CHUNKS", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    report = run_smoke_retrieve(paths, require_chunks=require)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if report.get("ok") else 1)


if __name__ == "__main__":
    main()
