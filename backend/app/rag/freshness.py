"""Phase 16 — content-freshness helpers for the retrieval payload.

Each returned source is enriched (additively, post-retrieval — no ranking impact)
with its crawl_date, freshness_days, a freshness tier (fresh/aging/stale) and an
authority_tier so the UI can show "Updated N days ago" and a trust colour.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.trust.authority import host_authority

# Day thresholds (Phase 16 P16.3): 0-30 fresh, 31-180 aging, >180 stale.
FRESH_MAX_DAYS = 30
AGING_MAX_DAYS = 180


def freshness_tier(days: int | None) -> str | None:
    if days is None:
        return None
    if days <= FRESH_MAX_DAYS:
        return "fresh"
    if days <= AGING_MAX_DAYS:
        return "aging"
    return "stale"


def freshness_label(days: int | None) -> str | None:
    if days is None:
        return None
    if days <= 0:
        return "Updated today"
    if days == 1:
        return "Updated 1 day ago"
    if days < 60:
        return f"Updated {days} days ago"
    months = days // 30
    if months < 24:
        return f"Updated {months} month{'s' if months > 1 else ''} ago"
    return f"Updated {days // 365} year{'s' if days // 365 > 1 else ''} ago"


def authority_tier(hostname: str | None, root_domain: str = "mercubuana.ac.id") -> str:
    a = host_authority(hostname or "", root_domain)
    if a >= 0.85:
        return "tier1_official"
    if a >= 0.5:
        return "tier2_in_scope"
    if a >= 0.45:
        return "tier3_library"
    if a >= 0.2:
        return "tier4_archive"
    return "out_of_scope"


def _days_since(dt: datetime | None) -> int | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - dt).days)


def enrich_sources_with_freshness(db: Session, sources: list[dict], root_domain: str = "mercubuana.ac.id") -> list[dict]:
    """Add crawl_date / freshness_days / freshness_tier / freshness_label /
    authority_tier to each source dict (keyed by url). Best-effort: on any DB
    error the sources are returned unchanged (freshness is never load-bearing)."""
    if not sources:
        return sources
    urls = [s.get("url") for s in sources if s.get("url")]
    crawl_by_url: dict[str, tuple] = {}
    if urls:
        try:
            rows = db.execute(
                text(
                    "SELECT url, fetched_at, last_verified_date, source_last_modified "
                    "FROM sources WHERE url = ANY(:urls)"
                ),
                {"urls": urls},
            ).all()
            crawl_by_url = {r[0]: (r[1], r[2], r[3]) for r in rows}
        except Exception:
            crawl_by_url = {}

    for s in sources:
        crawl, verified, last_mod = crawl_by_url.get(s.get("url"), (None, None, None))
        days = _days_since(crawl)
        s["crawl_date"] = crawl.isoformat() if crawl else None
        s["last_verified_date"] = verified.isoformat() if verified else None
        s["source_last_modified"] = last_mod.isoformat() if last_mod else None
        s["freshness_days"] = days
        s["freshness_tier"] = freshness_tier(days)
        s["freshness_label"] = freshness_label(days)
        s["authority_tier"] = authority_tier(s.get("hostname"), root_domain)
    return sources
