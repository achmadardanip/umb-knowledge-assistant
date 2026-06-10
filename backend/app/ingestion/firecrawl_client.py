from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests

from app.core.config import get_settings


RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class FirecrawlConfigurationError(RuntimeError):
    pass


class FirecrawlAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, response_payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_payload = response_payload


@dataclass(frozen=True)
class FirecrawlDocument:
    url: str
    title: str | None
    markdown: str
    metadata: dict
    links: list[str]
    images: list[str]
    source_type: str
    status_code: int


class FirecrawlClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: int | None = None,
        max_retries: int | None = None,
        retry_backoff_seconds: float | None = None,
        session: requests.Session | None = None,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.firecrawl_api_key
        self.base_url = (base_url or settings.firecrawl_base_url).rstrip("/")
        # Self-hosted Firecrawl (USE_DB_AUTHENTICATION=false) needs no key; cloud does.
        if not self.api_key and "api.firecrawl.dev" in self.base_url:
            raise FirecrawlConfigurationError("FIRECRAWL_API_KEY is required for the Firecrawl cloud API.")
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else settings.firecrawl_timeout_seconds
        self.max_retries = max_retries if max_retries is not None else settings.firecrawl_max_retries
        self.retry_backoff_seconds = (
            retry_backoff_seconds if retry_backoff_seconds is not None else settings.firecrawl_retry_backoff_seconds
        )
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    def _request(self, method: str, path: str, *, json_payload: dict | None = None) -> dict:
        url = self._url(path)
        last_payload: Any = None
        for attempt in range(max(0, self.max_retries) + 1):
            try:
                response = self.session.request(
                    method,
                    url,
                    headers=self._headers(),
                    json=json_payload,
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise FirecrawlAPIError(
                        f"Firecrawl request failed after retries: {exc}",
                        response_payload=last_payload,
                    ) from exc
                time.sleep(max(self.retry_backoff_seconds * (2**attempt), 0.0))
                continue
            try:
                payload = response.json()
            except ValueError:
                payload = {"error": response.text[:500]}
            last_payload = payload
            if response.ok:
                return payload if isinstance(payload, dict) else {"data": payload}
            if response.status_code not in RETRYABLE_STATUS_CODES or attempt >= self.max_retries:
                message = None
                if isinstance(payload, dict):
                    message = payload.get("error") or payload.get("message")
                raise FirecrawlAPIError(
                    f"Firecrawl request failed with status {response.status_code}: {message or 'request failed'}",
                    status_code=response.status_code,
                    response_payload=payload,
                )
            retry_after = response.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after else self.retry_backoff_seconds * (2**attempt)
            except ValueError:
                delay = self.retry_backoff_seconds * (2**attempt)
            time.sleep(max(delay, 0.0))
        raise FirecrawlAPIError("Firecrawl request failed after retries.", response_payload=last_payload)

    def map_urls(
        self,
        url: str,
        *,
        limit: int,
        include_subdomains: bool = True,
        sitemap: str = "include",
    ) -> dict:
        return self._request(
            "POST",
            "/map",
            json_payload={
                "url": url,
                "sitemap": sitemap,
                "includeSubdomains": include_subdomains,
                "ignoreQueryParameters": True,
                "limit": limit,
                "timeout": self.timeout_seconds * 1000,
            },
        )

    def search_urls(self, query: str, *, limit: int, include_domains: list[str] | None = None) -> dict:
        payload = {
            "query": query,
            "limit": limit,
            "sources": ["web"],
            "ignoreInvalidURLs": True,
            "timeout": self.timeout_seconds * 1000,
        }
        if include_domains:
            payload["includeDomains"] = include_domains
        return self._request("POST", "/search", json_payload=payload)

    def start_crawl(
        self,
        url: str,
        *,
        limit: int,
        delay_seconds: float,
        max_concurrency: int,
        zero_data_retention: bool,
    ) -> dict:
        return self._request(
            "POST",
            "/crawl",
            json_payload={
                "url": url,
                "sitemap": "include",
                "ignoreQueryParameters": True,
                "limit": limit,
                "crawlEntireDomain": True,
                "allowExternalLinks": False,
                "allowSubdomains": True,
                "delay": delay_seconds,
                "maxConcurrency": max_concurrency,
                "zeroDataRetention": zero_data_retention,
                "scrapeOptions": _scrape_options(
                    zero_data_retention=zero_data_retention,
                    timeout_seconds=self.timeout_seconds,
                    include_zero_data_retention=False,
                ),
            },
        )

    def get_crawl_status(self, crawl_id_or_next_url: str) -> dict:
        path = crawl_id_or_next_url if crawl_id_or_next_url.startswith(("http://", "https://")) else f"/crawl/{crawl_id_or_next_url}"
        return self._request("GET", path)

    def scrape(self, url: str, *, zero_data_retention: bool) -> dict:
        payload = {"url": url, **_scrape_options(zero_data_retention=zero_data_retention, timeout_seconds=self.timeout_seconds)}
        return self._request("POST", "/scrape", json_payload=payload)


def _scrape_options(*, zero_data_retention: bool, timeout_seconds: int, include_zero_data_retention: bool = True) -> dict:
    options = {
        "formats": ["markdown", "links", "images"],
        "onlyMainContent": True,
        "timeout": timeout_seconds * 1000,
        "parsers": ["pdf"],
    }
    if include_zero_data_retention:
        options["zeroDataRetention"] = zero_data_retention
    return options


def documents_from_payload(payload: dict) -> list[FirecrawlDocument]:
    raw_docs = []
    if isinstance(payload.get("data"), list):
        raw_docs = payload["data"]
    elif isinstance(payload.get("data"), dict):
        data = payload["data"]
        if isinstance(data.get("web"), list):
            raw_docs = data["web"]
        else:
            raw_docs = [data]
    elif any(key in payload for key in ("markdown", "metadata", "links", "images")):
        raw_docs = [payload]

    documents: list[FirecrawlDocument] = []
    for item in raw_docs:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        url = str(metadata.get("sourceURL") or metadata.get("url") or item.get("url") or "").strip()
        markdown = str(item.get("markdown") or item.get("content") or "").strip()
        if not url or not markdown:
            continue
        source_type = _source_type_from_metadata(url, metadata)
        status_code = _status_code(metadata)
        documents.append(
            FirecrawlDocument(
                url=url,
                title=metadata.get("title") or item.get("title"),
                markdown=markdown,
                metadata=dict(metadata),
                links=_string_list(item.get("links")),
                images=_string_list(item.get("images")),
                source_type=source_type,
                status_code=status_code,
            )
        )
    return documents


def links_from_map_payload(payload: dict) -> list[dict]:
    links = payload.get("links") or []
    if not isinstance(links, list):
        return []
    normalized: list[dict] = []
    for item in links:
        if isinstance(item, str):
            normalized.append({"url": item})
        elif isinstance(item, dict) and item.get("url"):
            normalized.append(item)
    return normalized


def links_from_search_payload(payload: dict) -> list[dict]:
    data = payload.get("data") or {}
    if isinstance(data, list):
        web = data
    elif isinstance(data, dict):
        web = data.get("web") or []
    else:
        web = []
    if not isinstance(web, list):
        return []
    return [item for item in web if isinstance(item, dict) and item.get("url")]


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item:
            result.append(item)
        elif isinstance(item, dict):
            candidate = item.get("url") or item.get("imageUrl") or item.get("src")
            if candidate:
                result.append(str(candidate))
    return result


def _source_type_from_metadata(url: str, metadata: dict) -> str:
    content_type = str(metadata.get("contentType") or metadata.get("content_type") or "").lower()
    lowered_url = url.lower().split("?", 1)[0]
    if "pdf" in content_type or lowered_url.endswith(".pdf"):
        return "pdf"
    if any(lowered_url.endswith(ext) for ext in (".doc", ".docx")):
        return "docx"
    if any(lowered_url.endswith(ext) for ext in (".ppt", ".pptx")):
        return "pptx"
    if any(lowered_url.endswith(ext) for ext in (".xls", ".xlsx", ".csv")):
        return "spreadsheet"
    return "html"


def _status_code(metadata: dict) -> int:
    for key in ("statusCode", "pageStatusCode", "status_code"):
        value = metadata.get(key)
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 200
