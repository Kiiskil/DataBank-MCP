"""Pickleable-tason parse-workerit (ProcessPoolExecutor / spawn-yhteensopiva)."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def parse_source_file(path_str: str, ft: str) -> dict[str, Any]:
    """
    Palauttaa dictin josta ingest rakentaa ParsedDocumentin.
    Virheet: ok=False, error=viesti.
    """
    from devworkflow.zt_rag.parsers import parse_epub, parse_markdown, parse_pdf

    try:
        p = Path(path_str)
        if ft == "epub":
            doc = parse_epub(p)
            return {
                "ok": True,
                "error": None,
                "title": doc.title,
                "sections": doc.sections,
                "quality": {},
            }
        if ft == "md":
            doc = parse_markdown(p)
            return {
                "ok": True,
                "error": None,
                "title": doc.title,
                "sections": doc.sections,
                "quality": {},
            }
        doc, quality = parse_pdf(p)
        return {
            "ok": True,
            "error": None,
            "title": doc.title,
            "sections": doc.sections,
            "quality": quality,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "title": "",
            "sections": [],
            "quality": {},
        }
