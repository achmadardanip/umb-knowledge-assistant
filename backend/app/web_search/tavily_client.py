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


@dataclass(frozen=True)
class TavilyExtractResult:
    url: str
    raw_content: str
    title: str | None = None


class TavilyClient:
    endpoint = "https://api.tavily.com/search"
    map_endpoint = "https://api.tavily.com/map"
    extract_endpoint = "https://api.tavily.com/extract"
    crawl_endpoint = "https://api.tavily.com/crawl"

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

    def _scoped(self, urls) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in urls or []:
            url = normalize_url(str(raw or ""))
            if not url or url in seen or is_archive_url(url):
                continue
            if not validate_url_scope(url, self.strict_domain).is_allowed:
                continue
            seen.add(url)
            out.append(url)
        return out

    def map_site(self, url: str, *, max_depth: int = 2, limit: int = 200, instructions: str | None = None) -> list[str]:
        """Discover in-scope UMB URLs reachable from a seed page (Tavily /map)."""
        self.ensure_configured()
        body = {
            "url": url,
            "max_depth": max_depth,
            "limit": limit,
            "allow_external": False,
        }
        if instructions:
            body["instructions"] = instructions
        response = requests.post(
            self.map_endpoint,
            json=body,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=max(self.timeout, 60),
        )
        response.raise_for_status()
        payload = response.json()
        return self._scoped(payload.get("results") or payload.get("links") or [])

    def crawl(self, url: str, *, max_depth: int = 2, limit: int = 50, instructions: str | None = None) -> list[TavilyExtractResult]:
        """Discover + extract in-scope UMB pages in one call (Tavily /crawl)."""
        self.ensure_configured()
        body = {"url": url, "max_depth": max_depth, "limit": limit}
        if instructions:
            body["instructions"] = instructions
        response = requests.post(
            self.crawl_endpoint,
            json=body,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=max(self.timeout, 180),
        )
        response.raise_for_status()
        payload = response.json()
        results: list[TavilyExtractResult] = []
        for item in payload.get("results") or []:
            page_url = normalize_url(str(item.get("url") or ""))
            content = str(item.get("raw_content") or item.get("content") or "")
            if not page_url or not content.strip() or is_archive_url(page_url):
                continue
            if not validate_url_scope(page_url, self.strict_domain).is_allowed:
                continue
            results.append(TavilyExtractResult(url=page_url, raw_content=content, title=item.get("title")))
        return results

    def extract(self, urls: list[str], *, extract_depth: str = "basic") -> list[TavilyExtractResult]:
        """Extract clean page content for in-scope URLs (Tavily /extract, <=20 per call)."""
        self.ensure_configured()
        results: list[TavilyExtractResult] = []
        scoped = self._scoped(urls)
        for start in range(0, len(scoped), 20):
            batch = scoped[start : start + 20]
            response = requests.post(
                self.extract_endpoint,
                json={"urls": batch, "extract_depth": extract_depth, "format": "markdown"},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=max(self.timeout, 120),
            )
            response.raise_for_status()
            payload = response.json()
            for item in payload.get("results") or []:
                url = normalize_url(str(item.get("url") or ""))
                content = str(item.get("raw_content") or item.get("content") or "")
                if url and content.strip():
                    results.append(TavilyExtractResult(url=url, raw_content=content, title=item.get("title")))
        return results
