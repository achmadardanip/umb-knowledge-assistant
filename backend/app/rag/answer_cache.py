from __future__ import annotations

import hashlib
import json
import re
from datetime import timedelta

from sqlalchemy.orm import Session

from app.db.models import RAGAnswerCache, utcnow


def normalize_question(question: str) -> str:
    return re.sub(r"\s+", " ", (question or "").strip().lower())


def question_hash(question: str) -> str:
    return hashlib.sha256(normalize_question(question).encode("utf-8")).hexdigest()


def build_cache_key(
    *,
    question: str,
    intent: str,
    provider_used: str,
    model_used: str,
    contexts: list[dict],
    memory_enabled: bool,
) -> str:
    # Intentionally NOT keyed on retrieved contexts: while the live crawl mutates
    # the index, context ids shift between identical questions and the cache would
    # never hit. Keying on the normalized question + provider/model gives reliable
    # hits for repeated questions (bounded by the TTL); volatile facts are handled
    # separately by the freshness/VA-JIT path, not by cache invalidation.
    _ = contexts  # kept in the signature for caller compatibility
    payload = {
        "question_hash": question_hash(question),
        "intent": intent,
        "provider": provider_used,
        "model": model_used,
        "memory_enabled": bool(memory_enabled),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_cached_answer(db: Session, cache_key: str) -> dict | None:
    row = (
        db.query(RAGAnswerCache)
        .filter(RAGAnswerCache.cache_key == cache_key, RAGAnswerCache.expires_at > utcnow())
        .first()
    )
    if not row:
        return None
    payload = dict(row.answer_payload or {})
    payload.setdefault("provider_used", row.provider_used)
    payload.setdefault("model_used", row.model_used)
    payload["cache_hit"] = True
    return payload


def store_cached_answer(
    db: Session,
    *,
    cache_key: str,
    question: str,
    intent: str,
    provider_used: str | None,
    model_used: str | None,
    answer_payload: dict,
    ttl_seconds: int,
) -> None:
    if not cache_key or not answer_payload:
        return
    now = utcnow()
    row = db.query(RAGAnswerCache).filter(RAGAnswerCache.cache_key == cache_key).first()
    if row is None:
        row = RAGAnswerCache(cache_key=cache_key, question_hash=question_hash(question))
        db.add(row)
    row.intent = intent
    row.provider_used = provider_used
    row.model_used = model_used
    row.answer_payload = answer_payload
    row.source_urls = [source.get("url") for source in answer_payload.get("sources") or [] if source.get("url")]
    row.created_at = now
    row.expires_at = now + timedelta(seconds=max(ttl_seconds, 60))
    db.flush()

