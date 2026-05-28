from __future__ import annotations

from dataclasses import dataclass

from app.core.config import get_settings


@dataclass
class VideoExtraction:
    content: str
    transcript_source: str
    timestamp_start: float | None
    timestamp_end: float | None
    extraction_method: str
    extraction_confidence: float
    status: str
    metadata: dict


def extract_video_metadata(url: str) -> VideoExtraction:
    settings = get_settings()
    if not settings.enable_ytdlp_metadata:
        return VideoExtraction("", "metadata_only", None, None, "yt-dlp", 0.0, "disabled", {})
    try:
        import yt_dlp

        options = {
            "skip_download": not settings.enable_video_download,
            "quiet": True,
            "writesubtitles": False,
            "writeautomaticsub": False,
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=settings.enable_video_download)
        content = "\n".join(
            part
            for part in [info.get("title"), info.get("description")]
            if part
        )
        return VideoExtraction(content, "metadata_only", None, None, "yt-dlp", 0.45, "ok", info)
    except Exception as exc:
        return VideoExtraction("", "metadata_only", None, None, "yt-dlp", 0.0, "failed", {"error": str(exc)})

