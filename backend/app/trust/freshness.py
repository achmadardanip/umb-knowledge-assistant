"""Freshness decay for the Trust substrate (§4.1).

``F = 0.5 ** (age / half_life)`` — equivalent to ``exp(-lambda * age)`` with
``lambda = ln(2) / half_life``. The half-life is set per volatility class
(fees/deadlines short, vision/history long), so volatile facts decay fast.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.trust.volatility import half_life_for_volatility


def freshness(age_seconds: float, half_life_seconds: float) -> float:
    if age_seconds <= 0:
        return 1.0
    if half_life_seconds <= 0:
        return 0.0
    return 0.5 ** (age_seconds / half_life_seconds)


def freshness_from_age(fetched_at: datetime | None, volatility: float, *, now: datetime | None = None) -> float:
    """Freshness of a source given when it was fetched and the query volatility.

    Volatile facts (short half-life) decay fast; stable facts stay fresh for
    months. An unknown timestamp is treated as neutral (1.0) so missing metadata
    never penalises a source.
    """
    if fetched_at is None:
        return 1.0
    now = now or datetime.now(timezone.utc)
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    age_seconds = (now - fetched_at).total_seconds()
    return freshness(max(age_seconds, 0.0), half_life_for_volatility(volatility))
