"""Read-only knowledge-base statistics for the UI sidebar (no retrieval/RAG logic)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.db.database import get_db

router = APIRouter(tags=["stats"])

_ENTITY_TABLES = (
    "umb_faculties", "umb_study_programs", "umb_campuses",
    "umb_scholarships", "umb_contacts", "umb_services",
)


def _count(db: Session, table: str) -> int:
    try:
        return int(db.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0)
    except Exception:
        return 0


@router.get("/stats")
def stats(db: Session = Depends(get_db)) -> dict:
    """Dynamic KB counts from PostgreSQL. Values are never hardcoded."""
    chunks = _count(db, "chunks")
    sources = _count(db, "sources")
    faculties = _count(db, "umb_faculties")
    programs = _count(db, "umb_study_programs")
    entities = sum(_count(db, t) for t in _ENTITY_TABLES)

    last_updated = None
    for table, col in (("sources", "fetched_at"), ("sources", "updated_at"), ("chunks", "created_at")):
        try:
            value = db.execute(text(f"SELECT max({col}) FROM {table}")).scalar()
            if value is not None:
                last_updated = value.isoformat() if hasattr(value, "isoformat") else str(value)
                break
        except Exception:
            continue

    return {
        "chunks": chunks,
        "sources": sources,
        "entities": entities,
        "faculties": faculties,
        "programs": programs,
        "last_updated": last_updated,
    }
