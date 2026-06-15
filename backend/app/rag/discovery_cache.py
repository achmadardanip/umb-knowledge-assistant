"""
Batch 4 — knowledge discovery cache + retrieval confidence evaluation.

* ``evaluate_confidence`` turns the merged retrieval contexts into a 0-1 score +
  a sufficiency flag. This is the explicit "Confidence Check" that gates the
  billed Tavily live fallback: FAQ → Entity → Graph → Hybrid → *confidence* →
  (only if low) Tavily.
* ``was_recently_discovered`` / ``record_discoveries`` back the
  ``knowledge_discovery_cache`` table so a question already resolved through
  Tavily (and acquired into the KB) does not trigger another Tavily search.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from urllib.parse import urlparse

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.rag.answer_cache import question_hash
from app.trust.authority import host_authority

logger = logging.getLogger(__name__)

# Structured layers are curated/high-precision; an official chunk is solid too.
_STRUCTURED = {"faq", "entity", "graph"}


def evaluate_confidence(contexts: list[dict], *, root_domain: str = "mercubuana.ac.id") -> tuple[float, bool]:
    """Return (confidence in [0,1], sufficient?). Sufficient retrieval means the
    live Tavily fallback can be skipped. A strong FAQ/entity/graph hit, or several
    official-host chunks, is sufficient; archive-only / empty is not."""
    if not contexts:
        return 0.0, False
    top = contexts[0]
    top_type = top.get("source_type")
    top_score = float(top.get("score") or 0.0)

    # A non-demoted structured hit is a curated, grounded answer.
    if top_type in _STRUCTURED and not top.get("intent_demoted"):
        return (0.95 if top_score >= 12.0 else 0.85), True

    official = [c for c in contexts if host_authority(c.get("hostname"), root_domain) >= 0.5]
    official_top = host_authority(top.get("hostname"), root_domain) >= 0.5
    # Require ≥2 official chunks to call retrieval confident enough to skip the live
    # fallback. A single lone official chunk is NOT sufficient on its own — defer to
    # the count/score gate (``_kb_contexts_sufficient``) so a thin KB still escalates.
    if official_top and len(official) >= 2:
        return 0.7, True
    if official_top:
        return 0.55, False
    if official:
        return 0.4, False
    return 0.2, False


def was_recently_discovered(db: Session, question: str, *, ttl_hours: int = 168) -> bool:
    """True if this question was resolved via Tavily and acquired into the KB within
    ``ttl_hours`` — so we can skip another Tavily round-trip."""
    try:
        from app.db.models import KnowledgeDiscoveryCache, utcnow

        cutoff = utcnow() - timedelta(hours=max(1, ttl_hours))
        row = (
            db.query(KnowledgeDiscoveryCache.id)
            .filter(
                KnowledgeDiscoveryCache.question_hash == question_hash(question),
                KnowledgeDiscoveryCache.indexed.is_(True),
                KnowledgeDiscoveryCache.created_at >= cutoff,
            )
            .first()
        )
        return row is not None
    except OperationalError:
        return False
    except Exception as exc:
        logger.debug("discovery-cache lookup skipped: %s", exc)
        return False


def record_discoveries(db: Session, question: str, contexts: list[dict], *, indexed: bool) -> int:
    """Insert one cache row per live-web URL that answered ``question``."""
    try:
        from app.db.models import KnowledgeDiscoveryCache

        qhash = question_hash(question)
        urls = []
        seen: set[str] = set()
        for ctx in contexts:
            url = (ctx.get("url") or "").strip()
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
        for url in urls:
            db.add(
                KnowledgeDiscoveryCache(
                    question_hash=qhash,
                    query=question[:1000],
                    normalized_url=url,
                    source_domain=(urlparse(url).hostname or "").lower(),
                    indexed=indexed,
                )
            )
        db.commit()
        return len(urls)
    except Exception as exc:  # best-effort
        logger.warning("record_discoveries failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return 0
