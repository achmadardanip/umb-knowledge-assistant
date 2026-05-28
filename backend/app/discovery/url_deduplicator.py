from __future__ import annotations

from app.discovery.url_normalizer import normalize_url


def deduplicate_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        if not url or not url.strip():
            continue
        normalized = normalize_url(url)
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result

