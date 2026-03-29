"""Pankkikohtainen termihakemisto: ingest → julkaisu → kyselyn termivihjeet."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from devworkflow.zt_rag.source_manifest import Manifest, SourceStatus

TERM_CATALOG_FILE = "term_catalog.jsonl"

# Dokumentin/osion otsikot, lyhyet symbolit
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "this", "that", "from", "are", "was", "were", "have",
    "has", "not", "but", "can", "you", "your", "chapter", "section", "page", "figure",
})


def _norm_term(s: str) -> str:
    return " ".join(s.strip().lower().split())


def _add_term(
    weights: dict[str, float],
    term: str,
    w: float,
) -> None:
    t = term.strip()
    if len(t) < 2 or len(t) > 200:
        return
    key = _norm_term(t)
    if not key or key in _STOPWORDS:
        return
    weights[key] = weights.get(key, 0.0) + w


def _title_phrases(title: str) -> list[str]:
    t = title.strip()
    if not t:
        return []
    return [t]


def build_term_weights(
    chunks: list[Any],
    manifest: Manifest,
) -> dict[str, float]:
    """Kerää termit painoineen (otsikot > osiot > tekniset tokenit)."""
    weights: dict[str, float] = {}
    paths_by_sid = {
        sid: Path(ent.path)
        for sid, ent in manifest.sources.items()
        if ent.status in (SourceStatus.ACTIVE, SourceStatus.UPDATED)
    }

    from devworkflow.zt_rag.query_rewrite import tech_tokens_from_text

    for c in chunks:
        for phrase in _title_phrases(c.title):
            _add_term(weights, phrase, 3.0)
        if c.section and str(c.section).strip():
            _add_term(weights, str(c.section).strip(), 2.0)
        p = paths_by_sid.get(c.source_id)
        if p is not None:
            _add_term(weights, p.stem.replace("_", " "), 1.0)
            if p.suffix:
                _add_term(weights, p.stem, 0.5)
        for tok in tech_tokens_from_text(c.text[:8000]):
            _add_term(weights, tok, 0.35)

    return weights


def write_term_catalog_jsonl(
    path: Path,
    weights: dict[str, float],
    *,
    max_entries: int = 50_000,
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    ranked = sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for term, w in ranked[:max_entries]:
            line = json.dumps({"term": term, "weight": round(w, 4)}, ensure_ascii=False)
            f.write(line + "\n")
            n += 1
    return n


def load_term_catalog(
    path: Path,
    *,
    max_lines: int | None = None,
    max_line_bytes: int = 65_536,
) -> list[tuple[str, float]]:
    """
    Lue termilista. Oletus katkoo pahimman muistikuorman (``ZT_TERM_CATALOG_MAX_LINES``).
    """
    out: list[tuple[str, float]] = []
    if not path.is_file():
        return out
    cap = max_lines
    if cap is None:
        cap = 100_000
        raw = os.environ.get("ZT_TERM_CATALOG_MAX_LINES", "").strip()
        if raw:
            try:
                cap = max(1, int(raw))
            except ValueError:
                pass
    n_read = 0
    max_raw_scans = max(cap * 20, 50_000)
    scans = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            if n_read >= cap:
                break
            if scans >= max_raw_scans:
                break
            scans += 1
            line = line.strip()
            if len(line) > max_line_bytes:
                continue
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = str(d.get("term", "")).strip()
            if not t:
                continue
            try:
                w = float(d.get("weight", 1.0))
            except (TypeError, ValueError):
                w = 1.0
            out.append((t, w))
            n_read += 1
    return out


def term_catalog_path_in_index(index_dir: Path, meta: dict[str, Any]) -> Path | None:
    raw = meta.get("term_catalog_file")
    if not raw:
        return None
    cf = str(raw).strip()
    if not cf or "/" in cf or "\\" in cf or ".." in cf:
        return None
    p = (index_dir.resolve() / cf)
    return p if p.is_file() else None


_WORD_SPLIT = re.compile(r"[^\w+./:-]+", re.UNICODE)


def select_term_hints(
    question: str,
    catalog: list[tuple[str, float]],
    *,
    max_hints: int,
) -> list[str]:
    """Yksinkertainen päällekkäisyyspisteytys: kysymyksen tokenit vs. hakemiston termit."""
    if not question.strip() or not catalog or max_hints <= 0:
        return []

    q_tokens = {t.lower() for t in _WORD_SPLIT.split(question) if len(t) > 1}
    if not q_tokens:
        return []

    scored: list[tuple[float, str]] = []
    for term, weight in catalog:
        tl = term.lower()
        parts = {p for p in _WORD_SPLIT.split(tl) if len(p) > 1}
        overlap = len(q_tokens & parts)
        if overlap == 0:
            # osa-osumia: jokin kyselyn token on tekstin substring
            for qt in q_tokens:
                if qt in tl or tl in qt:
                    overlap = max(overlap, 1)
                    break
        if overlap == 0:
            continue
        score = overlap * 1.0 + min(weight, 10.0) * 0.15
        scored.append((score, term))

    scored.sort(key=lambda x: (-x[0], x[1]))
    seen: set[str] = set()
    out: list[str] = []
    for _, term in scored:
        k = term.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(term)
        if len(out) >= max_hints:
            break
    return out


def top_terms_as_hints(
    catalog: list[tuple[str, float]],
    *,
    max_hints: int,
) -> list[str]:
    """Kun kyselyssä ei ole osumia, palauta painotetuimmat termit (vikalähtöinen vihje)."""
    out: list[str] = []
    for term, _w in catalog[:max_hints]:
        if term not in out:
            out.append(term)
        if len(out) >= max_hints:
            break
    return out
