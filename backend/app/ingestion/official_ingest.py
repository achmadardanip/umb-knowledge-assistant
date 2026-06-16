"""
Phase-7 official-source ingestion (HTML + PDF) into the configured KB.

Thin wrapper over the existing ``upsert_source_document`` (which already de-dups via
content hash, chunks, prunes metadata, embeds, and stores in the retriever's schema).
Adds the two things the plan requires and the base pipeline lacks:

  1. Content-type detection (URL suffix + HTTP HEAD) → HTML vs PDF vs skip.
  2. PDF text extraction via PyMuPDF (fitz, preferred) with a pypdf fallback.

Every stored chunk keeps provenance (source_url, hostname, title, source_type,
authority_tier, discovery_source). Only official ``*.mercubuana.ac.id`` URLs are accepted.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import requests

from app.discovery.scope_validator import validate_url_scope
from app.ingestion.pipeline import upsert_source_document
from app.trust.authority import host_authority

logger = logging.getLogger(__name__)
ROOT_DOMAIN = "mercubuana.ac.id"
_UA = {"User-Agent": "UMB-KnowledgeAssistant/1.0 (+official ingestion)"}


def authority_tier(hostname: str) -> int:
    """1=root/admissions/sia/sso, 2=bti/baa/support, 3=faculty, 4=library, 5=archive."""
    h = (hostname or "").lower()
    sub = h.replace(f".{ROOT_DOMAIN}", "") if h.endswith(ROOT_DOMAIN) else h
    if sub in {"", "www", "mercubuana.ac.id", "pmb", "pendaftaran", "sia", "sso"}:
        return 1
    if sub in {"bti", "baa", "support", "ditmawa", "kemahasiswaan"}:
        return 2
    if sub in {"repository", "publikasi", "journal", "jurnal", "proceeding", "digilib", "ejournal"}:
        return 5
    if sub in {"lib", "library", "perpustakaan"}:
        return 4
    return 3  # faculty / other official subdomains


def detect_content_type(url: str, *, timeout: int = 15) -> str:
    """Return 'pdf' | 'html' | 'skip'."""
    path = urlparse(url).path.lower()
    if path.endswith(".pdf"):
        return "pdf"
    if any(path.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".zip", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx")):
        return "skip"
    try:
        resp = requests.head(url, headers=_UA, timeout=timeout, allow_redirects=True)
        ctype = (resp.headers.get("Content-Type") or "").lower()
    except Exception:
        return "html"  # default; extraction will validate
    if "application/pdf" in ctype:
        return "pdf"
    if "text/html" in ctype or not ctype:
        return "html"
    return "skip"


def extract_pdf(url: str, *, timeout: int = 60) -> tuple[str, str | None, int]:
    """Extract text from a PDF (PyMuPDF preferred, pypdf fallback). Returns (text, title, pages)."""
    resp = requests.get(url, headers=_UA, timeout=timeout)
    resp.raise_for_status()
    data = resp.content
    # Preferred: PyMuPDF (fitz)
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(stream=data, filetype="pdf")
        parts = []
        for i, page in enumerate(doc, start=1):
            txt = (page.get_text() or "").strip()
            if txt:
                parts.append(f"[hal. {i}]\n{txt}")
        title = (doc.metadata or {}).get("title") or None
        n = doc.page_count
        doc.close()
        return "\n\n".join(parts), title, n
    except Exception as exc:
        logger.info("PyMuPDF failed for %s (%s); trying pypdf", url, exc)
    # Fallback: pypdf
    try:
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        parts = [(p.extract_text() or "").strip() for p in reader.pages]
        text = "\n\n".join(f"[hal. {i}]\n{t}" for i, t in enumerate(parts, start=1) if t)
        title = (reader.metadata or {}).title if reader.metadata else None
        return text, title, len(reader.pages)
    except Exception as exc:
        logger.warning("PDF extraction failed for %s: %s", url, exc)
        return "", None, 0


def ingest_urls(db, urls: list[str], *, discovery_source: str = "phase7_official", client=None) -> dict:
    """Ingest official HTML + PDF URLs into the KB. Returns ingestion stats."""
    from app.web_search.tavily_client import TavilyClient

    client = client or TavilyClient()
    client.ensure_configured()

    stats = {"requested": len(urls), "ingested": 0, "skipped": 0, "failed": 0,
             "chunks_added": 0, "by_type": {"html": 0, "pdf": 0}, "errors": []}

    for url in urls:
        if not validate_url_scope(url, ROOT_DOMAIN).is_allowed:
            stats["skipped"] += 1
            continue
        hostname = (urlparse(url).hostname or "").lower()
        tier = authority_tier(hostname)
        if tier >= 5:  # archive/repository — reject during ingestion
            stats["skipped"] += 1
            continue
        ctype = detect_content_type(url)
        if ctype == "skip":
            stats["skipped"] += 1
            continue
        try:
            if ctype == "pdf":
                text, title, pages = extract_pdf(url)
                meta = {"authority_tier": tier, "page_count": pages}
                src_type, method = "pdf", "pymupdf"
            else:
                results = client.extract([url])
                if not results or not results[0].raw_content:
                    stats["skipped"] += 1
                    continue
                text, title = results[0].raw_content, None
                meta = {"authority_tier": tier}
                src_type, method = "html", "tavily_extract"
            if not text or len(text.split()) < 25:
                stats["skipped"] += 1
                continue
            n_chunks = upsert_source_document(
                db, url=url, text=text, title=title, metadata=meta, http_status=200,
                discovery_source=discovery_source, source_type=src_type, extraction_method=method,
            )
            db.commit()
            stats["ingested"] += 1
            stats["by_type"][src_type] += 1
            stats["chunks_added"] += int(n_chunks or 0)
        except Exception as exc:
            db.rollback()
            stats["failed"] += 1
            if len(stats["errors"]) < 20:
                stats["errors"].append({"url": url, "error": str(exc)[:160]})
    return stats
