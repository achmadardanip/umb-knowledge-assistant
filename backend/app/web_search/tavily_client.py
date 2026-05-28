from __future__ import annotations

from dataclasses import dataclass

import requests

from app.core.config import get_settings
from app.discovery.scope_validator import validate_url_scope
from app.discovery.url_normalizer import is_archive_url, normalize_url


class WebSearchConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class TavilySearchResult:
    title: str | None
    url: str
    snippet: str
    score: float


class TavilyClient:
    endpoint = "https://api.tavily.com/search"

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.tavily_api_key
        self.strict_domain = settings.web_search_strict_domain
        self.timeout = settings.web_search_timeout_seconds

    def ensure_configured(self) -> None:
        if not get_settings().web_search_enabled:
            raise WebSearchConfigurationError("Web search selected but WEB_SEARCH_ENABLED is false.")
        if not self.api_key:
            raise WebSearchConfigurationError("Web search selected but TAVILY_API_KEY is not configured.")

    def search(self, query: str, *, max_results: int | None = None) -> list[TavilySearchResult]:
        self.ensure_configured()
        settings = get_settings()
        limit = max(1, min(max_results or settings.web_search_top_k, 10))
        scoped_query = f"site:{self.strict_domain} {query}".strip()
        response = requests.post(
            self.endpoint,
            json={
                "api_key": self.api_key,
                "query": scoped_query,
                "search_depth": "basic",
                "max_results": limit,
                "include_answer": False,
                "include_raw_content": False,
                "include_domains": [self.strict_domain],
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        results: list[TavilySearchResult] = []
        for item in payload.get("results") or []:
            url = normalize_url(str(item.get("url") or ""))
            if not url or is_archive_url(url):
                continue
            if not validate_url_scope(url, self.strict_domain).is_allowed:
                continue
            results.append(
                TavilySearchResult(
                    title=item.get("title"),
                    url=url,
                    snippet=str(item.get("content") or ""),
                    score=float(item.get("score") or 0.0),
                )
            )
        return results
