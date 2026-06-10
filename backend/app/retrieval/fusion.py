"""Reciprocal Rank Fusion (Cormack et al., SIGIR 2009).

Combines several ranked candidate lists (e.g. dense BGE-M3 + sparse BM25/FTS)
into one ranking that rewards cross-list consensus, without needing comparable
score scales across retrievers.
"""

from __future__ import annotations

from collections import defaultdict


def reciprocal_rank_fusion(ranked_lists: list[list[str]], *, k: int = 60) -> list[tuple[str, float]]:
    """Return ``(item_id, score)`` pairs sorted by fused score, highest first.

    ``k`` damps the influence of items deep in any single list; the canonical
    default is 60.
    """
    scores: dict[str, float] = defaultdict(float)
    for ranked in ranked_lists:
        for rank, item_id in enumerate(ranked, start=1):
            scores[item_id] += 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def tahf_score(relevance: float, authority: float, freshness: float, *, alpha: float, beta: float) -> float:
    """Trust-Aware Hybrid Fusion score: S(d) = rel(d) + alpha*A(h,q) + beta*F(d).

    ``relevance`` is the (rerank/RRF) relevance; ``alpha`` and ``beta`` are tuned
    on a dev set. Lets a fresher, more authoritative source outrank a marginally
    more lexically-relevant but lower-trust one.
    """
    return relevance + alpha * authority + beta * freshness
