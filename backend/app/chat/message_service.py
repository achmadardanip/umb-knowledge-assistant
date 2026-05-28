from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.security import sanitize_user_visible_text
from app.db.models import ChatMessage, ChatSession, utcnow


def save_message(
    db: Session,
    *,
    session_id: str,
    role: str,
    content: str,
    sources: list[dict] | None = None,
    confidence_score: str | None = None,
    provider_used: str | None = None,
    model_used: str | None = None,
    not_found: bool = False,
    visible_steps: list[dict | str] | None = None,
    metadata: dict | None = None,
) -> ChatMessage:
    clean_content = sanitize_user_visible_text(content, redact_passwords=role != "assistant")
    message = ChatMessage(
        session_id=session_id,
        role=role,
        content=clean_content,
        sources=sources,
        confidence_score=confidence_score,
        provider_used=provider_used,
        model_used=model_used,
        not_found=not_found,
        visible_steps=visible_steps,
        meta=metadata or {},
    )
    db.add(message)
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if session:
        session.last_message_at = utcnow()
        session.updated_at = utcnow()
    db.flush()
    return message


def recent_messages(db: Session, session_id: str, limit: int = 12) -> list[dict]:
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "sources": message.sources or [],
            "created_at": message.created_at.isoformat() if message.created_at else None,
        }
        for message in reversed(rows)
    ]
