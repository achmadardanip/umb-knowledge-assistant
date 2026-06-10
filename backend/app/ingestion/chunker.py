from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TextChunk:
    chunk_text: str
    chunk_index: int
    token_count: int
    metadata: dict[str, Any]
    source_type: str | None = None
    page_number: int | None = None
    slide_number: int | None = None
    sheet_name: str | None = None
    row_range: str | None = None
    timestamp_start: float | None = None
    timestamp_end: float | None = None
    extraction_method: str | None = None
    extraction_confidence: float | None = None


def approximate_tokens(text: str) -> list[str]:
    return (text or "").split()


def _chunk_words(words: list[str], chunk_size: int, overlap: int) -> list[list[str]]:
    if not words:
        return []
    chunks: list[list[str]] = []
    step = max(chunk_size - overlap, 1)
    for start in range(0, len(words), step):
        current = words[start : start + chunk_size]
        if len(current) < 25 and chunks:
            chunks[-1].extend(current)
            break
        chunks.append(current)
        if start + chunk_size >= len(words):
            break
    return chunks


def chunk_text(
    text: str,
    *,
    metadata: dict[str, Any] | None = None,
    chunk_size: int = 900,
    overlap: int = 120,
    min_words: int = 25,
) -> list[TextChunk]:
    metadata = dict(metadata or {})
    source_type = metadata.get("source_type") or "html"
    if source_type == "html":
        chunk_size = min(max(chunk_size, 700), 1000)
    words = approximate_tokens(text)
    if len(words) < min_words:
        return []
    title = metadata.get("title")
    heading = metadata.get("section_heading")
    prefix = " - ".join(part for part in [title, heading] if part)
    chunks: list[TextChunk] = []
    for index, word_chunk in enumerate(_chunk_words(words, chunk_size, overlap)):
        content = " ".join(word_chunk).strip()
        if prefix and not content.startswith(prefix):
            content = f"{prefix}\n{content}"
        chunk_metadata = dict(metadata)
        chunk_metadata["chunk_index"] = index
        chunks.append(
            TextChunk(
                chunk_text=content,
                chunk_index=index,
                token_count=len(word_chunk),
                metadata=chunk_metadata,
                source_type=source_type,
                page_number=metadata.get("page_number"),
                slide_number=metadata.get("slide_number"),
                sheet_name=metadata.get("sheet_name"),
                row_range=metadata.get("row_range"),
                timestamp_start=metadata.get("timestamp_start"),
                timestamp_end=metadata.get("timestamp_end"),
                extraction_method=metadata.get("extraction_method"),
                extraction_confidence=metadata.get("extraction_confidence"),
            )
        )
    return chunks


def chunk_segments(
    segments: list[dict[str, Any]],
    *,
    chunk_size: int = 900,
    overlap: int = 120,
) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    for segment in segments:
        content = segment.get("content") or ""
        metadata = {key: value for key, value in segment.items() if key != "content"}
        chunks.extend(chunk_text(content, metadata=metadata, chunk_size=chunk_size, overlap=overlap))
    return chunks

