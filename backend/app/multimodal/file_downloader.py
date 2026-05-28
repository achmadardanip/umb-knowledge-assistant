from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

from app.core.config import get_settings
from app.core.paths import project_path
from app.discovery.scope_validator import validate_url_scope
from app.discovery.url_normalizer import normalize_url
from app.multimodal.source_classifier import classify_source


logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    url: str
    status: str
    local_path: str | None = None
    sha256: str | None = None
    file_size_bytes: int | None = None
    mime_type: str | None = None
    source_type: str | None = None
    reason: str | None = None


def max_size_for_type(source_type: str) -> int:
    settings = get_settings()
    mb = {
        "pdf": settings.max_pdf_size_mb,
        "doc": settings.max_doc_size_mb,
        "docx": settings.max_doc_size_mb,
        "ppt": settings.max_ppt_size_mb,
        "pptx": settings.max_ppt_size_mb,
        "xls": settings.max_spreadsheet_size_mb,
        "xlsx": settings.max_spreadsheet_size_mb,
        "csv": settings.max_spreadsheet_size_mb,
        "image": settings.max_image_size_mb,
        "audio": settings.max_audio_size_mb,
        "video": settings.max_video_size_mb,
    }.get(source_type, 10)
    return mb * 1024 * 1024


def download_file(url: str, download_dir: str | Path | None = None, timeout: int | None = None) -> DownloadResult:
    settings = get_settings()
    request_timeout = timeout or settings.crawler_timeout_seconds
    normalized = normalize_url(url)
    decision = validate_url_scope(normalized, settings.allowed_domain)
    if not decision.is_allowed:
        return DownloadResult(normalized, "skipped", reason=decision.reason)

    try:
        head = requests.head(normalized, allow_redirects=True, timeout=request_timeout)
    except requests.RequestException as exc:
        return DownloadResult(normalized, "failed", reason=str(exc))

    classification = classify_source(normalized, head.headers.get("content-type"))
    max_size = max_size_for_type(classification.source_type)
    content_length = head.headers.get("content-length")
    if content_length and int(content_length) > max_size:
        return DownloadResult(
            normalized,
            "skipped",
            file_size_bytes=int(content_length),
            mime_type=classification.mime_type,
            source_type=classification.source_type,
            reason="file_too_large",
        )

    try:
        with requests.get(normalized, stream=True, timeout=request_timeout) as response:
            response.raise_for_status()
            hasher = hashlib.sha256()
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=1024 * 64):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_size:
                    return DownloadResult(normalized, "skipped", file_size_bytes=total, reason="file_too_large")
                hasher.update(chunk)
                chunks.append(chunk)
            digest = hasher.hexdigest()
            extension = classification.file_extension or Path(urlparse(normalized).path).suffix or ".bin"
            target_dir = Path(download_dir) if download_dir else project_path("data", "downloads", "raw")
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"{digest}{extension}"
            if not target.exists():
                target.write_bytes(b"".join(chunks))
            return DownloadResult(
                normalized,
                "downloaded",
                local_path=str(target),
                sha256=digest,
                file_size_bytes=total,
                mime_type=response.headers.get("content-type"),
                source_type=classification.source_type,
            )
    except requests.RequestException as exc:
        return DownloadResult(normalized, "failed", reason=str(exc))
