"""
Phase 32 P32.3/P32.4 — TavilyFallbackRetriever.

The single external retrieval path. It activates ONLY when the KB is insufficient,
prioritizes official UMB domains, uses Tavily for BOTH search and content extraction
(no Firecrawl / direct fetch), and trust-filters every result so external answers are
never built on low-trust sources.

Activation policy (``should_activate``): fire only when
  * KB returned empty, OR
  * no citations were produced by the KB layers, OR
  * normalized KB retrieval confidence < ``TAVILY_FALLBACK_THRESHOLD`` (default 0.45).
Never call Tavily when KB confidence is sufficient.

Official-domain prioritization: Tavily search is already scoped to
``site:mercubuana.ac.id`` with ``include_domains``; this retriever additionally accepts
all ``*.mercubuana.ac.id`` subdomains (repository/pmb/baa/elearning/…) and only widens
to a global search when no official result is found.

Off-safe: if the Tavily key/feature is not configured, ``retrieve`` returns [] and the
caller falls back to the normal not-found / clarification path (no crash).
"""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.trust.source_trust import OFFICIAL, filter_trusted, trust_for

logger = logging.getLogger(__name__)


def _normalize_confidence(contexts: list[dict]) -> float:
    """Map the heterogeneous KB scores onto ~[0,1]. Entity scores are 7–10, hybrid/
    TAHF scores are typically 0–3; we normalize both to a comparable confidence."""
    best = 0.0
    for c in contexts or []:
        try:
            s = float(c.get("score") or 0.0)
        except (TypeError, ValueError):
            s = 0.0
        if s > 1.5:  # entity-scale -> /10
            s = min(1.0, s / 10.0)
        else:        # hybrid-scale -> /3 (a strong hybrid top score ~2-3)
            s = min(1.0, s / 3.0)
        best = max(best, s)
    return best


def should_activate(contexts: list[dict], *, citations: int | None = None,
                    threshold: float | None = None) -> tuple[bool, str]:
    """Decide whether the Tavily fallback should run. Returns (activate, reason)."""
    settings = get_settings()
    if threshold is None:
        threshold = settings.tavily_fallback_threshold
    if not settings.web_search_enabled or not settings.tavily_api_key:
        return False, "tavily_not_configured"
    if not contexts:
        return True, "kb_empty"
    if citations is not None and citations <= 0:
        return True, "no_citations"
    conf = _normalize_confidence(contexts)
    if conf < threshold:
        return True, f"low_confidence({conf:.2f}<{threshold:.2f})"
    return False, f"kb_sufficient({conf:.2f}>={threshold:.2f})"


class TavilyFallbackRetriever:
    """Tavily-only external fallback. Search (official-first) → Extract → trust-filter."""

    def __init__(self):
        from app.web_search.tavily_client import TavilyClient

        self.client = TavilyClient()

    def _is_official(self, url: str) -> bool:
        h = (url or "").lower()
        return OFFICIAL in h

    def retrieve(self, query: str, *, top_k: int | None = None,
                 allow_global: bool = True) -> list[dict]:
        """Return trust-filtered external contexts for ``query`` (or [])."""
        settings = get_settings()
        limit = max(1, min(top_k or settings.web_search_top_k, settings.rag_top_k_max))
        try:
            self.client.ensure_configured()
        except Exception as exc:
            logger.info("Tavily fallback unavailable: %s", exc)
            return []

        # 1) Official-domain-first search (TavilyClient already scopes to mercubuana.ac.id).
        try:
            results = self.client.search(query, max_results=max(limit, settings.web_search_top_k))
        except Exception as exc:
            logger.info("Tavily search failed: %s", exc)
            return []

        official = [r for r in results if self._is_official(r.url)]
        chosen = official or (results if allow_global else [])
        if not chosen:
            return []

        # 2) Tavily Extract for clean content (the ONLY external parser; replaces Firecrawl).
        urls = [r.url for r in chosen][:limit]
        try:
            extracts = {e.url: e for e in self.client.extract(urls)}
        except Exception as exc:
            logger.info("Tavily extract failed (%s); using search snippets.", exc)
            extracts = {}

        contexts: list[dict] = []
        for r in chosen[:limit]:
            content = (extracts.get(r.url).raw_content if extracts.get(r.url) else "") or r.snippet
            if not content:
                continue
            v = trust_for(r.url)
            host = r.url.split("/")[2] if "://" in r.url else ""
            contexts.append({
                "chunk_text": content[:4000],
                "url": r.url,
                "title": r.title or r.url,
                "score": float(r.score or 0.5),
                "hostname": host,
                "discovery_source": "tavily_fallback",
                "source_type": "web",
                "trust_score": v.score,
                "source_class": v.source_class,
                "extraction_method": "tavily_extract" if r.url in extracts else "tavily_snippet",
            })

        # 3) Trust filter — reject anything below the trust floor (default 0.7).
        contexts = filter_trusted(contexts)
        contexts.sort(key=lambda c: (float(c.get("trust_score") or 0.0), float(c.get("score") or 0.0)),
                      reverse=True)
        return contexts[:limit]
