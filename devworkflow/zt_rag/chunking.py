"""Kappaletietoinen chunkkaus: katkaisee heading- ja paragraph-rajoilla."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ChunkConfig:
    max_chars: int = 2000
    overlap_chars: int = 200


_HEADING_RE = re.compile(r"(?=^#{1,4}\s)", re.MULTILINE)
_PARA_RE = re.compile(r"\n{2,}")


def _split_on_boundaries(text: str) -> list[str]:
    """Pilko teksti heading- ja kappaletasoille."""
    heading_parts = _HEADING_RE.split(text)
    segments: list[str] = []
    for hp in heading_parts:
        paras = _PARA_RE.split(hp)
        for p in paras:
            stripped = p.strip()
            if stripped:
                segments.append(stripped)
    return segments


def chunk_text(
    text: str,
    cfg: ChunkConfig | None = None,
) -> list[str]:
    cfg = cfg or ChunkConfig()
    t = text.strip()
    if not t:
        return []

    segments = _split_on_boundaries(t)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for seg in segments:
        seg_len = len(seg)
        if seg_len > cfg.max_chars:
            if current:
                chunks.append("\n\n".join(current))
                current, current_len = [], 0
            chunks.extend(_hard_split(seg, cfg))
            continue

        if current_len + seg_len + 2 > cfg.max_chars and current:
            chunks.append("\n\n".join(current))
            overlap_text = _build_overlap(current, cfg.overlap_chars)
            current = [overlap_text] if overlap_text else []
            current_len = len(overlap_text) if overlap_text else 0

        current.append(seg)
        current_len += seg_len + 2

    if current:
        joined = "\n\n".join(current).strip()
        if joined:
            chunks.append(joined)

    return chunks


def _build_overlap(parts: list[str], overlap_chars: int) -> str:
    """Ota edellisen chunkin lopusta overlap_chars merkkiä kokonaisina segmentteinä."""
    if not parts or overlap_chars <= 0:
        return ""
    tail: list[str] = []
    total = 0
    for seg in reversed(parts):
        if total + len(seg) > overlap_chars and tail:
            break
        tail.append(seg)
        total += len(seg) + 2
    tail.reverse()
    return "\n\n".join(tail)


def _hard_split(text: str, cfg: ChunkConfig) -> list[str]:
    """Fallback: liian pitkä segmentti → merkkimääräinen jako lauserajoilla."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0
    for s in sentences:
        if buf_len + len(s) + 1 > cfg.max_chars and buf:
            chunks.append(" ".join(buf))
            overlap_text = " ".join(buf)[-cfg.overlap_chars:]
            buf = [overlap_text] if overlap_text.strip() else []
            buf_len = len(buf[0]) if buf else 0
        buf.append(s)
        buf_len += len(s) + 1
    if buf:
        joined = " ".join(buf).strip()
        if joined:
            chunks.append(joined)
    return chunks
