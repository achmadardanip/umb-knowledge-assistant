from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.chat.faq_service import top_faq
from app.db.database import get_db

router = APIRouter()


@router.get("/faq/top")
def faq_top(limit: int = 6, db: Session = Depends(get_db)) -> dict:
    """Interaction-driven top questions for the home page (curated fallback)."""
    return {"questions": top_faq(db, limit=max(1, min(limit, 12)))}
