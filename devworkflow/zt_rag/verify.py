"""Sitaattiverifiointi ja valinnainen NLI."""
from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Any

from devworkflow.zt_rag.schemas import ZtAnswer, refusal_payload
from devworkflow.zt_rag.retrieval import PublishedIndex
from devworkflow.zt_rag.versioning import content_hash, normalize_for_match


def _high_risk_question(q: str) -> bool:
    ql = q.lower()
    keys = (
        "lääk", "legal", "oikeus", "guarantee", "varmasti aina",
        "invest", "tervey", "diagnos",
    )
    return any(k in ql for k in keys)


_TYPOGRAPHIC_MAP = str.maketrans({
    "\u2018": "'", "\u2019": "'",  # ' '
    "\u201c": '"', "\u201d": '"',  # " "
    "\u2013": "-", "\u2014": "-",  # – —
    "\u2026": "...",               # …
})


def _flatten(s: str) -> str:
    """Normalisoi lainausmerkit, viivat ja whitespace vertailua varten."""
    t = s.translate(_TYPOGRAPHIC_MAP)
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


def _strip_punct(s: str) -> str:
    return re.sub(r"[^\w\s]", "", s).strip()


def _quote_in_body(nquote: str, nbody: str) -> bool:
    """Monikerroksinen sitaattitarkistus: tarkasta → flatten → sanaosuma."""
    fq = _flatten(nquote)
    fb = _flatten(nbody)
    if fq in fb:
        return True
    sq = _strip_punct(fq)
    sb = _strip_punct(fb)
    if sq in sb:
        return True
    words = sq.split()
    if len(words) >= 4:
        body_words = set(sb.split())
        hits = sum(1 for w in words if w in body_words)
        if hits / len(words) >= 0.80:
            return True
    return False


@lru_cache(maxsize=1)
def _nli_pipeline():
    """Yksi transformers-pipeline-instanssi per prosessi (ei uudelleenalustusta joka kyselyllä)."""
    from transformers import pipeline

    return pipeline(
        "text-classification",
        model="cross-encoder/nli-deberta-v3-small",
        device=-1,
    )


def verify_citations(
    answer: ZtAnswer,
    index: PublishedIndex,
    _published_meta_source_fingerprint: str,
) -> tuple[bool, str]:
    """
    Tarkista että jokainen sitaatti löytyy chunkista ja chunk_hash on eheä.
    """
    if not answer.citations:
        if normalize_for_match(answer.answer) == normalize_for_match(
            refusal_payload()["answer"]
        ):
            return True, "refusal_ok"
        return False, "non_refusal_without_citations"

    chunks_map = index.chunks_map
    for cit in answer.citations:
        row = chunks_map.get(cit.chunk_id)
        if row is None:
            return False, f"unknown_chunk:{cit.chunk_id}"
        body = str(row.get("text", ""))
        nbody = normalize_for_match(body)
        nquote = normalize_for_match(cit.quote)
        if not nquote:
            return False, "empty_quote"
        if not _quote_in_body(nquote, nbody):
            return False, f"quote_not_in_chunk:{cit.chunk_id}"
        expected = str(row.get("chunk_hash", ""))
        if expected and content_hash(nbody) != expected:
            return False, f"chunk_hash_mismatch:{cit.chunk_id}"

    return True, "ok"


def maybe_nli_verify(answer_text: str, context_texts: list[str], question: str) -> tuple[bool, str]:
    """NLI vain jos ZT_ENABLE_NLI=1 ja (korkean riskin kysymys tai ZT_NLI_ALWAYS=1)."""
    if os.environ.get("ZT_ENABLE_NLI", "").lower() not in ("1", "true", "yes"):
        return True, "nli_disabled"

    always = os.environ.get("ZT_NLI_ALWAYS", "").lower() in ("1", "true", "yes")
    if not always and not _high_risk_question(question):
        return True, "nli_skipped_low_risk"

    try:
        nli = _nli_pipeline()
    except ImportError:
        return False, "nli_import_failed"
    nans = normalize_for_match(answer_text)
    if not nans or nans == normalize_for_match(refusal_payload()["answer"]):
        return True, "nli_skip_refusal"

    best = 0.0
    for ctx in context_texts:
        c = normalize_for_match(ctx)[:2000]
        if not c:
            continue
        pair = f"{c} [SEP] {nans}"
        try:
            out = nli(pair)[0]
        except Exception as e:
            return False, f"nli_error:{e}"
        label = str(out.get("label", "")).upper()
        score = float(out.get("score", 0.0))
        if "CONTRADICT" in label:
            return False, "nli_contradiction"
        if "ENTAIL" in label:
            best = max(best, score)

    threshold = float(os.environ.get("ZT_NLI_THRESHOLD", "0.7"))
    if best < threshold:
        return False, f"nli_below_threshold:{best}"
    return True, f"nli_ok:{best}"


def verify_full_pipeline(
    answer: ZtAnswer,
    index: PublishedIndex,
    meta: dict[str, Any],
    context_chunks: list[dict[str, Any]],
    question: str,
) -> tuple[bool, str, dict[str, Any]]:
    fp = str(meta.get("source_fingerprint", ""))
    ok, reason = verify_citations(answer, index, fp)
    detail: dict[str, Any] = {"citation_check": {"ok": ok, "reason": reason}}
    if not ok:
        return False, reason, detail

    ctx_texts = [str(c.get("text", "")) for c in context_chunks]
    nli_ok, nli_reason = maybe_nli_verify(answer.answer, ctx_texts, question)
    detail["nli"] = {"ok": nli_ok, "reason": nli_reason}
    if not nli_ok:
        return False, nli_reason, detail

    return True, "accepted", detail
