"""Phase 22 P22.3/P22.5 — feedback & conversation analytics (read-only).

Aggregates chat_messages + feedback to surface answer quality and top failure
categories so we can learn from real conversations. All values are computed live
from PostgreSQL.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.database import get_db

router = APIRouter(tags=["analytics"])


def _scalar(db: Session, q: str):
    try:
        return db.execute(text(q)).scalar()
    except Exception:
        return None


@router.get("/analytics")
def analytics(db: Session = Depends(get_db)) -> dict:
    sessions = _scalar(db, "SELECT count(*) FROM chat_sessions WHERE is_archived = false") or 0
    assistant = _scalar(db, "SELECT count(*) FROM chat_messages WHERE role='assistant'") or 0
    answered = _scalar(db, "SELECT count(*) FROM chat_messages WHERE role='assistant' AND not_found = false") or 0
    unanswered = _scalar(db, "SELECT count(*) FROM chat_messages WHERE role='assistant' AND not_found = true") or 0
    with_sources = _scalar(
        db,
        "SELECT count(*) FROM chat_messages WHERE role='assistant' "
        "AND sources IS NOT NULL AND jsonb_array_length(sources::jsonb) > 0",
    ) or 0

    fb_total = _scalar(db, "SELECT count(*) FROM feedback") or 0
    fb_pos = _scalar(db, "SELECT count(*) FROM feedback WHERE rating='helpful'") or 0
    fb_neg = _scalar(db, "SELECT count(*) FROM feedback WHERE rating='not_helpful'") or 0

    def rate(n, d):
        return round(n / d, 4) if d else 0.0

    # --- failure detection (P22.5) ---
    repeated_unanswered = db.execute(text(
        "SELECT lower(trim(u.content)) AS q, count(*) AS n "
        "FROM chat_messages a "
        "JOIN chat_messages u ON u.session_id = a.session_id AND u.role='user' "
        "  AND u.created_at < a.created_at "
        "WHERE a.role='assistant' AND a.not_found = true "
        "  AND u.id = (SELECT id FROM chat_messages u2 WHERE u2.session_id=a.session_id "
        "              AND u2.role='user' AND u2.created_at < a.created_at "
        "              ORDER BY u2.created_at DESC LIMIT 1) "
        "GROUP BY lower(trim(u.content)) HAVING count(*) > 1 ORDER BY n DESC LIMIT 10"
    )).all()
    clarification_requests = _scalar(
        db, "SELECT count(*) FROM chat_messages WHERE role='assistant' "
            "AND (metadata->>'intent_refusal' = 'true' OR content ILIKE '%apakah yang anda maksud%')"
    ) or 0
    failed_entity = db.execute(text(
        "SELECT lower(trim(u.content)) AS q, count(*) AS n "
        "FROM chat_messages a "
        "JOIN chat_messages u ON u.session_id=a.session_id AND u.role='user' AND u.created_at < a.created_at "
        "WHERE a.role='assistant' AND a.not_found = true "
        "  AND (u.content ILIKE '%dekan%' OR u.content ILIKE '%kaprodi%' OR u.content ILIKE '%akreditas%') "
        "GROUP BY lower(trim(u.content)) ORDER BY n DESC LIMIT 10"
    )).all()

    return {
        "total_chats": sessions,
        "total_answers": assistant,
        "positive_rate": rate(fb_pos, fb_total),
        "negative_rate": rate(fb_neg, fb_total),
        "unanswered_rate": rate(unanswered, assistant),
        "citation_usage_rate": rate(with_sources, assistant),
        "feedback": {"total": fb_total, "positive": fb_pos, "negative": fb_neg},
        "counts": {"answered": answered, "unanswered": unanswered, "with_sources": with_sources},
        "top_failures": {
            "repeated_unanswered_questions": [{"question": r[0], "count": r[1]} for r in repeated_unanswered],
            "repeated_clarification_requests": clarification_requests,
            "failed_entity_resolution": [{"question": r[0], "count": r[1]} for r in failed_entity],
        },
    }
