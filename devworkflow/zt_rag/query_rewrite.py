"""
Kyselyn esikäsittely: käännös, dekomposiointi, HyDE ja fallback-query-rewrite.
"""
from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from typing import Any

import anthropic

from devworkflow.zt_rag.query_hard_profile import QUERY_HARD_PROFILE_ENV

_TRANSLATE_PROMPT = (
    "Translate the following question to English for use as a search query against an English-language corpus. "
    "Return ONLY the translated question, nothing else. If the question is already in English, return it unchanged."
)

_DECOMPOSE_SYSTEM = (
    "You prepare short search queries for RAG retrieval over an English-language document corpus.\n"
    "Return ONLY a JSON array of 2 to 4 strings. Each string is one concise English search query "
    "capturing a distinct angle, entity, or keyword facet of the user's question.\n"
    "If the user message is not in English, translate the intent into English sub-queries.\n"
    "Do not wrap the array in an object. Do not use markdown fences. Example:\n"
    '["fine-tuning large language models", "retrieval augmented generation RAG definition"]'
)

_HYDE_PROMPT = (
    "Given the following question, write a short (2-3 sentence) hypothetical passage "
    "that would answer it, as if it appeared in a textbook. "
    "Return ONLY the passage text, nothing else."
)

_FALLBACK_DECOMPOSE_SYSTEM = (
    "The user's question may use vague or non-technical wording that does not match the corpus vocabulary.\n"
    "Prepare 3 to 5 short English search queries for RAG retrieval.\n"
    "Each query must add concrete technical keywords, standard library/framework names, "
    "CLI flags, protocols, or synonyms likely to appear in English technical documentation.\n"
    "Keep the user's intent; do not invent unrelated topics.\n"
    "Return ONLY a JSON array of strings. No markdown fences.\n"
    'Example: ["vim write quit command :wq", "vi exit save"]'
)

_CORPUS_AWARE_FALLBACK_SYSTEM = (
    "The user's question may not use the same words as the indexed corpus.\n"
    "Below are HIGH-CONFIDENCE terms/phrases extracted from the actual corpus (titles, headings, symbols).\n"
    "Prepare 3 to 5 short English search queries for RAG retrieval.\n"
    "Each query should incorporate relevant corpus terms where they fit the user's intent.\n"
    "Do not force irrelevant terms. Do not output explanations.\n"
    "Return ONLY a JSON array of strings. No markdown fences."
)


def env_flag_enabled(name: str) -> bool:
    """Totuusluku: 1, true, yes, on (case-insensitive)."""
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def hyde_enabled() -> bool:
    return env_flag_enabled("ZT_ENABLE_HYDE")


def corpus_aware_rewrite_enabled() -> bool:
    return env_flag_enabled("ZT_ENABLE_CORPUS_AWARE_REWRITE")


def query_policy() -> str:
    return os.environ.get("ZT_QUERY_POLICY", "standard").strip().lower()


def skip_query_decompose() -> bool:
    """Kevyt polku: ei Anthropic-dekomponointia (yksi hakukysely)."""
    if query_policy() in ("fast", "single", "quick"):
        return True
    raw = os.environ.get("ZT_SKIP_QUERY_DECOMPOSE", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _detect_non_english(text: str) -> bool:
    ascii_letters = sum(1 for c in text if c.isascii() and c.isalpha())
    all_letters = sum(1 for c in text if c.isalpha())
    if all_letters == 0:
        return False
    return (ascii_letters / all_letters) < 0.85


def translate_query_for_retrieval(question: str, model: str | None) -> str:
    if not _detect_non_english(question):
        return question
    m = model or os.environ.get("ZT_QUERY_MODEL", "claude-sonnet-4-6")
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=m,
            max_tokens=256,
            system=_TRANSLATE_PROMPT,
            messages=[{"role": "user", "content": question}],
        )
        translated = resp.content[0].text.strip()
        return translated if translated else question
    except Exception:
        return question


def parse_subquery_json(raw: str) -> list[str]:
    clean = raw.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        clean = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    clean = clean.strip()
    try:
        data = json.loads(clean)
    except json.JSONDecodeError:
        start = clean.find("[")
        end = clean.rfind("]")
        if start == -1 or end <= start:
            return []
        try:
            data = json.loads(clean[start : end + 1])
        except json.JSONDecodeError:
            return []
    if isinstance(data, list):
        return [str(x).strip() for x in data if str(x).strip()][:6]
    if isinstance(data, dict):
        for key in ("queries", "search_queries", "subqueries"):
            inner = data.get(key)
            if isinstance(inner, list):
                return [str(x).strip() for x in inner if str(x).strip()][:6]
    return []


def decompose_search_queries(question: str, model: str | None) -> tuple[list[str], str]:
    """Yksi Anthropic-kutsu: englanninkieliset alakyselyt + teksti rerankkerille."""
    m = model or os.environ.get("ZT_QUERY_MODEL", "claude-sonnet-4-6")
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=m,
            max_tokens=512,
            system=_DECOMPOSE_SYSTEM,
            messages=[{"role": "user", "content": question}],
        )
        raw = resp.content[0].text.strip()
        sub = parse_subquery_json(raw)
        if not sub:
            single = translate_query_for_retrieval(question, model)
            sq = single.strip() or question.strip()
            return [sq], sq
        seen: set[str] = set()
        uniq: list[str] = []
        for s in sub:
            k = s.lower()
            if k in seen:
                continue
            seen.add(k)
            uniq.append(s)
        rerank_text = " ".join(uniq[:4])
        return uniq[:4], rerank_text
    except Exception:
        single = translate_query_for_retrieval(question, model)
        sq = single.strip() or question.strip()
        return [sq], sq


def hyde_expand(query: str, model: str | None) -> str:
    m = model or os.environ.get("ZT_QUERY_MODEL", "claude-sonnet-4-6")
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=m,
            max_tokens=256,
            system=_HYDE_PROMPT,
            messages=[{"role": "user", "content": query}],
        )
        hypo = resp.content[0].text.strip()
        return f"{query} {hypo}" if hypo else query
    except Exception:
        return query


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def max_rerank_candidate_count(rerank_events: list[dict[str, Any]] | None) -> int:
    n = 0
    for ev in rerank_events or []:
        if not isinstance(ev, dict):
            continue
        c = ev.get("candidate_count")
        if isinstance(c, int) and c > n:
            n = c
    return n


def rerank_adaptive_starved(rerank_events: list[dict[str, Any]] | None) -> bool:
    for ev in rerank_events or []:
        if not isinstance(ev, dict):
            continue
        if ev.get("skip_reason") == "adaptive_below_threshold":
            return True
    return False


def should_trigger_query_fallback(
    ctx_rows: list[dict[str, Any]],
    retrieval_telemetry: dict[str, Any] | None,
) -> tuple[bool, str]:
    """
    Päättele tarvitaanko toinen hakuyritys (leveämpi profiili + uudet kyselyt).
    """
    te = retrieval_telemetry or {}
    rerank_events = list(te.get("rerank_events") or [])
    pool = int(te.get("pre_rerank_pool_size") or 0)
    min_rows = _env_int("ZT_FALLBACK_MIN_CTX_ROWS", 2)
    min_pool = _env_int("ZT_FALLBACK_MIN_PRE_RERANK_POOL", 12)

    if not ctx_rows:
        return True, "empty_context"
    if len(ctx_rows) < min_rows:
        return True, "few_context_rows"
    if pool and pool < min_pool:
        return True, "small_pre_rerank_pool"
    if rerank_adaptive_starved(rerank_events):
        return True, "rerank_adaptive_starved"
    if max_rerank_candidate_count(rerank_events) < min_pool:
        return True, "few_rerank_candidates"
    return False, "none"


def fallback_decompose_queries(
    question: str,
    model: str | None,
    *,
    corpus_term_hints: list[str] | None,
) -> tuple[list[str], str]:
    """Toisen yrityksen alakyselyt: korostaa konkreettista teknistä sanastoa."""
    m = model or os.environ.get("ZT_QUERY_MODEL", "claude-sonnet-4-6")
    hints = [h for h in (corpus_term_hints or []) if str(h).strip()]
    max_hints = _env_int("ZT_TERM_HINTS_MAX", 24)
    hints = hints[:max_hints]

    if hints and corpus_aware_rewrite_enabled():
        system = _CORPUS_AWARE_FALLBACK_SYSTEM
        user = (
            "Corpus terms (use only when relevant to the question):\n"
            + "\n".join(f"- {h}" for h in hints)
            + f"\n\nUser question:\n{question}"
        )
    else:
        system = _FALLBACK_DECOMPOSE_SYSTEM
        user = question

    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=m,
            max_tokens=512,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        raw = resp.content[0].text.strip()
        sub = parse_subquery_json(raw)
        if not sub:
            sq = translate_query_for_retrieval(question, model).strip() or question.strip()
            return [sq], sq
        seen: set[str] = set()
        uniq: list[str] = []
        for s in sub:
            k = s.lower()
            if k in seen:
                continue
            seen.add(k)
            uniq.append(s)
        rerank_text = " ".join(uniq[:5])
        return uniq[:5], rerank_text
    except Exception:
        sq = translate_query_for_retrieval(question, model).strip() or question.strip()
        return [sq], sq


@contextmanager
def temporary_env(updates: dict[str, str]):
    """
    Tilapäinen ympäristö (esim. leveämpi hakuprofiili yhdelle hakukutsulle).

    Ei säieturvallinen: MCP/CLI on yksisäikeinen. Älä käytä samaan aikaan
    rinnakkaisia kyselyitä samassa prosessissa.
    """
    old: dict[str, str | None] = {}
    try:
        for k, v in updates.items():
            old[k] = os.environ.get(k)
            os.environ[k] = v
        yield
    finally:
        for k, prev in old.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev


@contextmanager
def hard_retrieval_profile_env():
    """Sama profiili kuin query_hard_profile / mcp_query_batch --hard."""
    with temporary_env(dict(QUERY_HARD_PROFILE_ENV)):
        yield


def query_fallback_enabled() -> bool:
    return env_flag_enabled("ZT_ENABLE_QUERY_FALLBACK")


def term_catalog_feature_enabled() -> bool:
    return not env_flag_enabled("ZT_DISABLE_TERM_CATALOG")


# Tekniset tokenit (komennot, polut, liput) termihakemiston rikastukseen chunk-tekstistä
_TECH_TOKEN_RE = re.compile(
    r"(?:\b[a-z][-a-z0-9_.]{1,}[a-z0-9]\b"
    r"|\b[A-Z][A-Z0-9_]{2,}\b"
    r"|\b:[a-z]+\b"
    r"|\./[\w./-]+"
    r"|--[\w-]+"
    r"|\`[^\`]+\`)"
)

_MAX_TECH_TOKENS_PER_CHUNK = 12


def tech_tokens_from_text(text: str) -> list[str]:
    if not text or len(text) > 120_000:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for m in _TECH_TOKEN_RE.finditer(text):
        t = m.group(0).strip()
        if len(t) < 2 or len(t) > 80:
            continue
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
        if len(out) >= _MAX_TECH_TOKENS_PER_CHUNK:
            break
    return out
