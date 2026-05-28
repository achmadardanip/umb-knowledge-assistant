from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


SOURCE_EXTENSIONS = {
    ".html": "html",
    ".htm": "html",
    ".pdf": "pdf",
    ".doc": "doc",
    ".docx": "docx",
    ".ppt": "ppt",
    ".pptx": "pptx",
    ".xls": "xls",
    ".xlsx": "xlsx",
    ".csv": "csv",
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".webp": "image",
    ".mp3": "audio",
    ".wav": "audio",
    ".m4a": "audio",
    ".mp4": "video",
    ".webm": "video",
    ".mov": "video",
    ".vtt": "transcript",
    ".srt": "transcript",
    ".txt": "transcript",
}


@dataclass(frozen=True)
class SourceClassification:
    source_type: str
    mime_type: str | None = None
    file_extension: str | None = None
    confidence: float = 0.6


def classify_source(url: str, content_type: str | None = None, local_path: str | None = None) -> SourceClassification:
    mime = (content_type or "").split(";")[0].strip().lower() or None
    path = local_path or urlparse(url).path
    extension = Path(path).suffix.lower()
    lowered_path = path.lower()

    if extension in SOURCE_EXTENSIONS:
        return SourceClassification(SOURCE_EXTENSIONS[extension], mime or mimetypes.guess_type(path)[0], extension, 0.9)

    if "/article/download/" in lowered_path:
        return SourceClassification("pdf", mime or "application/pdf", ".pdf", 0.65)

    if mime:
        if mime in {"text/html", "application/xhtml+xml"}:
            return SourceClassification("html", mime, extension or None, 0.85)
        if mime == "application/pdf":
            return SourceClassification("pdf", mime, extension or ".pdf", 0.9)
        if mime in {"text/csv", "application/csv"}:
            return SourceClassification("csv", mime, extension or ".csv", 0.85)
        if mime.startswith("image/"):
            return SourceClassification("image", mime, extension or None, 0.85)
        if mime.startswith("audio/"):
            return SourceClassification("audio", mime, extension or None, 0.85)
        if mime.startswith("video/"):
            return SourceClassification("video", mime, extension or None, 0.85)
        if "wordprocessingml" in mime:
            return SourceClassification("docx", mime, ".docx", 0.9)
        if "presentationml" in mime:
            return SourceClassification("pptx", mime, ".pptx", 0.9)
        if "spreadsheetml" in mime:
            return SourceClassification("xlsx", mime, ".xlsx", 0.9)
        if mime.startswith("text/"):
            return SourceClassification("html" if mime == "text/html" else "transcript", mime, extension or None, 0.55)

    return SourceClassification("unknown", mime, extension or None, 0.2)
