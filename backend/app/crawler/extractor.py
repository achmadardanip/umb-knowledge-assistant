from __future__ import annotations

import hashlib

from app.multimodal.html_extractor import ExtractedHTML, extract_html


def extract_html_document(html: str, url: str) -> ExtractedHTML:
    return extract_html(html, url=url)


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()

