"""zt-retrieve JSON stdout -skeema (cli-bot / IndexAdapter)."""
from __future__ import annotations

from typing import Any

SCHEMA_VERSION = 1


def error_payload(
    error: str,
    message: str,
    *,
    question: str = "",
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "error": error,
        "message": message,
    }
    if question:
        out["question"] = question
    return out


def success_payload(
    question: str,
    chunks: list[dict[str, Any]],
    *,
    meta: dict[str, Any],
    telemetry: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "question": question,
        "chunks": chunks,
        "meta": meta,
        "telemetry": telemetry,
    }


def chunk_for_response(row: dict[str, Any]) -> dict[str, Any]:
    """Rajaa chunk-kentät JSON-vastaukseen."""
    score = row.get("score")
    out: dict[str, Any] = {
        "chunk_id": str(row.get("chunk_id", "")),
        "text": str(row.get("text", "")),
        "title": str(row.get("title", "")),
        "section": str(row.get("section", "")),
        "heading_path": str(row.get("heading_path", "")),
        "source_id": str(row.get("source_id", "")),
        "page": row.get("page"),
        "lang": str(row.get("lang", "")),
    }
    if score is not None:
        try:
            out["score"] = float(score)
        except (TypeError, ValueError):
            pass
    return out
