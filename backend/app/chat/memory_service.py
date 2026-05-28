from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.redaction import redact_sensitive
from app.db.models import ChatMemory, ChatMessage, ChatSession, utcnow


def get_active_memories(db: Session, session_id: str, anonymous_session_id: str | None = None, limit: int = 20) -> list[ChatMemory]:
    query = db.query(ChatMemory).filter(ChatMemory.is_active.is_(True))
    if session_id:
        query = query.filter(ChatMemory.session_id == session_id)
    elif anonymous_session_id:
        query = query.filter(ChatMemory.anonymous_session_id == anonymous_session_id)
    return query.order_by(ChatMemory.importance_score.desc(), ChatMemory.updated_at.desc()).limit(limit).all()


def summarize_safe_messages(messages: list[ChatMessage], max_chars: int = 1200) -> str:
    lines = []
    for message in messages[-10:]:
        content = redact_sensitive(message.content)
        if content.strip():
            lines.append(f"{message.role}: {content[:300]}")
    summary = "\n".join(lines)
    return summary[:max_chars]


def refresh_session_memory(db: Session, session_id: str) -> ChatMemory | None:
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session or not session.memory_enabled:
        return None
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    summary = summarize_safe_messages(messages)
    if not summary:
        return None
    existing = (
        db.query(ChatMemory)
        .filter(ChatMemory.session_id == session_id, ChatMemory.memory_type == "session_summary", ChatMemory.is_active.is_(True))
        .first()
    )
    if existing:
        existing.content = summary
        existing.updated_at = utcnow()
        memory = existing
    else:
        memory = ChatMemory(
            session_id=session_id,
            anonymous_session_id=session.anonymous_session_id,
            memory_type="session_summary",
            content=summary,
            importance_score=0.7,
        )
        db.add(memory)
    db.flush()
    return memory


def toggle_memory(db: Session, session_id: str, enabled: bool) -> ChatSession | None:
    session = db.query(ChatSession).filter(ChatSession.id == session_id, ChatSession.is_archived.is_(False)).first()
    if not session:
        return None
    session.memory_enabled = enabled
    session.updated_at = utcnow()
    db.commit()
    db.refresh(session)
    return session


def delete_memory(db: Session, memory_id: str) -> bool:
    memory = db.query(ChatMemory).filter(ChatMemory.id == memory_id).first()
    if not memory:
        return False
    memory.is_active = False
    memory.updated_at = utcnow()
    db.commit()
    return True
