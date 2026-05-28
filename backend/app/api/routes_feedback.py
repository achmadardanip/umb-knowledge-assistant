from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends

from app.db.database import get_db
from app.db.models import Feedback


router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackRequest(BaseModel):
    message_id: str
    rating: Literal["helpful", "not_helpful"]
    comment: str | None = None


@router.post("")
def create_feedback(payload: FeedbackRequest, db: Session = Depends(get_db)) -> dict:
    feedback = Feedback(message_id=payload.message_id, rating=payload.rating, comment=payload.comment)
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return {"id": feedback.id, "rating": feedback.rating}

