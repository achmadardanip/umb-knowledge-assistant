"""Freshness decay for the Trust substrate (§4.1).

``F = 0.5 ** (age / half_life)`` — equivalent to ``exp(-lambda * age)`` with
``lambda = ln(2) / half_life``. The half-life is set per volatility class
(fees/deadlines short, vision/history long), so volatile facts decay fast.
"""

from __future__ import annotations


def freshness(age_seconds: float, half_life_seconds: float) -> float:
    if age_seconds <= 0:
        return 1.0
    if half_life_seconds <= 0:
        return 0.0
    return 0.5 ** (age_seconds / half_life_seconds)
