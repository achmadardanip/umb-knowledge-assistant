"""
Phase 33 P33.2 — Tavily auto-ingestion pipeline.

When the Tavily fallback successfully answers a KB miss, the result is recorded as a
``knowledge_candidates`` row. This module decides, per candidate, whether to
AUTO-INGEST it into the KB (so the next identical question is served from the indexed
KB with no external round-trip) or HOLD it for review.

Auto-ingest rules (ALL must hold):
  * trust_score    >= TAVILY_AUTOINGEST_MIN_TRUST (default 0.9)
  * domain endswith mercubuana.ac.id
  * duplicate_score < 0.9   (not already substantially in the KB)
  * relevance       > 0.85  (answers the asked question)

Otherwise the candidate is kept with ``accepted=false`` for human review. Actual KB
insertion reuses the existing trusted ingestion path
(``knowledge_ingestion_pipeline.ingest_web_result``) so provenance, citations and
embeddings are produced exactly as for any other KB content — no new ingest path,
no provenance loss.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.trust.source_trust import OFFICIAL, classify_source

logger = logging.getLogger(__name__)


@dataclass
class CandidateDecision:
    auto_ingest: bool
    accepted: bool
    reason: str
    trust_score: float
    duplicate_score: float
    relevance: float


def _hash(q: str) -> str:
    return hashlib.sha256((q or "").strip().lower().encode("utf-8")).hexdigest()[:32]


def _is_official(url: str) -> bool:
    h = (urlparse(url).hostname or "").lower()
    return h == OFFICIAL or h.endswith("." + OFFICIAL)


def decide(trust_score: float, duplicate_score: float, relevance: float, url: str,
           *, min_trust: float | None = None) -> CandidateDecision:
    settings = get_settings()
    if min_trust is None:
        min_trust = settings.tavily_autoingest_min_trust
    official = _is_official(url)
    auto = (
        trust_score >= min_trust
        and official
        and duplicate_score < 0.9
        and relevance > 0.85
    )
    if auto:
        reason = "auto_ingest"
    elif not official:
        reason = "hold_non_official"
    elif trust_score < min_trust:
        reason = "hold_low_trust"
    elif duplicate_score >= 0.9:
        reason = "hold_duplicate"
    else:
        reason = "hold_low_relevance"
    return CandidateDecision(auto, auto, reason, trust_score, duplicate_score, relevance)


def record_candidate(db: Session, *, query: str, answer: str, source_url: str,
                     relevance: float = 0.0, duplicate_score: float = 0.0) -> CandidateDecision:
    """Persist a Tavily candidate and decide auto-ingest vs review. Returns the
    decision; never raises into the caller (best-effort enrichment)."""
    from app.db.models import KnowledgeCandidate

    trust, klass = classify_source(source_url)
    decision = decide(trust, duplicate_score, relevance, source_url)
    try:
        row = KnowledgeCandidate(
            query=query,
            query_hash=_hash(query),
            answer=(answer or "")[:8000],
            source_url=source_url,
            source_domain=(urlparse(source_url).hostname or "").lower(),
            trust_score=trust,
            source_class=klass,
            relevance=relevance,
            duplicate_score=duplicate_score,
            accepted=decision.accepted,
            reason=decision.reason,
        )
        db.add(row)
        db.flush()
    except Exception as exc:  # candidate logging must never break the chat flow
        logger.info("knowledge_candidate record skipped: %s", exc)
        db.rollback()
        return decision

    if decision.auto_ingest:
        try:
            from app.ingestion.knowledge_ingestion_pipeline import ingest_web_result

            ingest_web_result(db, query=query, url=source_url, text=answer)
            row.ingested = True
            db.flush()
        except Exception as exc:
            logger.info("auto-ingest of candidate deferred (%s): %s", source_url, exc)
    return decision
