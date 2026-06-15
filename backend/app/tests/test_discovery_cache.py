"""Tests for Batch 4 — confidence evaluation + knowledge discovery cache + async acquisition."""

from __future__ import annotations

from app.db.models import KnowledgeDiscoveryCache
from app.rag.discovery_cache import (
    evaluate_confidence,
    record_discoveries,
    was_recently_discovered,
)


# --- confidence evaluation ---------------------------------------------------
def test_confidence_empty_is_insufficient():
    score, ok = evaluate_confidence([])
    assert score == 0.0 and ok is False


def test_confidence_strong_faq_is_sufficient():
    score, ok = evaluate_confidence([{"source_type": "faq", "score": 14.0, "hostname": "sia.mercubuana.ac.id"}])
    assert ok is True and score >= 0.9


def test_confidence_demoted_structured_not_trusted():
    # an intent-demoted entity is NOT a confident structured hit; a single official
    # top chunk is not sufficient on its own (defers to the count/score gate).
    ctx = [{"source_type": "entity", "score": 2.0, "intent_demoted": True, "hostname": "www.mercubuana.ac.id"}]
    score, ok = evaluate_confidence(ctx)
    assert ok is False and 0.5 <= score < 0.85


def test_confidence_two_official_chunks_sufficient():
    ctx = [
        {"source_type": "html", "score": 3.0, "hostname": "pendaftaran.mercubuana.ac.id"},
        {"source_type": "html", "score": 2.0, "hostname": "baa.mercubuana.ac.id"},
    ]
    score, ok = evaluate_confidence(ctx)
    assert ok is True and score >= 0.7


def test_confidence_archive_only_insufficient():
    ctx = [{"source_type": "html", "score": 2.0, "hostname": "repository.mercubuana.ac.id"}]
    score, ok = evaluate_confidence(ctx)
    assert ok is False  # archive (authority 0.25) → not official enough → fallback


# --- discovery cache ---------------------------------------------------------
def test_record_and_recently_discovered(db):
    q = "Bagaimana cara mengurus surat keterangan aktif kuliah?"
    web_ctx = [{"url": "https://baa.mercubuana.ac.id/surat-aktif", "chunk_text": "..."}]
    assert was_recently_discovered(db, q) is False
    n = record_discoveries(db, q, web_ctx, indexed=True)
    assert n == 1
    assert was_recently_discovered(db, q) is True
    row = db.query(KnowledgeDiscoveryCache).first()
    assert row.source_domain == "baa.mercubuana.ac.id"
    assert row.indexed is True


def test_recently_discovered_respects_indexed_flag(db):
    q = "Pertanyaan yang ditemukan tapi belum terindeks?"
    record_discoveries(db, q, [{"url": "https://www.mercubuana.ac.id/x", "chunk_text": "y"}], indexed=False)
    # not indexed yet → don't skip Tavily next time
    assert was_recently_discovered(db, q) is False


def test_recently_discovered_respects_ttl(db):
    q = "Pertanyaan lama?"
    record_discoveries(db, q, [{"url": "https://www.mercubuana.ac.id/old", "chunk_text": "z"}], indexed=True)
    assert was_recently_discovered(db, q, ttl_hours=168) is True
    assert was_recently_discovered(db, q, ttl_hours=0) is True  # clamped to >=1h, row is fresh


# --- async acquisition -------------------------------------------------------
def test_schedule_kb_acquisition_returns_false_for_empty():
    from app.ingestion.async_acquisition import schedule_kb_acquisition

    assert schedule_kb_acquisition("q", []) is False
    assert schedule_kb_acquisition("q", [{"url": "", "chunk_text": ""}]) is False
