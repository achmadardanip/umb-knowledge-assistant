"""Volatility-prioritized recrawl ordering (§6).

A source's recrawl priority is how *overdue* it is relative to its expected
change rate: ``1 - freshness``, where freshness decays on a half-life set by the
source's volatility. Volatile sources (fees, schedules) lose freshness fast and
rise to the top; stable sources (vision, history) stay fresh for months and sink.
The freshness crawl workflow recrawls in this order so the day-of facts are
refreshed first under a fixed crawl budget.
"""

from __future__ import annotations

from datetime import datetime

from app.trust.freshness import freshness_from_age
from app.trust.volatility import query_volatility


def recrawl_priority(
    *,
    title: str | None = None,
    path: str | None = None,
    url: str | None = None,
    fetched_at: datetime | None,
    now: datetime | None = None,
) -> float:
    descriptor = " ".join(part for part in [title, path, url] if part)
    volatility = query_volatility(descriptor)
    return 1.0 - freshness_from_age(fetched_at, volatility, now=now)


def prioritize_recrawl(sources: list, *, now: datetime | None = None) -> list:
    """Return sources ordered by recrawl priority (most overdue first)."""

    def key(source) -> float:
        return recrawl_priority(
            title=getattr(source, "title", None),
            path=getattr(source, "path", None),
            url=getattr(source, "url", None),
            fetched_at=getattr(source, "fetched_at", None),
            now=now,
        )

    return sorted(sources, key=key, reverse=True)
