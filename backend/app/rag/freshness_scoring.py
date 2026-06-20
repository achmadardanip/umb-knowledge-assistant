"""Phase 19 P19.4 — freshness enforcement (ranking-confidence penalty).

Stale sources are NOT hidden and their citations are NOT removed — only their
ranking *confidence* is reduced and a stale warning is attached, so the answer
still shows them but flags that the evidence may be outdated.

  green  (≤30d)   multiplier 1.00   no warning
  yellow (31-180) multiplier 0.97   "aging"
  red    (>180d)  multiplier 0.85   "stale" + warning

The penalty is applied post-retrieval to the source confidence (relevance_score),
not to which sources are retrieved or their citation order — so it cannot change
official_top / citation_failure. On the current KB (all sources fresh) the
multiplier is 1.0 for every source ⇒ provably zero retrieval regression.
"""

from __future__ import annotations

from app.rag.freshness import AGING_MAX_DAYS, FRESH_MAX_DAYS

AGING_MULTIPLIER = 0.97
STALE_MULTIPLIER = 0.85


def freshness_multiplier(days: int | None) -> float:
    if days is None:
        return 1.0
    if days <= FRESH_MAX_DAYS:
        return 1.0
    if days <= AGING_MAX_DAYS:
        return AGING_MULTIPLIER
    return STALE_MULTIPLIER


def freshness_penalty(days: int | None) -> float:
    return round(1.0 - freshness_multiplier(days), 4)


def is_stale(days: int | None) -> bool:
    return days is not None and days > AGING_MAX_DAYS


def apply_freshness_confidence(sources: list[dict]) -> list[dict]:
    """Adjust each source's ranking *confidence* by its freshness multiplier and
    attach a stale warning. Requires the Phase-16 freshness fields to already be on
    the source (enrich_sources_with_freshness). Order/membership are untouched."""
    for s in sources:
        days = s.get("freshness_days")
        mult = freshness_multiplier(days)
        base = s.get("relevance_score")
        if isinstance(base, (int, float)):
            s["freshness_adjusted_score"] = round(float(base) * mult, 4)
        s["freshness_multiplier"] = mult
        s["freshness_penalty"] = round(1.0 - mult, 4)
        if is_stale(days):
            s["stale_warning"] = (
                f"Sumber ini terakhir diverifikasi {days} hari lalu — informasi mungkin "
                "sudah tidak terkini. Verifikasi ke unit resmi UMB."
            )
    return sources
