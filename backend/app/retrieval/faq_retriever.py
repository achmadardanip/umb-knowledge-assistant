"""
Phase 3 — Canonical FAQ Layer (answer-retrieval).

Runs first in the retrieval pipeline (before entity lookup and vector search).
A user query is matched against curated canonical questions + their paraphrase
aliases.  An accepted match returns the verified answer as the top-ranked
context (score above entity contexts) so the answer generator grounds on it and
cites its source URL.

Matching is deterministic (no embedding): normalized exact match → score 1.0;
otherwise a Dice token-overlap above ``_FUZZY_THRESHOLD`` with a minimum content
overlap.  Curated aliases compensate for the lack of semantic matching.

Distinct from ``app.chat.faq_service`` (home-page popular-questions widget).
"""

from __future__ import annotations

import logging
import re

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# FAQ contexts rank above entity contexts (10.0) — the most curated layer wins.
_FAQ_SCORE_EXACT = 14.0
_FAQ_SCORE_FUZZY = 12.0

# Dice similarity threshold for a fuzzy (non-exact) FAQ match.
_FUZZY_THRESHOLD = 0.62
# Require at least this many overlapping content tokens for a fuzzy match.
# With the Dice threshold above, a single-token overlap can only clear the bar
# when both phrases are very short (|q|+|c| <= 3), e.g. the query "beasiswa?" vs
# the alias "beasiswa umb apa saja" — exactly the short-keyword case we want.
_MIN_CONTENT_OVERLAP = 1

# Question words / ubiquitous tokens stripped before similarity so paraphrases
# align ("Bagaimana cara daftar…" vs "cara mendaftar…") and the omnipresent
# "umb / universitas mercu buana" can't inflate similarity.
_FAQ_STOPWORDS = {
    "apa", "apakah", "bagaimana", "gimana", "dimana", "di", "mana", "kah",
    "kapan", "berapa", "cara", "saja", "yang", "untuk", "dengan", "ada",
    "itu", "adalah", "ke", "dari", "dan", "atau", "tentang", "soal", "mengenai",
    "saya", "aku", "kami", "kita", "nya", "sih", "dong", "ya", "tolong", "mohon",
    "bisa", "boleh", "harus", "ingin", "mau", "pengen",
    "umb", "universitas", "mercu", "buana", "kampus",
    "the", "what", "how", "where", "when", "is", "are", "do", "does", "a", "an",
    "i", "my", "me", "can", "could", "of", "in", "at", "to", "for", "about",
    "please", "tell",
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _content_tokens(text: str) -> set[str]:
    tokens = re.findall(r"[\w]+", _normalize(text))
    meaningful = {t for t in tokens if len(t) > 1 and t not in _FAQ_STOPWORDS}
    # If stripping leaves nothing, fall back to raw tokens so very short queries
    # ("SIA?", "SSO?") still match.
    return meaningful or {t for t in tokens if len(t) > 1}


def _dice(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return (2.0 * inter) / (len(a) + len(b))


def _load_active_faqs(db: Session) -> list:
    """Active FAQ rows as lightweight, cacheable records (read on every chat). v3 P5
    caches them so the FAQ table isn't re-read from Supabase each request."""
    from types import SimpleNamespace

    from app.core.cache import cache_get, cache_set, make_key

    key = make_key("faq_active", "v1")
    cached = cache_get(key)
    if cached is not None:
        return cached
    from app.db.models import UMBFAQ

    records = [
        SimpleNamespace(
            id=f.id,
            canonical_question=f.canonical_question,
            answer=f.answer,
            aliases=list(f.aliases or []),
            category=f.category,
            source_urls=list(f.source_urls or []),
            source_confidence=f.source_confidence,
        )
        for f in db.query(UMBFAQ).filter(UMBFAQ.is_active.is_(True)).all()
    ]
    from app.core.config import get_settings

    cache_set(key, records, get_settings().faq_cache_ttl_seconds)
    return records


def _candidate_phrases(faq) -> list[str]:
    phrases = [faq.canonical_question]
    aliases = faq.aliases if isinstance(faq.aliases, list) else []
    phrases.extend(a for a in aliases if a)
    return phrases


def _faq_context(faq, score: float, matched_via: str) -> dict:
    src_urls = faq.source_urls if isinstance(faq.source_urls, list) else []
    url = src_urls[0] if src_urls else "https://www.mercubuana.ac.id/"
    hostname = url.split("/")[2] if "://" in url else "www.mercubuana.ac.id"
    return {
        "chunk_text": faq.answer,
        "url": url,
        "title": faq.canonical_question,
        "score": score,
        "hostname": hostname,
        "entity_type": "faq",
        "entity_id": str(faq.id),
        "confidence": float(faq.source_confidence or 0.8),
        "source_type": "faq",
        "faq_matched_via": matched_via,
        "faq_category": faq.category,
        "source_urls": src_urls,
    }


def match_faq(db: Session, query: str, *, limit: int = 2) -> list[dict]:
    """Return up to ``limit`` FAQ contexts whose canonical question or aliases
    match the query.  Returns [] if the table is missing, no FAQ is active, or
    nothing clears the threshold."""
    try:
        normalized_query = _normalize(query)
        if not normalized_query:
            return []
        query_tokens = _content_tokens(query)
        if not query_tokens:
            return []

        faqs = _load_active_faqs(db)
        scored: list[tuple[float, str, object]] = []
        for faq in faqs:
            best_score = 0.0
            best_via = ""
            for phrase in _candidate_phrases(faq):
                if _normalize(phrase) == normalized_query:
                    best_score, best_via = 1.0, "exact"
                    break
                phrase_tokens = _content_tokens(phrase)
                overlap = len(query_tokens & phrase_tokens)
                if overlap < _MIN_CONTENT_OVERLAP:
                    continue
                dice = _dice(query_tokens, phrase_tokens)
                if dice > best_score:
                    best_score, best_via = dice, "fuzzy"
            if best_via == "exact" or best_score >= _FUZZY_THRESHOLD:
                scored.append((best_score, best_via, faq))

        if not scored:
            return []

        scored.sort(key=lambda x: x[0], reverse=True)
        results: list[dict] = []
        for raw_score, via, faq in scored[:limit]:
            score = _FAQ_SCORE_EXACT if via == "exact" else _FAQ_SCORE_FUZZY
            ctx = _faq_context(faq, score, via)
            ctx["faq_match_score"] = round(float(raw_score), 3)
            results.append(ctx)
        # Intent-aware demotion: a broad/off-topic FAQ (e.g. the program-list FAQ)
        # must not answer a specific topical question (admissions, tuition, …).
        from app.rag.intent_router import apply_entity_intent_compatibility

        apply_entity_intent_compatibility(query, results)
        return results

    except OperationalError as exc:
        logger.debug("FAQ table not available (migration pending?): %s", exc)
        return []
    except Exception as exc:
        logger.warning("FAQ lookup failed: %s", exc)
        return []
