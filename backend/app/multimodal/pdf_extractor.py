from __future__ import annotations

from io import BytesIO
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings

@dataclass
class ExtractedPage:
    page_number: int
    content: str
    metadata: dict
    extraction_method: str
    extraction_confidence: float = 0.85


def _ocr_page(page) -> str:
    settings = get_settings()
    if not settings.enable_ocr:
        return ""
    try:
        import fitz
        import pytesseract
        from PIL import Image

        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        return pytesseract.image_to_string(
            Image.open(BytesIO(pixmap.tobytes("png"))),
            lang=settings.ocr_languages,
        ).strip()
    except Exception:
        return ""


def extract_pdf(path: str | Path) -> list[ExtractedPage]:
    target = Path(path)
    pages: list[ExtractedPage] = []
    try:
        import fitz  # PyMuPDF

        with fitz.open(target) as doc:
            for index, page in enumerate(doc, start=1):
                text = page.get_text("text").strip()
                extraction_method = "pymupdf"
                confidence = 0.85
                if not text:
                    text = _ocr_page(page)
                    extraction_method = "pymupdf+ocr"
                    confidence = 0.55
                if text:
                    pages.append(
                        ExtractedPage(
                            page_number=index,
                            content=text,
                            metadata={"title": doc.metadata.get("title") if doc.metadata else None},
                            extraction_method=extraction_method,
                            extraction_confidence=confidence,
                        )
                    )
        return pages
    except Exception:
        pass

    try:
        from pypdf import PdfReader

        reader = PdfReader(str(target))
        for index, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(
                    ExtractedPage(
                        page_number=index,
                        content=text,
                        metadata={"title": reader.metadata.title if reader.metadata else None},
                        extraction_method="pypdf",
                        extraction_confidence=0.75,
                    )
                )
    except Exception:
        return []
    return pages
