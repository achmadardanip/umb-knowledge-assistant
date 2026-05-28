from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.paths import project_path
from app.db.database import get_db
from app.db.models import ExtractedSegment, SourceAsset


router = APIRouter(prefix="/multimodal", tags=["multimodal"])


@router.get("/assets")
def assets(limit: int = Query(default=100, le=500), db: Session = Depends(get_db)) -> dict:
    rows = db.query(SourceAsset).order_by(SourceAsset.created_at.desc()).limit(limit).all()
    return {
        "assets": [
            {
                "id": asset.id,
                "url": asset.url,
                "source_type": asset.source_type,
                "mime_type": asset.mime_type,
                "download_status": asset.download_status,
                "extraction_status": asset.extraction_status,
                "extraction_method": asset.extraction_method,
                "extraction_confidence": asset.extraction_confidence,
            }
            for asset in rows
        ]
    }


@router.get("/extraction-report")
def extraction_report() -> dict:
    path = project_path("data", "multimodal", "extraction_report.json")
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


@router.get("/assets/{asset_id}/segments")
def asset_segments(asset_id: str, db: Session = Depends(get_db)) -> dict:
    rows = db.query(ExtractedSegment).filter(ExtractedSegment.asset_id == asset_id).order_by(ExtractedSegment.created_at.asc()).all()
    if not rows:
        asset = db.query(SourceAsset).filter(SourceAsset.id == asset_id).first()
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
    return {
        "segments": [
            {
                "id": segment.id,
                "segment_type": segment.segment_type,
                "content": segment.content,
                "page_number": segment.page_number,
                "slide_number": segment.slide_number,
                "sheet_name": segment.sheet_name,
                "row_range": segment.row_range,
                "timestamp_start": segment.timestamp_start,
                "timestamp_end": segment.timestamp_end,
                "extraction_confidence": segment.extraction_confidence,
            }
            for segment in rows
        ]
    }
