from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import urljoin

import requests

from app.discovery.scope_validator import validate_url_scope


def fetch_sitemap_urls(root_url: str, root_domain: str = "mercubuana.ac.id", timeout: int = 20) -> list[str]:
    sitemap_url = urljoin(root_url.rstrip("/") + "/", "sitemap.xml")
    try:
        response = requests.get(sitemap_url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException:
        return []
    try:
        root = ET.fromstring(response.text)
    except ET.ParseError:
        return []
    urls: list[str] = []
    for loc in root.iter():
        if loc.tag.endswith("loc") and loc.text:
            decision = validate_url_scope(loc.text.strip(), root_domain)
            if decision.is_allowed:
                urls.append(loc.text.strip())
    return urls

