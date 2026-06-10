from __future__ import annotations

import logging

from app.core.config import get_settings
from app.web_search.live_fetcher import fetch_firecrawl_contexts, fetch_live_contexts
from app.web_search.tavily_client import TavilyClient, WebSearchConfigurationError


logger = logging.getLogger(__name__)


class UMBLiveWebRetriever:
    def __init__(self):
        self.client = TavilyClient()

    def search(self, query: str, *, top_k: int | None = None) -> list[dict]:
        settings = get_settings()
        limit = max(1, min(top_k or settings.web_search_top_k, settings.rag_top_k_max))
        results = self.client.search(query, max_results=max(limit, settings.web_search_top_k))
        contexts: list[dict] = []
        for result in results:
            if len(contexts) >= limit:
                break
            try:
                page_contexts = fetch_firecrawl_contexts(result.url, title=result.title, score=result.score or 0.5)
                if not page_contexts:
                    page_contexts = fetch_live_contexts(result.url, title=result.title, score=result.score or 0.5)
            except WebSearchConfigurationError:
                raise
            except Exception as exc:
                logger.info("Firecrawl live parse failed for %s; trying direct fetch: %s", result.url, exc)
                try:
                    page_contexts = fetch_live_contexts(result.url, title=result.title, score=result.score or 0.5)
                except Exception as fallback_exc:
                    logger.info("Skipping live web result %s: %s", result.url, fallback_exc)
                    continue
            contexts.extend(page_contexts)
        contexts.sort(key=lambda context: float(context.get("score") or 0.0), reverse=True)
        return contexts[:limit]
