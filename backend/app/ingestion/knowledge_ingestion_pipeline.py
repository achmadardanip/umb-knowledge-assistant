"""Phase 28.2 — auto knowledge-injection pipeline.

When a fallback web search (Tavily, restricted to trusted domains) finds highly
relevant official Mercu Buana content, this ingests it into PostgreSQL/pgvector
with full provenance — but ONLY if all gates pass:

  * domain is trusted (*.mercubuana.ac.id or an official accreditation agency)
  * relevance >= threshold
  * content is NOT a duplicate (content_hash)

Reuses the dedup-aware ``upsert_source_document`` (skips re-chunking on identical
content) + ``backfill_embeddings`` (embeds only new chunks), then registers
freshness + the crawl registry. Returns a provenance record.

Import-safe and side-effect-free until ``ingest_web_result`` is called.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.orm import Session

# Official accreditation agencies (in addition to *.mercubuana.ac.id).
_ACCREDITATION_DOMAINS = (
    "banpt.or.id", "lamemba.or.id", "lamteknik.or.id", "laminfokom.or.id",
    "lamdik.kemdikbud.go.id", "lpuk.org",
)
_TRUSTED_SUFFIXES = ("mercubuana.ac.id",) + _ACCREDITATION_DOMAINS
_RELEVANCE_THRESHOLD = 0.6
_MIN_WORDS = 40


@dataclass
class IngestionResult:
    ingested: bool
    reason: str
    url: str
    chunks_added: int = 0
    duplicate: bool = False
    confidence: float | None = None


def is_trusted(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == s or host.endswith("." + s) or host.endswith(s) for s in _TRUSTED_SUFFIXES)


def _clean(content: str) -> str:
    content = re.sub(r"\s+\n", "\n", content or "")
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content.strip()


def _content_hash(text_: str) -> str:
    from app.ingestion.pipeline import content_hash
    return content_hash(text_)


def ingest_web_result(
    db: Session,
    url: str,
    content: str,
    title: str | None = None,
    *,
    relevance: float = 0.0,
    threshold: float = _RELEVANCE_THRESHOLD,
    discovery_source: str = "tavily",
) -> IngestionResult:
    """Ingest one trusted, relevant, non-duplicate web result. No hallucination:
    rejects anything that fails a gate (caller then keeps the safe refusal path)."""
    if not is_trusted(url):
        return IngestionResult(False, "untrusted_domain", url, confidence=relevance)
    if relevance < threshold:
        return IngestionResult(False, f"low_relevance<{threshold}", url, confidence=relevance)
    body = _clean(content)
    if len(body.split()) < _MIN_WORDS:
        return IngestionResult(False, "too_short", url, confidence=relevance)

    # duplicate detection (content already in KB under any URL)
    h = _content_hash(body)
    try:
        dup = db.execute(text("SELECT 1 FROM sources WHERE content_hash = :h LIMIT 1"), {"h": h}).first()
    except Exception:
        dup = None
    if dup:
        return IngestionResult(False, "duplicate_content", url, duplicate=True, confidence=relevance)

    from app.ingestion.embed_backfill import backfill_embeddings
    from app.ingestion.pipeline import upsert_source_document

    parsed = urlparse(url)
    n_chunks = upsert_source_document(
        db, url=url, text=body, title=title,
        metadata={"url": url, "hostname": (parsed.hostname or "").lower(), "ingested_via": discovery_source},
        http_status=200, discovery_source=discovery_source,
        source_type="pdf" if url.lower().endswith(".pdf") else "html",
        extraction_method="tavily_fallback", extraction_confidence=float(relevance),
    )
    # mark indexed + register provenance/freshness
    db.execute(text(
        "UPDATE sources SET status='indexed', fetched_at=now(), first_seen_date=COALESCE(first_seen_date, now()), "
        "last_verified_date=now(), extraction_date=now() WHERE url=:u"
    ), {"u": url})
    db.commit()

    embedded = backfill_embeddings(db, only_keyword_only=False)

    # register in the crawl registry for future change-detection
    try:
        db.execute(text(
            "INSERT INTO crawl_registry (id, url, hostname, content_hash, content_type, last_crawl, "
            "crawl_status, http_status, crawl_frequency, failure_count, created_at, updated_at) "
            "VALUES (gen_random_uuid(), :u, :h, :ch, :ct, now(), 'crawled', 200, 'weekly', 0, now(), now()) "
            "ON CONFLICT (url) DO UPDATE SET content_hash=EXCLUDED.content_hash, last_crawl=now()"
        ), {"u": url, "h": (parsed.hostname or "").lower(), "ch": h,
            "ct": "pdf" if url.lower().endswith(".pdf") else "html"})
        db.commit()
    except Exception:
        db.rollback()

    return IngestionResult(True, "ingested", url, chunks_added=n_chunks, confidence=relevance)
