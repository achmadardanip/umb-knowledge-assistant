from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, Query

from app.core.paths import project_path
from app.db.database import get_db
from app.db.models import DiscoveredHost, DiscoveredURL, Source


router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.get("/report")
def discovery_report() -> dict:
    path = project_path("data", "discovery", "discovery_report.json")
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


@router.get("/hosts")
def discovery_hosts(limit: int = Query(default=100, le=1000), db: Session = Depends(get_db)) -> dict:
    hosts = db.query(DiscoveredHost).order_by(DiscoveredHost.discovered_at.desc()).limit(limit).all()
    return {"hosts": [{"hostname": host.hostname, "is_allowed": host.is_allowed, "discovery_source": host.discovery_source, "rejection_reason": host.rejection_reason} for host in hosts]}


@router.get("/urls")
def discovery_urls(limit: int = Query(default=100, le=1000), db: Session = Depends(get_db)) -> dict:
    urls = db.query(DiscoveredURL).order_by(DiscoveredURL.discovered_at.desc()).limit(limit).all()
    return {"urls": [{"url": item.url, "normalized_url": item.normalized_url, "hostname": item.hostname, "is_allowed": item.is_allowed, "indexed": item.indexed, "discovery_source": item.discovery_source, "rejection_reason": item.rejection_reason} for item in urls]}


@router.get("/sources")
def discovery_sources(limit: int = Query(default=100, le=1000), db: Session = Depends(get_db)) -> dict:
    rows = db.query(Source).order_by(Source.fetched_at.desc()).limit(limit).all()
    return {"sources": [{"url": source.url, "title": source.title, "status": source.status, "discovery_source": source.discovery_source} for source in rows]}
