from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from app.multimodal.metadata_extractor import extract_html_metadata
from app.multimodal.table_extractor import extract_html_tables


@dataclass
class ExtractedHTML:
    title: str | None
    text: str
    headings: list[str]
    links: list[str]
    metadata: dict
    tables: list[dict]
    extraction_method: str = "trafilatura+beautifulsoup"
    extraction_confidence: float = 0.9


def clean_text(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text or "")).strip()


def extract_html(html: str, url: str | None = None) -> ExtractedHTML:
    metadata = extract_html_metadata(html)
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    extracted = ""
    try:
        import trafilatura

        extracted = trafilatura.extract(html, url=url, include_tables=True, include_links=False) or ""
    except Exception:
        extracted = ""
    if not extracted:
        main = soup.find("main") or soup.body or soup
        extracted = main.get_text("\n", strip=True)

    headings = [h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2", "h3"]) if h.get_text(strip=True)]
    links = [a.get("href") for a in soup.find_all("a") if a.get("href")]
    return ExtractedHTML(
        title=metadata.get("title"),
        text=clean_text(extracted),
        headings=headings[:50],
        links=links[:300],
        metadata=metadata,
        tables=extract_html_tables(html),
    )

