"""Lähteet -> chunkit + metatiedot."""
from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from devworkflow.zt_rag.chunking import ChunkConfig, chunk_text
from devworkflow.zt_rag.ingest_parse_worker import parse_source_file
from devworkflow.zt_rag.parsers import ParsedDocument, detect_type
from devworkflow.zt_rag.source_manifest import Manifest, SourceStatus
from devworkflow.zt_rag.storage_layout import StoragePaths
from devworkflow.zt_rag.versioning import content_hash, file_sha256, normalize_for_match


@dataclass
class ChunkRecord:
    chunk_id: str
    source_id: str
    source_hash: str
    chunk_hash: str
    title: str
    section: str
    page: int | None
    chunk_index: int
    char_start: int
    char_end: int
    text: str

    def to_json_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_source_tuple(task: tuple[str, str]) -> dict[str, Any]:
    """ProcessPoolExecutor.map vaatii yhden argumentin; ei starmap."""
    path_str, ft = task
    return parse_source_file(path_str, ft)


def _ingest_parse_workers(pending_n: int) -> int:
    raw = os.environ.get("ZT_INGEST_PARSE_WORKERS", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return min(4, max(1, pending_n))


def ingest_active_sources(
    paths: StoragePaths,
    manifest: Manifest,
    force_rebuild: bool = False,
) -> tuple[list[ChunkRecord], dict[str, Any]]:
    """
    Lukee kaikki ACTIVE-lähteet, tuottaa chunkit.
    Palauttaa (chunkit, raportti).
    """
    paths.ensure()
    records: list[ChunkRecord] = []
    report: dict[str, Any] = {"sources": {}, "errors": []}
    pending: list[tuple[str, Any, Path, str, str]] = []

    for sid, ent in list(manifest.sources.items()):
        if ent.status not in (SourceStatus.ACTIVE, SourceStatus.UPDATED):
            continue
        p = Path(ent.path)
        if not p.exists():
            ent.ingest_status = "missing_file"
            ent.error_code = "ENOENT"
            report["errors"].append({"source_id": sid, "error": "file_missing"})
            continue

        ft = detect_type(p)
        if ft == "unknown":
            ent.ingest_status = "unsupported"
            ent.error_code = "UNSUPPORTED_TYPE"
            ent.status = SourceStatus.FAILED
            report["errors"].append({"source_id": sid, "error": "unsupported_type"})
            continue

        try:
            sh = file_sha256(p)
            ent.source_hash = sh
        except OSError as e:
            ent.ingest_status = "read_error"
            ent.error_code = str(e)
            ent.status = SourceStatus.FAILED
            report["errors"].append({"source_id": sid, "error": str(e)})
            continue

        if (
            not force_rebuild
            and ent.indexed_source_hash == sh
            and ent.chunk_count > 0
        ):
            cache_file = paths.cache / sid / f"{sh}.jsonl"
            if cache_file.exists():
                with cache_file.open(encoding="utf-8") as cf:
                    for line in cf:
                        if line.strip():
                            records.append(ChunkRecord(**json.loads(line)))
                report["sources"][sid] = {"skipped_parse": True, "hash": sh}
                continue

        pending.append((sid, ent, p, ft, sh))

    if pending:
        tasks = [(str(p.resolve()), ft) for sid, ent, p, ft, sh in pending]
        workers = _ingest_parse_workers(len(pending))
        if workers <= 1:
            parsed_results = [parse_source_file(a, b) for a, b in tasks]
        else:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                parsed_results = list(ex.map(_parse_source_tuple, tasks))

        for (sid, ent, p, ft, sh), res in zip(pending, parsed_results, strict=True):
            if not res.get("ok"):
                ent.ingest_status = "parse_error"
                ent.error_code = str(res.get("error") or "parse_failed")
                ent.status = SourceStatus.FAILED
                report["errors"].append(
                    {"source_id": sid, "error": str(res.get("error"))}
                )
                continue

            quality: dict[str, Any] = dict(res.get("quality") or {})
            if ft == "pdf" and quality.get("suggest_quarantine"):
                ent.status = SourceStatus.QUARANTINED
                ent.parser_state = "low_text_density"
                ent.ingest_status = "quarantined"
                report["sources"][sid] = {"quarantined": True, "quality": quality}
                continue

            ent.parser_state = "ok"
            ent.ingest_status = "parsed"
            doc = ParsedDocument(
                title=str(res.get("title") or ""),
                sections=list(res.get("sections") or []),
            )
            cfg = ChunkConfig()
            char_cursor = 0
            sid_records: list[ChunkRecord] = []
            chunk_idx = 0
            for sec in doc.sections:
                heading = str(sec.get("heading", "")).strip()
                page = sec.get("page")
                page_i = page if isinstance(page, int) else None
                txt = str(sec.get("text", ""))
                if not txt.strip():
                    continue
                section_blob = f"## {heading}\n{txt}" if heading else txt
                section_label = heading if heading else "body"
                raw_chunks = chunk_text(section_blob, cfg)
                for ch in raw_chunks:
                    norm = normalize_for_match(ch)
                    chash = content_hash(norm)
                    cid = str(uuid.uuid4())
                    rec = ChunkRecord(
                        chunk_id=cid,
                        source_id=sid,
                        source_hash=sh,
                        chunk_hash=chash,
                        title=doc.title,
                        section=section_label,
                        page=page_i,
                        chunk_index=chunk_idx,
                        char_start=char_cursor,
                        char_end=char_cursor + len(ch),
                        text=ch,
                    )
                    char_cursor += len(ch) + 2
                    chunk_idx += 1
                    sid_records.append(rec)
                    records.append(rec)

            cache_dir = paths.cache / sid
            cache_dir.mkdir(parents=True, exist_ok=True)
            cf = cache_dir / f"{sh}.jsonl"
            cf.write_text(
                "\n".join(json.dumps(r.to_json_dict(), ensure_ascii=False) for r in sid_records)
                + "\n",
                encoding="utf-8",
            )

            ent.chunk_count = len(sid_records)
            ent.indexed_source_hash = sh
            ent.indexed_at = _now_iso()
            report["sources"][sid] = {
                "chunks": len(sid_records),
                "hash": sh,
                "quality": quality,
            }

    return records, report
