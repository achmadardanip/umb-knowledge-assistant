from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.core.config import get_settings
from app.core.paths import project_path
from app.crawler.extractor import content_hash
from app.db.database import get_session_local
from app.db.models import Chunk, DiscoveredURL, ExtractedSegment, Source, SourceAsset, utcnow
from app.discovery.scope_validator import validate_url_scope
from app.discovery.url_normalizer import normalize_url
from app.ingestion.embedder import EmbeddingConfigurationError, get_embedder
from app.ingestion.embedding_store import ensure_embedding_storage, store_chunk_embedding, validate_embedding_batch
from app.ingestion.chunker import chunk_segments
from app.multimodal.audio_extractor import extract_audio
from app.multimodal.document_extractor import extract_document
from app.multimodal.extraction_quality import should_index
from app.multimodal.file_downloader import download_file
from app.multimodal.html_extractor import extract_html
from app.multimodal.image_ocr_extractor import extract_image_ocr
from app.multimodal.pdf_extractor import extract_pdf
from app.multimodal.presentation_extractor import extract_pptx
from app.multimodal.source_classifier import classify_source
from app.multimodal.spreadsheet_extractor import extract_spreadsheet
from app.multimodal.transcript_extractor import extract_transcript
from app.multimodal.video_extractor import extract_video_metadata


DISCOVERY_URLS = project_path("data", "discovery", "urls_filtered.txt")
REPORT_PATH = project_path("data", "multimodal", "extraction_report.json")
CLASSIFIED_PATH = project_path("data", "multimodal", "classified_assets.json")
DISCOVERY_REPORT = project_path("data", "discovery", "discovery_report.json")
logger = logging.getLogger(__name__)


def _load_urls() -> list[str]:
    if not DISCOVERY_URLS.exists():
        return []
    return [line.strip() for line in DISCOVERY_URLS.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_report(report: dict) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def _update_discovery_report(report_update: dict) -> None:
    report = {}
    if DISCOVERY_REPORT.exists():
        try:
            report = json.loads(DISCOVERY_REPORT.read_text(encoding="utf-8"))
        except Exception:
            report = {}
    report.update(report_update)
    DISCOVERY_REPORT.parent.mkdir(parents=True, exist_ok=True)
    DISCOVERY_REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def classify_discovered() -> dict:
    settings = get_settings()
    items = []
    for url in _load_urls():
        normalized = normalize_url(url)
        decision = validate_url_scope(normalized, settings.allowed_domain)
        if not decision.is_allowed:
            continue
        classification = classify_source(normalized)
        parsed = urlparse(normalized)
        items.append(
            {
                "url": normalized,
                "hostname": parsed.hostname,
                "path": parsed.path,
                "source_type": classification.source_type,
                "mime_type": classification.mime_type,
                "file_extension": classification.file_extension,
                "confidence": classification.confidence,
            }
        )
    CLASSIFIED_PATH.parent.mkdir(parents=True, exist_ok=True)
    CLASSIFIED_PATH.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    report = {"classified_assets": len(items), "by_type": {}}
    for item in items:
        report["by_type"][item["source_type"]] = report["by_type"].get(item["source_type"], 0) + 1
    _write_report(report)
    return report


def _load_classified() -> list[dict]:
    if not CLASSIFIED_PATH.exists():
        classify_discovered()
    try:
        return json.loads(CLASSIFIED_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def download_assets(max_files: int = 200) -> dict:
    items = [item for item in _load_classified() if item.get("source_type") not in {"html", "unknown"}]
    results = []
    selected = items if max_files <= 0 else items[:max_files]
    for item in selected:
        result = download_file(item["url"])
        results.append(result.__dict__)
    report = {
        "downloaded": sum(1 for r in results if r["status"] == "downloaded"),
        "download_failed": sum(1 for r in results if r["status"] != "downloaded"),
        "candidate_assets": len(items),
        "results": results,
    }
    _write_report(report)
    _update_discovery_report({"downloaded_assets_total": report["downloaded"], "asset_failed_total": report["download_failed"]})
    return report


def extract_asset(local_path: str, source_type: str, url: str) -> list[dict]:
    segments: list[dict] = []
    if source_type == "pdf":
        for page in extract_pdf(local_path):
            segments.append({"content": page.content, "page_number": page.page_number, "source_type": "pdf", "extraction_method": page.extraction_method, "extraction_confidence": page.extraction_confidence})
    elif source_type in {"doc", "docx"}:
        doc = extract_document(local_path, source_type)
        segments.append({"content": doc.content, "source_type": source_type, "extraction_method": doc.extraction_method, "extraction_confidence": doc.extraction_confidence})
    elif source_type == "pptx":
        for slide in extract_pptx(local_path):
            segments.append({"content": slide.content, "slide_number": slide.slide_number, "source_type": "pptx", "extraction_method": slide.extraction_method, "extraction_confidence": slide.extraction_confidence})
    elif source_type in {"xls", "xlsx", "csv"}:
        for sheet in extract_spreadsheet(local_path, source_type):
            segments.append({"content": sheet.content, "sheet_name": sheet.sheet_name, "row_range": sheet.row_range, "source_type": "spreadsheet", "extraction_method": sheet.extraction_method, "extraction_confidence": sheet.extraction_confidence})
    elif source_type == "image":
        ocr = extract_image_ocr(local_path)
        segments.append({"content": ocr.content, "source_type": "image", "extraction_method": ocr.extraction_method, "extraction_confidence": ocr.extraction_confidence, "warning": ocr.warning})
    elif source_type == "audio":
        for segment in extract_audio(local_path):
            segments.append({"content": segment.content, "source_type": "audio", "timestamp_start": segment.timestamp_start, "timestamp_end": segment.timestamp_end, "extraction_method": segment.extraction_method, "extraction_confidence": segment.extraction_confidence})
    elif source_type == "video":
        video = extract_video_metadata(url)
        segments.append({"content": video.content, "source_type": "video", "timestamp_start": video.timestamp_start, "timestamp_end": video.timestamp_end, "extraction_method": video.extraction_method, "extraction_confidence": video.extraction_confidence})
    elif source_type == "transcript":
        for segment in extract_transcript(local_path):
            segments.append({"content": segment.content, "source_type": "transcript", "timestamp_start": segment.timestamp_start, "timestamp_end": segment.timestamp_end, "extraction_method": segment.extraction_method, "extraction_confidence": segment.extraction_confidence})
    return segments


def extract_assets() -> dict:
    if not REPORT_PATH.exists():
        return {"extracted_segments": 0, "chunks": 0, "reason": "no_download_report"}
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    results = payload.get("results", [])
    extracted = []
    settings = get_settings()
    for result in results:
        if result.get("status") != "downloaded" or not result.get("local_path"):
            continue
        segments = extract_asset(result["local_path"], result.get("source_type") or "unknown", result["url"])
        for segment in segments:
            if should_index(segment.get("content", ""), settings.multimodal_min_extraction_chars, segment.get("extraction_confidence")):
                segment["url"] = result["url"]
                extracted.append(segment)
    chunks = chunk_segments(extracted, chunk_size=settings.chunk_size, overlap=settings.chunk_overlap)
    report = {"extracted_segments": len(extracted), "chunks": len(chunks), "segments": extracted}
    _write_report(report)
    _update_discovery_report({"extracted_segments_total": len(extracted), "asset_chunks_total": len(chunks)})
    return report


def index_assets() -> dict:
    if not REPORT_PATH.exists():
        return {"indexed_chunks": 0, "reason": "no_extraction_report"}
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    segments = payload.get("segments", [])
    if not segments:
        return {"indexed_chunks": 0, "reason": "no_segments"}

    settings = get_settings()
    session_factory = get_session_local()
    try:
        embedder = get_embedder()
    except EmbeddingConfigurationError:
        embedder = None

    indexed_chunks = 0
    indexed_segments = 0
    indexed_assets = 0
    with session_factory() as db:
        for url in sorted({segment.get("url") for segment in segments if segment.get("url")}):
            normalized_url = normalize_url(url)
            decision = validate_url_scope(normalized_url, settings.allowed_domain)
            if not decision.is_allowed:
                continue
            parsed = urlparse(normalized_url)
            hostname = (parsed.hostname or "").lower()
            path = parsed.path or "/"
            title = unquote(Path(path).name) or normalized_url
            related_segments = [segment for segment in segments if segment.get("url") == url]
            source_type = related_segments[0].get("source_type") if related_segments else "unknown"
            combined_text = "\n\n".join(segment.get("content", "") for segment in related_segments)

            source = db.query(Source).filter(Source.url == normalized_url).first()
            if source is None:
                source = Source(url=normalized_url)
                db.add(source)
                db.flush()
            source.title = title
            source.hostname = hostname
            source.path = path
            source.content_hash = content_hash(combined_text)
            source.status = "indexed" if combined_text else "empty"
            source.discovery_source = source.discovery_source or "multimodal"
            source.http_status = source.http_status or 200

            discovered = db.query(DiscoveredURL).filter(DiscoveredURL.normalized_url == normalized_url).first()
            asset = db.query(SourceAsset).filter(SourceAsset.normalized_url == normalized_url).first()
            if asset and asset.extraction_status == "indexed":
                continue
            if asset is None:
                asset = SourceAsset(url=normalized_url, normalized_url=normalized_url)
                db.add(asset)
                db.flush()
            asset.source_id = source.id
            asset.discovered_url_id = discovered.id if discovered else None
            asset.hostname = hostname
            asset.path = path
            asset.source_type = source_type
            asset.file_extension = Path(path).suffix.lower() or None
            asset.download_status = "downloaded"
            asset.extraction_status = "indexed"
            asset.extraction_method = related_segments[0].get("extraction_method") if related_segments else None
            asset.extraction_confidence = related_segments[0].get("extraction_confidence") if related_segments else None
            asset.extracted_at = utcnow()
            asset.meta = {**(asset.meta or {}), "title": title, "source_url": normalized_url}

            for segment_index, segment in enumerate(related_segments):
                extracted = ExtractedSegment(
                    asset_id=asset.id,
                    source_id=source.id,
                    segment_type=segment.get("source_type") or source_type,
                    content=segment.get("content", ""),
                    page_number=segment.get("page_number"),
                    slide_number=segment.get("slide_number"),
                    sheet_name=segment.get("sheet_name"),
                    row_range=segment.get("row_range"),
                    timestamp_start=segment.get("timestamp_start"),
                    timestamp_end=segment.get("timestamp_end"),
                    extraction_confidence=segment.get("extraction_confidence"),
                    meta={
                        "url": normalized_url,
                        "hostname": hostname,
                        "path": path,
                        "title": title,
                        "source_type": segment.get("source_type") or source_type,
                        "extraction_method": segment.get("extraction_method"),
                        "segment_index": segment_index,
                    },
                )
                db.add(extracted)
                db.flush()
                metadata = {
                    **extracted.meta,
                    "page_number": extracted.page_number,
                    "slide_number": extracted.slide_number,
                    "sheet_name": extracted.sheet_name,
                    "row_range": extracted.row_range,
                    "timestamp_start": extracted.timestamp_start,
                    "timestamp_end": extracted.timestamp_end,
                    "extraction_confidence": extracted.extraction_confidence,
                }
                chunks = chunk_segments(
                    [{**metadata, "content": extracted.content}],
                    chunk_size=settings.chunk_size,
                    overlap=settings.chunk_overlap,
                )
                embeddings = [None] * len(chunks)
                if embedder and chunks:
                    try:
                        embeddings = embedder.embed_texts([chunk.chunk_text for chunk in chunks])
                        validate_embedding_batch(embedder, embeddings, len(chunks))
                        ensure_embedding_storage(db, embedder)
                    except Exception as exc:
                        logger.warning(
                            "Embedding failed for %s; indexing keyword-only asset chunks: %s",
                            normalized_url,
                            exc,
                        )
                        embeddings = [None] * len(chunks)
                for chunk, embedding in zip(chunks, embeddings, strict=True):
                    chunk_row = Chunk(
                        source_id=source.id,
                        asset_id=asset.id,
                        segment_id=extracted.id,
                        chunk_text=chunk.chunk_text,
                        chunk_index=chunk.chunk_index,
                        token_count=chunk.token_count,
                        meta=chunk.metadata,
                        source_type=chunk.source_type,
                        page_number=chunk.page_number,
                        slide_number=chunk.slide_number,
                        sheet_name=chunk.sheet_name,
                        row_range=chunk.row_range,
                        timestamp_start=chunk.timestamp_start,
                        timestamp_end=chunk.timestamp_end,
                        extraction_method=chunk.extraction_method,
                        extraction_confidence=chunk.extraction_confidence,
                    )
                    db.add(chunk_row)
                    if embedding is not None:
                        store_chunk_embedding(db, chunk_row, embedding, embedder)
                    indexed_chunks += 1
                indexed_segments += 1
            indexed_assets += 1
            db.commit()
    report = {"indexed_assets": indexed_assets, "indexed_segments": indexed_segments, "indexed_chunks": indexed_chunks}
    _update_discovery_report({"indexed_assets_total": indexed_assets, "extracted_segments_total": indexed_segments})
    return report


def run_all(max_files: int = 200) -> dict:
    classify_report = classify_discovered()
    download_report = download_assets(max_files=max_files)
    extract_report = extract_assets()
    index_report = index_assets()
    return {
        "classified_assets": classify_report.get("classified_assets", 0),
        "downloaded_assets": download_report.get("downloaded", 0),
        "extracted_segments": extract_report.get("extracted_segments", 0),
        "indexed_assets": index_report.get("indexed_assets", 0),
        "indexed_chunks": index_report.get("indexed_chunks", 0),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UMB multimodal ingestion pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("classify-discovered")
    download = sub.add_parser("download-assets")
    download.add_argument("--max-files", type=int, default=get_settings().multimodal_max_files_per_run)
    sub.add_parser("extract-assets")
    sub.add_parser("index-assets")
    run = sub.add_parser("run-all")
    run.add_argument("--max-files", type=int, default=get_settings().multimodal_max_files_per_run)
    args = parser.parse_args(argv)

    if args.command == "classify-discovered":
        report = classify_discovered()
    elif args.command == "download-assets":
        report = download_assets(max_files=args.max_files)
    elif args.command == "extract-assets":
        report = extract_assets()
    elif args.command == "index-assets":
        report = index_assets()
    elif args.command == "run-all":
        report = run_all(max_files=args.max_files)
    else:
        raise SystemExit("Unknown command")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
