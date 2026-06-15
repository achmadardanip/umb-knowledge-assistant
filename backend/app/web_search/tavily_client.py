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
    images: tuple[str, ...] = ()


class TavilyClient:
    endpoint = "https://api.tavily.com/search"
    map_endpoint = "https://api.tavily.com/map"
    extract_endpoint = "https://api.tavily.com/extract"

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.tavily_api_key
        self.strict_domain = settings.web_search_strict_domain
        self.timeout = settings.web_search_timeout_seconds

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

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

    def map(self, url: str, *, max_depth: int = 2, limit: int = 200, timeout: int | None = None) -> list[str]:
        """Discover in-domain URLs reachable from ``url`` via Tavily's site mapper.

        Returns scope-validated, archive-free URLs. May return an empty list when the
        target site blocks the mapper; callers should fall back to search discovery.
        """

        self.ensure_configured()
        response = requests.post(
            self.map_endpoint,
            json={"url": url, "max_depth": max_depth, "limit": limit, "allow_external": False},
            headers=self._auth_headers(),
            timeout=timeout or max(self.timeout, 60),
        )
        response.raise_for_status()
        payload = response.json()
        out: list[str] = []
        for raw in payload.get("results") or []:
            candidate = raw if isinstance(raw, str) else (raw.get("url") if isinstance(raw, dict) else None)
            normalized = normalize_url(str(candidate or ""))
            if not normalized or is_archive_url(normalized):
                continue
            if not validate_url_scope(normalized, self.strict_domain).is_allowed:
                continue
            out.append(normalized)
        return out

    def extract(self, urls: list[str], *, extract_depth: str = "advanced", timeout: int | None = None) -> list[TavilyExtractResult]:
        """Extract clean markdown/text for up to 20 URLs per call via Tavily Extract."""

        self.ensure_configured()
        batch = [u for u in urls if u][:20]
        if not batch:
            return []
        response = requests.post(
            self.extract_endpoint,
            json={"urls": batch, "extract_depth": extract_depth, "format": "markdown"},
            headers=self._auth_headers(),
            timeout=timeout or max(self.timeout, 90),
        )
        response.raise_for_status()
        payload = response.json()
        results: list[TavilyExtractResult] = []
        for item in payload.get("results") or []:
            url = normalize_url(str(item.get("url") or ""))
            content = str(item.get("raw_content") or "")
            if not url or not content:
                continue
            images = tuple(str(i) for i in (item.get("images") or []) if i)
            results.append(TavilyExtractResult(url=url, raw_content=content, images=images))
        return results
