from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import deque
from urllib.parse import urljoin

import requests

from app.discovery.scope_validator import validate_url_scope


def _loc_values(xml_text: str) -> tuple[str, list[str]]:
    root = ET.fromstring(xml_text)
    root_kind = "sitemapindex" if root.tag.endswith("sitemapindex") else "urlset" if root.tag.endswith("urlset") else "unknown"
    return root_kind, [node.text.strip() for node in root.iter() if node.tag.endswith("loc") and node.text and node.text.strip()]


def _robots_sitemaps(root_url: str, timeout: int) -> list[str]:
    robots_url = urljoin(root_url.rstrip("/") + "/", "robots.txt")
    try:
        response = requests.get(robots_url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException:
        return []
    sitemaps = []
    for line in response.text.splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == "sitemap" and value.strip():
            sitemaps.append(value.strip())
    return sitemaps


def fetch_sitemap_urls(root_url: str, root_domain: str = "mercubuana.ac.id", timeout: int = 20, max_sitemaps: int = 100, max_urls: int = 100_000) -> list[str]:
    sitemap_candidates = [*_robots_sitemaps(root_url, timeout), urljoin(root_url.rstrip("/") + "/", "sitemap.xml")]
    queue = deque(sitemap_candidates)
    seen_sitemaps: set[str] = set()
    urls: list[str] = []
    seen_urls: set[str] = set()

    while queue and len(seen_sitemaps) < max_sitemaps and len(urls) < max_urls:
        sitemap_url = queue.popleft()
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)
        try:
            response = requests.get(sitemap_url, timeout=timeout)
            response.raise_for_status()
            root_kind, locs = _loc_values(response.text)
        except (requests.RequestException, ET.ParseError):
            continue

        for loc in locs:
            decision = validate_url_scope(loc, root_domain)
            if not decision.is_allowed:
                continue
            if root_kind == "sitemapindex" or loc.lower().split("?", 1)[0].endswith(".xml"):
                if loc not in seen_sitemaps:
                    queue.append(loc)
                continue
            if loc not in seen_urls:
                seen_urls.add(loc)
                urls.append(loc)
            if len(urls) >= max_urls:
                break
    return urls
