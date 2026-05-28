from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, Query

from app.chat.session_service import archive_session, create_session, list_sessions, load_messages, rename_session
from app.db.database import get_db


router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    anonymous_session_id: str | None = None


class RenameSessionRequest(BaseModel):
    title: str


def serialize_session(session) -> dict:
    return {
        "session_id": session.id,
        "title": session.title,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        "last_message_at": session.last_message_at.isoformat() if session.last_message_at else None,
        "memory_enabled": session.memory_enabled,
    }


def serialize_message(message) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "sources": message.sources or [],
        "confidence": message.confidence_score,
        "provider_used": message.provider_used,
        "model_used": message.model_used,
        "not_found": message.not_found,
        "visible_steps": message.visible_steps or [],
        "created_at": message.created_at.isoformat() if message.created_at else None,
        "metadata": message.meta or {},
    }


@router.post("")
def create(payload: CreateSessionRequest, db: Session = Depends(get_db)) -> dict:
    session = create_session(db, payload.anonymous_session_id)
    return serialize_session(session)


@router.get("")
def list_all(anonymous_session_id: str | None = Query(default=None), db: Session = Depends(get_db)) -> dict:
    return {"sessions": [serialize_session(session) for session in list_sessions(db, anonymous_session_id)]}


@router.get("/{session_id}/messages")
def messages(session_id: str, db: Session = Depends(get_db)) -> dict:
    return {"messages": [serialize_message(message) for message in load_messages(db, session_id)]}


@router.patch("/{session_id}")
def rename(session_id: str, payload: RenameSessionRequest, db: Session = Depends(get_db)) -> dict:
    session = rename_session(db, session_id, payload.title)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return serialize_session(session)


@router.delete("/{session_id}")
def delete(session_id: str, db: Session = Depends(get_db)) -> dict:
    if not archive_session(db, session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}

