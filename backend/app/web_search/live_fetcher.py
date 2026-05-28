from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

from app.core.config import get_settings
from app.crawler.extractor import extract_html_document
from app.discovery.scope_validator import validate_url_scope
from app.discovery.url_normalizer import is_archive_url, normalize_url
from app.ingestion.chunker import chunk_text
from app.multimodal.document_extractor import extract_document
from app.multimodal.pdf_extractor import extract_pdf
from app.multimodal.presentation_extractor import extract_pptx
from app.multimodal.source_classifier import classify_source
from app.multimodal.spreadsheet_extractor import extract_spreadsheet
from app.multimodal.transcript_extractor import extract_transcript


@dataclass
class LiveContext:
    context: dict


MAX_HTML_BYTES = 5 * 1024 * 1024


def _max_bytes_for_type(source_type: str) -> int:
    settings = get_settings()
    limits_mb = {
        "pdf": settings.max_pdf_size_mb,
        "doc": settings.max_doc_size_mb,
        "docx": settings.max_doc_size_mb,
        "ppt": settings.max_ppt_size_mb,
        "pptx": settings.max_ppt_size_mb,
        "xls": settings.max_spreadsheet_size_mb,
        "xlsx": settings.max_spreadsheet_size_mb,
        "csv": settings.max_spreadsheet_size_mb,
        "transcript": settings.max_doc_size_mb,
        "html": 5,
    }
    return limits_mb.get(source_type, 5) * 1024 * 1024


def _base_metadata(url: str, title: str | None, source_type: str, method: str, confidence: float) -> dict:
    parsed = urlparse(url)
    return {
        "url": url,
        "hostname": (parsed.hostname or "").lower(),
        "path": parsed.path or "/",
        "title": title or url,
        "source_type": source_type,
        "discovery_source": "live_web_search",
        "extraction_method": method,
        "extraction_confidence": confidence,
    }


def _contexts_from_text(
    *,
    text: str,
    url: str,
    title: str | None,
    source_type: str,
    method: str,
    confidence: float,
    score: float,
    metadata: dict | None = None,
) -> list[dict]:
    base = _base_metadata(url, title, source_type, method, confidence)
    base.update(metadata or {})
    chunks = chunk_text(text, metadata=base, chunk_size=get_settings().chunk_size, overlap=get_settings().chunk_overlap)
    contexts: list[dict] = []
    for chunk in chunks:
        contexts.append(
            {
                "chunk_id": None,
                "source_id": None,
                "asset_id": None,
                "segment_id": None,
                "chunk_text": chunk.chunk_text,
                "url": url,
                "title": title or url,
                "score": score,
                "hostname": base["hostname"],
                "discovery_source": "live_web_search",
                "source_type": source_type,
                "page_number": chunk.page_number,
                "slide_number": chunk.slide_number,
                "sheet_name": chunk.sheet_name,
                "row_range": chunk.row_range,
                "timestamp_start": chunk.timestamp_start,
                "timestamp_end": chunk.timestamp_end,
                "extraction_method": method,
                "extraction_confidence": confidence,
                "metadata": chunk.metadata,
            }
        )
    return contexts


def _extract_file_contexts(path: Path, url: str, source_type: str, title: str | None, score: float) -> list[dict]:
    if source_type == "pdf":
        contexts: list[dict] = []
        for page in extract_pdf(path):
            contexts.extend(
                _contexts_from_text(
                    text=page.content,
                    url=url,
                    title=title or page.metadata.get("title"),
                    source_type="pdf",
                    method=page.extraction_method,
                    confidence=page.extraction_confidence,
                    score=score,
                    metadata={"page_number": page.page_number},
                )
            )
        return contexts
    if source_type in {"docx", "doc"}:
        extracted = extract_document(path, source_type)
        return _contexts_from_text(
            text=extracted.content,
            url=url,
            title=title,
            source_type=source_type,
            method=extracted.extraction_method,
            confidence=extracted.extraction_confidence,
            score=score,
        )
    if source_type in {"pptx", "ppt"}:
        contexts = []
        for slide in extract_pptx(path):
            contexts.extend(
                _contexts_from_text(
                    text=slide.content,
                    url=url,
                    title=title or slide.slide_title,
                    source_type="pptx",
                    method=slide.extraction_method,
                    confidence=slide.extraction_confidence,
                    score=score,
                    metadata={"slide_number": slide.slide_number},
                )
            )
        return contexts
    if source_type in {"xls", "xlsx", "csv"}:
        contexts = []
        for sheet in extract_spreadsheet(path, source_type):
            contexts.extend(
                _contexts_from_text(
                    text=sheet.content,
                    url=url,
                    title=title,
                    source_type="spreadsheet",
                    method=sheet.extraction_method,
                    confidence=sheet.extraction_confidence,
                    score=score,
                    metadata={"sheet_name": sheet.sheet_name, "row_range": sheet.row_range},
                )
            )
        return contexts
    if source_type == "transcript":
        contexts = []
        for segment in extract_transcript(path):
            contexts.extend(
                _contexts_from_text(
                    text=segment.content,
                    url=url,
                    title=title,
                    source_type="transcript",
                    method=segment.extraction_method,
                    confidence=segment.extraction_confidence,
                    score=score,
                    metadata={"timestamp_start": segment.timestamp_start, "timestamp_end": segment.timestamp_end},
                )
            )
        return contexts
    return []


def fetch_live_contexts(url: str, *, title: str | None = None, score: float = 0.5) -> list[dict]:
    settings = get_settings()
    normalized = normalize_url(url)
    if is_archive_url(normalized) or not validate_url_scope(normalized, settings.web_search_strict_domain).is_allowed:
        return []
    response = requests.get(
        normalized,
        headers={"User-Agent": "UMBKnowledgeAssistant/0.1 (+public-source-indexing)"},
        timeout=settings.web_search_timeout_seconds,
        allow_redirects=True,
    )
    response.raise_for_status()
    final_url = normalize_url(response.url)
    if is_archive_url(final_url) or not validate_url_scope(final_url, settings.web_search_strict_domain).is_allowed:
        return []
    content_type = response.headers.get("content-type")
    classification = classify_source(final_url, content_type)
    source_type = classification.source_type
    if source_type == "unknown":
        return []
    content_length = int(response.headers.get("content-length") or "0")
    max_bytes = _max_bytes_for_type(source_type)
    if content_length and content_length > max_bytes:
        return []
    content = response.content
    if len(content) > max(max_bytes, MAX_HTML_BYTES):
        return []

    if source_type == "html":
        extracted = extract_html_document(response.text, final_url)
        return _contexts_from_text(
            text=extracted.text,
            url=final_url,
            title=extracted.title or title,
            source_type="html",
            method=extracted.extraction_method,
            confidence=extracted.extraction_confidence,
            score=score,
        )

    suffix = classification.file_extension or Path(urlparse(final_url).path).suffix or ".bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    try:
        return _extract_file_contexts(temp_path, final_url, source_type, title, score)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
