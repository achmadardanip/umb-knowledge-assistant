"""Phase 17 — incremental crawl: change detection over the crawl_registry.

The registry is the ledger of every crawlable URL. ``detect_changed_content``
compares a freshly fetched page (content hash + optional Last-Modified) against
the registry and returns a decision so the ingester only re-processes pages that
actually changed — no full re-crawls, no duplicate chunk growth.

This module is the detection/bookkeeping core. The network fetch + (re-)ingestion
are driven by the existing crawler; a scheduler (daily critical / weekly general)
calls ``due_urls`` then ``record_crawl`` for each fetched page.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import CrawlRegistry, utcnow

# Re-crawl cadence per frequency tier.
_FREQUENCY_DAYS = {"daily": 1, "weekly": 7, "manual": 10_000}


def content_hash(body: bytes | str) -> str:
    data = body.encode("utf-8") if isinstance(body, str) else body
    return hashlib.sha256(data).hexdigest()


@dataclass
class ChangeDecision:
    url: str
    changed: bool
    reason: str  # new | hash_changed | last_modified_changed | unchanged


def detect_changed_content(
    db: Session,
    url: str,
    *,
    new_hash: str | None = None,
    last_modified: datetime | None = None,
) -> ChangeDecision:
    """Decide whether a freshly fetched page must be re-ingested. Re-ingest only
    when the URL is new, its content hash changed, or its server Last-Modified is
    newer than what we recorded. Otherwise skip."""
    row = db.query(CrawlRegistry).filter(CrawlRegistry.url == url).first()
    if row is None:
        return ChangeDecision(url, True, "new")
    if new_hash and row.content_hash and new_hash != row.content_hash:
        return ChangeDecision(url, True, "hash_changed")
    if new_hash and not row.content_hash:
        return ChangeDecision(url, True, "hash_changed")
    if last_modified and row.last_modified:
        lm = last_modified if last_modified.tzinfo else last_modified.replace(tzinfo=timezone.utc)
        prev = row.last_modified if row.last_modified.tzinfo else row.last_modified.replace(tzinfo=timezone.utc)
        if lm > prev:
            return ChangeDecision(url, True, "last_modified_changed")
    return ChangeDecision(url, False, "unchanged")


def record_crawl(
    db: Session,
    url: str,
    *,
    new_hash: str | None = None,
    last_modified: datetime | None = None,
    http_status: int | None = None,
    content_type: str | None = None,
    status: str = "crawled",
    changed: bool | None = None,
) -> CrawlRegistry:
    """Upsert the registry row after a crawl. Bumps last_crawl always; bumps
    last_changed only when the content actually changed."""
    row = db.query(CrawlRegistry).filter(CrawlRegistry.url == url).first()
    now = utcnow()
    if row is None:
        row = CrawlRegistry(url=url, crawl_frequency="weekly")
        db.add(row)
        changed = True if changed is None else changed
    if changed is None:
        changed = bool(new_hash and new_hash != row.content_hash)
    if new_hash:
        row.content_hash = new_hash
    if last_modified:
        row.last_modified = last_modified
    if content_type:
        row.content_type = content_type
    if http_status is not None:
        row.http_status = http_status
    row.last_crawl = now
    row.crawl_status = status
    if changed:
        row.last_changed = now
    if status == "failed":
        row.failure_count = (row.failure_count or 0) + 1
    db.commit()
    return row


def due_urls(db: Session, frequency: str | None = None, limit: int = 500) -> list[str]:
    """URLs whose cadence has elapsed (or never crawled). ``frequency`` filters to
    a tier (daily/weekly); None returns everything due."""
    q = db.query(CrawlRegistry)
    if frequency:
        q = q.filter(CrawlRegistry.crawl_frequency == frequency)
    out: list[str] = []
    now = datetime.now(timezone.utc)
    for row in q.limit(limit * 4).all():
        budget = _FREQUENCY_DAYS.get(row.crawl_frequency or "weekly", 7)
        last = row.last_crawl
        if last is None:
            out.append(row.url)
        else:
            last = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
            if now - last >= timedelta(days=budget):
                out.append(row.url)
        if len(out) >= limit:
            break
    return out


def registry_status(db: Session) -> dict:
    """Aggregate registry stats for GET /crawl/status and the efficiency report."""
    s = lambda q: db.execute(text(q)).scalar()
    by_status = dict(db.execute(text(
        "SELECT crawl_status, count(*) FROM crawl_registry GROUP BY crawl_status"
    )).all())
    by_freq = dict(db.execute(text(
        "SELECT crawl_frequency, count(*) FROM crawl_registry GROUP BY crawl_frequency"
    )).all())
    return {
        "total_urls": s("SELECT count(*) FROM crawl_registry"),
        "by_status": by_status,
        "by_frequency": by_freq,
        "with_hash": s("SELECT count(*) FROM crawl_registry WHERE content_hash IS NOT NULL"),
        "pdf_urls": s("SELECT count(*) FROM crawl_registry WHERE content_type='pdf'"),
        "changed_last_7d": s(
            "SELECT count(*) FROM crawl_registry WHERE last_changed >= now() - interval '7 days'"
        ),
        "failed": s("SELECT count(*) FROM crawl_registry WHERE crawl_status='failed'"),
        "last_crawl": (lambda v: v.isoformat() if v else None)(s("SELECT max(last_crawl) FROM crawl_registry")),
        "due_now": len(due_urls(db, limit=10_000)),
    }
