"""Trust-aware support score for C²GV.

Combines entailment with the Trust-substrate primitives — authority A, freshness
F, corroboration C — into a single per-claim support score in [0, 1]. The
conformal layer calibrates an admission threshold over this score.

Trust features are optional: until authority (M2), freshness (M3), and
corroboration (M4) are computed, the score defaults to entailment-only, so the
gate's behaviour is unchanged. Callers opt into trust weighting by passing
non-zero weights and the corresponding features.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SupportWeights:
    entailment: float = 1.0
    authority: float = 0.0
    freshness: float = 0.0
    corroboration: float = 0.0


def support_score(
    *,
    entailment: float,
    authority: float | None = None,
    freshness: float | None = None,
    corroboration: float | None = None,
    weights: SupportWeights = SupportWeights(),
) -> float:
    """Weighted average over the features that are present.

    Missing features are simply excluded from the normalization (no penalty), so
    an entailment-only call returns the entailment score regardless of weights.
    """
    terms: list[tuple[float, float]] = [(weights.entailment, entailment)]
    if authority is not None:
        terms.append((weights.authority, authority))
    if freshness is not None:
        terms.append((weights.freshness, freshness))
    if corroboration is not None:
        terms.append((weights.corroboration, corroboration))
    total_weight = sum(weight for weight, _ in terms)
    if total_weight <= 0:
        return entailment
    return sum(weight * value for weight, value in terms) / total_weight
