"""Phase 17 P17.5 — crawl monitoring endpoint (read-only ledger view)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.crawl.incremental import registry_status
from app.db.database import get_db

router = APIRouter(tags=["crawl"])


@router.get("/crawl/status")
def crawl_status(db: Session = Depends(get_db)) -> dict:
    """Incremental-crawl ledger summary for the admin monitoring card.

    Exposes crawled / changed / skipped / failed counts, the cadence split and the
    last crawl time. Values are read live from crawl_registry (never hardcoded)."""
    try:
        status = registry_status(db)
    except Exception:
        # Registry not migrated yet — degrade gracefully rather than 500.
        return {"available": False, "total_urls": 0}
    status["available"] = True
    return status


@router.get("/crawl/recent")
def crawl_recent(limit: int = 20, db: Session = Depends(get_db)) -> dict:
    """Most recently changed URLs (for the dashboard detail list)."""
    try:
        rows = db.execute(
            text(
                "SELECT url, hostname, content_type, crawl_status, last_crawl, last_changed "
                "FROM crawl_registry WHERE last_changed IS NOT NULL "
                "ORDER BY last_changed DESC LIMIT :n"
            ),
            {"n": max(1, min(limit, 100))},
        ).all()
    except Exception:
        return {"items": []}
    return {
        "items": [
            {
                "url": r[0], "hostname": r[1], "content_type": r[2], "crawl_status": r[3],
                "last_crawl": r[4].isoformat() if r[4] else None,
                "last_changed": r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ]
    }
