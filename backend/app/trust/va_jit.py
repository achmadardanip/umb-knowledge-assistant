"""Volatility-Aware Just-in-Time Verification (VA-JIT) — Method 1.

Unlike active-retrieval methods that trigger on *generation uncertainty*, VA-JIT
triggers on **knowledge dynamics**: a fact that is volatile (fees, deadlines,
schedules, contacts) AND whose best indexed evidence is stale or under-
corroborated is re-verified by a *targeted, cost-bounded* live re-fetch of the
top-authority in-scope page — so a fee/deadline is correct on the day asked, not
merely as of the last crawl.

This module is the decision core (pure, testable). Wiring: in process_chat, after
indexed retrieval, call ``va_jit_reverify(query, contexts, fetcher=...)`` with a
``fetcher`` built from the existing live web retriever, gated by ``VA_JIT_ENABLED``;
fold the returned fresh contexts back through TAHF + CGCV (the conformal buy-back).
"""

from __future__ import annotations

from typing import Callable

from app.trust.volatility import query_volatility

Fetcher = Callable[..., list[dict]]


def should_reverify(
    *,
    volatility: float,
    best_freshness: float,
    corroboration: int,
    volatility_threshold: float = 0.7,
    freshness_threshold: float = 0.5,
    min_corroboration: int = 2,
) -> bool:
    """Trigger when the fact is volatile AND (stale OR under-corroborated)."""
    if volatility < volatility_threshold:
        return False
    return best_freshness < freshness_threshold or corroboration < min_corroboration


def va_jit_reverify(
    query: str,
    contexts: list[dict],
    *,
    fetcher: Fetcher,
    budget: int = 2,
    volatility: float | None = None,
    volatility_threshold: float = 0.7,
    freshness_threshold: float = 0.5,
    min_corroboration: int = 2,
) -> list[dict]:
    """Return fresh contexts from a bounded live re-fetch, or [] if not triggered.

    Corroboration is approximated by the count of distinct authoritative hosts
    among the retrieved contexts (near-duplicate collapse happens upstream).
    """
    resolved_volatility = query_volatility(query) if volatility is None else volatility
    best_freshness = max((context.get("freshness", 1.0) for context in contexts), default=0.0)
    corroboration = len({context.get("hostname") for context in contexts if context.get("hostname")})
    if not should_reverify(
        volatility=resolved_volatility,
        best_freshness=best_freshness,
        corroboration=corroboration,
        volatility_threshold=volatility_threshold,
        freshness_threshold=freshness_threshold,
        min_corroboration=min_corroboration,
    ):
        return []
    fresh = fetcher(query, budget=budget) or []
    return fresh[:budget]
