from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExtractedPage:
    page_number: int
    content: str
    metadata: dict
    extraction_method: str
    extraction_confidence: float = 0.85


def extract_pdf(path: str | Path) -> list[ExtractedPage]:
    target = Path(path)
    pages: list[ExtractedPage] = []
    try:
        import fitz  # PyMuPDF

        with fitz.open(target) as doc:
            for index, page in enumerate(doc, start=1):
                text = page.get_text("text").strip()
                if text:
                    pages.append(
                        ExtractedPage(
                            page_number=index,
                            content=text,
                            metadata={"title": doc.metadata.get("title") if doc.metadata else None},
                            extraction_method="pymupdf",
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

