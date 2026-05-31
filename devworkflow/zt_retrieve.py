#!/usr/bin/env python3
"""
zt-retrieve — retrieve-only JSON stdout (cli-bot).

Kehitys:
  python -m devworkflow.zt_retrieve -q "dnf install" -n 5 --json

Vaatii ZT_DATA_DIR ja julkaistun indeksin. Ei vaadi ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_pkg_root = Path(__file__).resolve().parent.parent
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))


def main() -> None:
    p = argparse.ArgumentParser(
        prog="zt-retrieve",
        description="ZT-RAG retrieve-only (ei LLM:ää)",
    )
    p.add_argument("-q", "--question", required=True, help="Hakumerkkijono")
    p.add_argument("-n", "--top-n", type=int, default=5, help="Chunkkien määrä")
    p.add_argument(
        "--json",
        action="store_true",
        default=True,
        help="JSON stdout (oletus päällä)",
    )
    p.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="ZT_DATA_DIR (oletus ympäristöstä)",
    )
    args = p.parse_args()

    os.environ.setdefault("ZT_QUERY_POLICY", "fast")

    from devworkflow.zt_rag.retrieve_runner import run_retrieve
    from devworkflow.zt_rag.storage_layout import StoragePaths

    root = (args.data_dir or Path(os.environ.get("ZT_DATA_DIR", "/data"))).resolve()
    paths = StoragePaths.create(root=root)
    out = run_retrieve(paths, args.question, top_n=max(1, args.top_n))

    print(json.dumps(out, ensure_ascii=False))

    if not out.get("ok"):
        err = str(out.get("error", ""))
        sys.exit(2 if err == "empty_question" else 1)


if __name__ == "__main__":
    main()
