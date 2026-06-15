"""Tests for Phase 3 — Canonical FAQ Layer (seeder + retriever + agent wiring)."""

from __future__ import annotations

import pytest

from app.db.models import UMBFAQ
from app.ingestion.faq_seed import FAQ_SEEDS, seed_faqs
from app.retrieval.faq_retriever import (
    _content_tokens,
    _dice,
    _normalize,
    match_faq,
)


@pytest.fixture()
def faq_db(db):
    seed_faqs(db)
    return db


# ---------------------------------------------------------------------------
# Seeder
# ---------------------------------------------------------------------------


def test_seed_faqs_inserts_all(db):
    counts = seed_faqs(db)
    assert counts["inserted"] == len(FAQ_SEEDS)
    assert db.query(UMBFAQ).count() == len(FAQ_SEEDS)


def test_seed_faqs_is_idempotent(db):
    seed_faqs(db)
    counts2 = seed_faqs(db)
    # Second run updates (refreshes) but inserts nothing new
    assert counts2["inserted"] == 0
    assert counts2["updated"] == len(FAQ_SEEDS)
    assert db.query(UMBFAQ).count() == len(FAQ_SEEDS)


def test_seed_faqs_populates_normalized_and_sources(faq_db):
    for faq in faq_db.query(UMBFAQ).all():
        assert faq.normalized_question == faq.normalized_question.lower().strip()
        assert faq.answer
        assert isinstance(faq.source_urls, list) and faq.source_urls
        assert "mercubuana.ac.id" in faq.source_urls[0]


def test_seed_covers_weak_domains(faq_db):
    categories = {f.category for f in faq_db.query(UMBFAQ).all()}
    # Domains the Phase-1 benchmark flagged weak must be covered
    for needed in {"admissions", "sia", "sso", "scholarship", "student_services"}:
        assert needed in categories


# ---------------------------------------------------------------------------
# Matching primitives
# ---------------------------------------------------------------------------


def test_normalize_collapses_whitespace_and_case():
    assert _normalize("  Bagaimana   CARA Daftar? ") == "bagaimana cara daftar?"


def test_content_tokens_strips_stopwords():
    tokens = _content_tokens("Bagaimana cara daftar mahasiswa baru di UMB?")
    # question words + 'umb' removed; content words kept
    assert "daftar" in tokens
    assert "mahasiswa" in tokens
    assert "bagaimana" not in tokens
    assert "umb" not in tokens


def test_content_tokens_falls_back_for_short_query():
    # All-stopword-ish short query falls back to raw tokens
    tokens = _content_tokens("SIA")
    assert "sia" in tokens


def test_dice_identical_sets_is_one():
    s = {"daftar", "mahasiswa"}
    assert _dice(s, s) == 1.0


def test_dice_disjoint_is_zero():
    assert _dice({"a", "b"}, {"c", "d"}) == 0.0


# ---------------------------------------------------------------------------
# match_faq — exact / fuzzy / negative
# ---------------------------------------------------------------------------


def test_match_faq_exact_canonical(faq_db):
    results = match_faq(faq_db, "Bagaimana cara mendaftar sebagai mahasiswa baru di UMB?")
    assert results
    top = results[0]
    assert top["source_type"] == "faq"
    assert top["faq_matched_via"] == "exact"
    assert top["score"] == 14.0


def test_match_faq_exact_alias(faq_db):
    # An alias phrased differently from the canonical question
    results = match_faq(faq_db, "cara daftar mahasiswa baru umb")
    assert results
    assert results[0]["faq_matched_via"] == "exact"


def test_match_faq_fuzzy_paraphrase(faq_db):
    results = match_faq(faq_db, "Gimana sih langkah-langkah mendaftar jadi mahasiswa baru?")
    assert results
    assert results[0]["entity_type"] == "faq"
    assert "pendaftaran.mercubuana.ac.id" in results[0]["url"]


def test_match_faq_sso_login(faq_db):
    results = match_faq(faq_db, "cara login SSO UMB gimana?")
    assert results
    answer = results[0]["chunk_text"].lower()
    assert "sso" in answer


def test_match_faq_scholarship(faq_db):
    results = match_faq(faq_db, "beasiswa apa saja yang ada di mercu buana?")
    assert results
    assert results[0]["chunk_text"]
    cats_titles = results[0]["title"].lower()
    assert "beasiswa" in cats_titles


def test_match_faq_returns_empty_for_unrelated(faq_db):
    results = match_faq(faq_db, "Bagaimana cuaca di Jakarta hari ini?")
    assert results == []


def test_match_faq_score_above_entity_scores(faq_db):
    # FAQ must outrank entity contexts (entity high = 10.0)
    results = match_faq(faq_db, "Berapa biaya kuliah di Universitas Mercu Buana?")
    assert results
    assert results[0]["score"] >= 12.0


def test_match_faq_respects_is_active(faq_db):
    # Deactivate all FAQs → no matches
    for faq in faq_db.query(UMBFAQ).all():
        faq.is_active = False
    faq_db.commit()
    results = match_faq(faq_db, "Bagaimana cara mendaftar sebagai mahasiswa baru di UMB?")
    assert results == []


def test_match_faq_caps_results(faq_db):
    results = match_faq(faq_db, "pendaftaran biaya beasiswa sso sia mahasiswa baru umb")
    assert len(results) <= 2


def test_match_faq_graceful_when_table_missing():
    """If umb_faqs doesn't exist, match_faq returns [] without raising."""
    from sqlalchemy import text

    from app.db.database import configure_test_database, get_session_local
    from app.db.models import Base

    engine = configure_test_database()
    Base.metadata.create_all(engine, checkfirst=True)
    session = get_session_local()()
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS umb_faqs"))
        results = match_faq(session, "cara daftar umb")
        assert isinstance(results, list)
        assert results == []
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Agent wiring — FAQ ranks first
# ---------------------------------------------------------------------------


def test_agent_faq_lookup_ranks_first(faq_db, monkeypatch):
    """run_umb_agent should surface a matched FAQ as the top context."""
    from app.agent import umb_agent

    # Stub the hybrid retriever so the test doesn't touch real vector search
    class _StubRetriever:
        def __init__(self, db, root_domain="mercubuana.ac.id", **kwargs):
            pass

        def search(self, query, top_k=5, **kwargs):
            return [
                {
                    "chunk_id": "c1",
                    "chunk_text": "Beberapa info pendaftaran umum.",
                    "url": "https://www.mercubuana.ac.id/info",
                    "title": "Info",
                    "score": 3.0,
                    "hostname": "www.mercubuana.ac.id",
                    "source_type": "html",
                }
            ]

    monkeypatch.setattr(umb_agent, "get_settings", umb_agent.get_settings)
    steps: list[tuple] = []

    result = umb_agent.run_umb_agent(
        db=faq_db,
        query="Bagaimana cara mendaftar sebagai mahasiswa baru di UMB?",
        retrieval_mode="indexed",
        top_k=5,
        root_domain="mercubuana.ac.id",
        emit=lambda *a: steps.append(a),
        indexed_retriever_cls=_StubRetriever,
    )

    assert result.contexts
    assert result.contexts[0]["source_type"] == "faq"
    # the FAQ step was emitted
    assert any(s[0] == "faq_lookup" for s in steps)
