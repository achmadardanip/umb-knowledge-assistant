from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings


@dataclass
class AudioTranscript:
    content: str
    transcript_source: str
    timestamp_start: float | None
    timestamp_end: float | None
    extraction_method: str
    extraction_confidence: float
    status: str


def extract_audio(path: str | Path) -> list[AudioTranscript]:
    settings = get_settings()
    if not settings.enable_asr:
        return [
            AudioTranscript(
                content="",
                transcript_source="metadata_only",
                timestamp_start=None,
                timestamp_end=None,
                extraction_method=settings.asr_provider,
                extraction_confidence=0.0,
                status="asr_disabled",
            )
        ]
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(settings.asr_model_size)
        segments, _info = model.transcribe(str(path))
        return [
            AudioTranscript(
                content=segment.text.strip(),
                transcript_source="asr",
                timestamp_start=float(segment.start),
                timestamp_end=float(segment.end),
                extraction_method="faster-whisper",
                extraction_confidence=0.6,
                status="ok",
            )
            for segment in segments
            if segment.text.strip()
        ]
    except Exception:
        return []

