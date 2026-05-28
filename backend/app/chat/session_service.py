from __future__ import annotations

from sqlalchemy.orm import Session

from app.chat.title_generator import generate_title_from_question, generate_title_with_llm
from app.db.models import ChatMessage, ChatSession, utcnow


def create_session(db: Session, anonymous_session_id: str | None, user_id: str | None = None) -> ChatSession:
    session = ChatSession(
        user_id=user_id,
        anonymous_session_id=anonymous_session_id,
        title="New Chat",
        memory_enabled=True,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db: Session, session_id: str) -> ChatSession | None:
    return db.query(ChatSession).filter(ChatSession.id == session_id, ChatSession.is_archived.is_(False)).first()


def list_sessions(db: Session, anonymous_session_id: str | None, user_id: str | None = None) -> list[ChatSession]:
    query = db.query(ChatSession).filter(ChatSession.is_archived.is_(False))
    if user_id:
        query = query.filter(ChatSession.user_id == user_id)
    elif anonymous_session_id:
        query = query.filter(ChatSession.anonymous_session_id == anonymous_session_id)
    return query.order_by(ChatSession.last_message_at.desc()).all()


def rename_session(db: Session, session_id: str, title: str) -> ChatSession | None:
    session = get_session(db, session_id)
    if not session:
        return None
    session.title = (title or "New Chat").strip()[:200]
    session.updated_at = utcnow()
    db.commit()
    db.refresh(session)
    return session


def archive_session(db: Session, session_id: str) -> bool:
    session = get_session(db, session_id)
    if not session:
        return False
    session.is_archived = True
    session.updated_at = utcnow()
    db.commit()
    return True


def maybe_autotitle_session(db: Session, session_id: str, question: str) -> str:
    session = get_session(db, session_id)
    if not session:
        return "New Chat"
    message_count = db.query(ChatMessage).filter(ChatMessage.session_id == session_id, ChatMessage.role == "user").count()
    if session.title == "New Chat" and message_count <= 1:
        session.title = generate_title_from_question(question)
        session.updated_at = utcnow()
        db.flush()
    return session.title


def maybe_refine_title_with_llm(db: Session, session_id: str, question: str, provider_override: str | None = None) -> str:
    session = get_session(db, session_id)
    if not session:
        return "New Chat"
    message_count = db.query(ChatMessage).filter(ChatMessage.session_id == session_id, ChatMessage.role == "user").count()
    if message_count > 1:
        return session.title
    generated = generate_title_with_llm(question, provider_override=provider_override)
    if generated:
        session.title = generated[:200]
        session.updated_at = utcnow()
        db.flush()
    return session.title


def load_messages(db: Session, session_id: str) -> list[ChatMessage]:
    return (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
