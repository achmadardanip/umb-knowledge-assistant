from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests

from app.crawler.extractor import extract_html_document
from app.discovery.robots_checker import can_fetch
from app.discovery.scope_validator import validate_url_scope
from app.discovery.url_normalizer import normalize_url


logger = logging.getLogger(__name__)


@dataclass
class CrawledPage:
    url: str
    title: str | None
    text: str
    html: str
    status_code: int
    metadata: dict
    links: list[str]


def fetch_page(url: str, timeout: int = 20) -> CrawledPage | None:
    headers = {"User-Agent": "UMBKnowledgeAssistant/0.1 (+public indexing; contact site owner)"}
    try:
        response = requests.get(url, timeout=timeout, headers=headers)
    except requests.RequestException as exc:
        logger.warning("Fetch failed for %s: %s", url, exc)
        return None
    if response.status_code >= 400:
        return CrawledPage(url, None, "", response.text, response.status_code, {}, [])
    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type and not urlparse(url).path.endswith((".html", ".htm", "/")):
        return CrawledPage(url, None, "", response.text, response.status_code, {"content_type": content_type}, [])
    extracted = extract_html_document(response.text, url)
    links = []
    for href in extracted.links:
        absolute = normalize_url(urljoin(url, href))
        links.append(absolute)
    return CrawledPage(
        url=url,
        title=extracted.title,
        text=extracted.text,
        html=response.text,
        status_code=response.status_code,
        metadata={**extracted.metadata, "headings": extracted.headings, "tables": extracted.tables},
        links=links,
    )


def crawl_bfs(
    start_url: str,
    *,
    root_domain: str = "mercubuana.ac.id",
    max_pages: int = 500,
    max_depth: int = 3,
    rate_limit: float = 2.0,
    respect_robots: bool = True,
) -> list[CrawledPage]:
    start = normalize_url(start_url)
    queue = deque([(start, 0)])
    seen = {start}
    pages: list[CrawledPage] = []
    delay = 1.0 / max(rate_limit, 0.1)
    while queue and len(pages) < max_pages:
        url, depth = queue.popleft()
        decision = validate_url_scope(url, root_domain)
        if not decision.is_allowed:
            continue
        if respect_robots and not can_fetch(url):
            continue
        page = fetch_page(url)
        time.sleep(delay)
        if not page:
            continue
        pages.append(page)
        if depth >= max_depth:
            continue
        for link in page.links:
            if link in seen:
                continue
            if validate_url_scope(link, root_domain).is_allowed:
                seen.add(link)
                queue.append((link, depth + 1))
    return pages

