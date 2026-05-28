from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings


@dataclass
class OCRResult:
    content: str
    extraction_method: str
    extraction_confidence: float
    status: str
    warning: str | None = None


def extract_image_ocr(path: str | Path) -> OCRResult:
    settings = get_settings()
    if not settings.enable_ocr:
        return OCRResult("", settings.ocr_provider, 0.0, "disabled", "OCR is disabled by default.")
    try:
        import pytesseract
        from PIL import Image

        text = pytesseract.image_to_string(Image.open(path)).strip()
        confidence = 0.6 if text else 0.0
        return OCRResult(
            text,
            "tesseract",
            confidence,
            "ok" if text else "failed_no_text",
            "OCR text may contain errors.",
        )
    except Exception as exc:
        return OCRResult("", settings.ocr_provider, 0.0, "failed", str(exc))

