"""Interaction-driven FAQ: the home page's top questions evolve from what users
actually ask, with curated defaults so it is never empty."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

from sqlalchemy.orm import Session

from app.db.models import ChatMessage, utcnow
from app.rag.answer_cache import normalize_question

CURATED_FAQ = [
    "Bagaimana cara daftar mahasiswa baru di UMB?",
    "Berapa biaya kuliah di Universitas Mercu Buana?",
    "Apa saja program studi yang tersedia di UMB?",
    "Bagaimana cara login SSO dan SIA UMB?",
    "Di mana informasi perpustakaan UMB?",
    "Apa saja beasiswa yang tersedia di UMB?",
]


def top_questions(db: Session, *, limit: int = 6, days: int = 30, min_len: int = 12) -> list[dict]:
    """Most-asked user questions in the recent window, normalized and counted."""
    cutoff = utcnow() - timedelta(days=days)
    rows = (
        db.query(ChatMessage.content)
        .filter(ChatMessage.role == "user", ChatMessage.created_at >= cutoff)
        .all()
    )
    counter: Counter[str] = Counter()
    display: dict[str, str] = {}
    for (content,) in rows:
        question = (content or "").strip()
        if len(question) < min_len:
            continue
        key = normalize_question(question)
        counter[key] += 1
        display.setdefault(key, question)
    return [{"question": display[key], "count": count} for key, count in counter.most_common(limit)]


def top_faq(db: Session, *, limit: int = 6) -> list[str]:
    """Dynamic top questions, padded with curated defaults up to ``limit``."""
    questions = [item["question"] for item in top_questions(db, limit=limit)]
    seen = {normalize_question(q) for q in questions}
    for candidate in CURATED_FAQ:
        if len(questions) >= limit:
            break
        if normalize_question(candidate) not in seen:
            questions.append(candidate)
            seen.add(normalize_question(candidate))
    return questions[:limit]
