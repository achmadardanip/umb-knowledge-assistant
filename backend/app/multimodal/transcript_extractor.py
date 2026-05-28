from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TranscriptSegment:
    content: str
    timestamp_start: float | None
    timestamp_end: float | None
    extraction_method: str
    extraction_confidence: float = 0.8


TIMESTAMP_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(?P<end>\d{2}:\d{2}:\d{2}[,.]\d{3})"
)


def _to_seconds(value: str) -> float:
    hours, minutes, rest = value.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(rest)


def extract_transcript(path: str | Path) -> list[TranscriptSegment]:
    target = Path(path)
    text = target.read_text(encoding="utf-8", errors="ignore")
    if target.suffix.lower() == ".txt":
        return [TranscriptSegment(text.strip(), None, None, "txt") if text.strip() else TranscriptSegment("", None, None, "txt", 0.0)]

    segments: list[TranscriptSegment] = []
    blocks = re.split(r"\n\s*\n", text)
    for block in blocks:
        match = TIMESTAMP_RE.search(block)
        lines = [line.strip() for line in block.splitlines() if line.strip() and "-->" not in line and not line.strip().isdigit()]
        content = " ".join(lines).strip()
        if not content:
            continue
        segments.append(
            TranscriptSegment(
                content=content,
                timestamp_start=_to_seconds(match.group("start")) if match else None,
                timestamp_end=_to_seconds(match.group("end")) if match else None,
                extraction_method="vtt/srt parser",
            )
        )
    return segments

