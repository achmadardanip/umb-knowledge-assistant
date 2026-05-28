from __future__ import annotations

from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, Query

from app.db.database import get_db
from app.db.models import Source


router = APIRouter(tags=["sources"])


@router.get("/sources")
def list_sources(limit: int = Query(default=50, le=500), db: Session = Depends(get_db)) -> dict:
    rows = db.query(Source).order_by(Source.fetched_at.desc()).limit(limit).all()
    return {
        "sources": [
            {
                "id": source.id,
                "url": source.url,
                "title": source.title,
                "hostname": source.hostname,
                "path": source.path,
                "status": source.status,
                "discovery_source": source.discovery_source,
                "http_status": source.http_status,
                "fetched_at": source.fetched_at.isoformat() if source.fetched_at else None,
            }
            for source in rows
        ]
    }

