"""Tests for Phase 2 — Structured Entity Knowledge Layer.

Covers:
 - entity_extractor seed_entities / mine_entities
 - entity_retriever query_entities intent detection + formatting
 - umb_agent run_entity_lookup integration (via monkey-patch)
"""

from __future__ import annotations

import pytest

from app.db.models import (
    UMBCampus,
    UMBContact,
    UMBFaculty,
    UMBScholarship,
    UMBService,
    UMBStudyProgram,
)
from app.ingestion.entity_extractor import seed_entities
from app.retrieval.entity_retriever import (
    _has_any,
    _tokenize,
    query_entities,
    _lookup_faculties,
    _lookup_programs,
    _lookup_campuses,
    _lookup_scholarships,
    _lookup_contacts,
    _FACULTY_TERMS,
    _PROGRAM_TERMS,
    _CAMPUS_TERMS,
    _SCHOLARSHIP_TERMS,
    _CONTACT_TERMS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def seeded_db(db):
    """A test DB seeded with UMB entity data."""
    seed_entities(db, confidence=0.85)
    return db


# ---------------------------------------------------------------------------
# entity_extractor: seed pass
# ---------------------------------------------------------------------------


def test_seed_entities_populates_faculties(db):
    counts = seed_entities(db)
    assert counts["faculties"] == 7
    assert db.query(UMBFaculty).count() == 7


def test_seed_entities_populates_programs(db):
    counts = seed_entities(db)
    assert counts["programs"] == 20


def test_seed_entities_populates_campuses(db):
    counts = seed_entities(db)
    assert counts["campuses"] == 4


def test_seed_entities_populates_scholarships(db):
    counts = seed_entities(db)
    assert counts["scholarships"] == 4


def test_seed_entities_populates_contacts_and_services(db):
    counts = seed_entities(db)
    assert counts["contacts"] == 7
    assert counts["services"] == 6


def test_seed_entities_is_idempotent(db):
    seed_entities(db)
    counts2 = seed_entities(db)
    # Second run inserts 0 new rows (all already present)
    assert all(v == 0 for v in counts2.values())


def test_seed_programs_have_faculty_fk(seeded_db):
    programs = seeded_db.query(UMBStudyProgram).all()
    assert all(p.faculty_name for p in programs)
    # All programs for known faculties should resolve their FK
    assert any(p.faculty_id is not None for p in programs)


def test_seed_programs_upsert_key_is_unique(seeded_db):
    keys = [p.upsert_key for p in seeded_db.query(UMBStudyProgram).all()]
    assert len(keys) == len(set(keys))


def test_seed_campus_meruya_has_address(seeded_db):
    meruya = seeded_db.query(UMBCampus).filter(UMBCampus.campus_name == "Meruya").first()
    assert meruya is not None
    assert meruya.address and "Meruya" in meruya.address
    assert meruya.phone


def test_seed_contact_pmb_has_phone(seeded_db):
    pmb = (
        seeded_db.query(UMBContact)
        .filter(UMBContact.service_type == "admission")
        .first()
    )
    assert pmb is not None
    assert pmb.phone or pmb.whatsapp


# ---------------------------------------------------------------------------
# entity_retriever: intent detection
# ---------------------------------------------------------------------------


def test_tokenize_splits_query():
    tokens = _tokenize("Siapa dekan Fakultas Ilmu Komputer?")
    assert "dekan" in tokens
    assert "komputer" in tokens


def test_has_any_matches_terms():
    assert _has_any(["dekan", "fakultas"], _FACULTY_TERMS)
    assert not _has_any(["berita", "olahraga"], _FACULTY_TERMS)


def test_has_any_matches_campus_terms():
    assert _has_any(["meruya", "lokasi"], _CAMPUS_TERMS)
    assert _has_any(["alamat", "kampus"], _CAMPUS_TERMS)


def test_has_any_matches_scholarship_terms():
    assert _has_any(["beasiswa", "kip"], _SCHOLARSHIP_TERMS)


def test_has_any_matches_contact_terms():
    assert _has_any(["kontak", "telepon"], _CONTACT_TERMS)


# ---------------------------------------------------------------------------
# entity_retriever: lookup functions
# ---------------------------------------------------------------------------


def test_lookup_faculties_returns_all_on_generic_query(seeded_db):
    tokens = _tokenize("daftar fakultas di UMB")
    results = _lookup_faculties(seeded_db, tokens)
    assert len(results) >= 6
    types = {r["entity_type"] for r in results}
    assert types == {"faculty"}


def test_lookup_faculties_targets_fasilkom(seeded_db):
    tokens = _tokenize("dekan fasilkom UMB")
    results = _lookup_faculties(seeded_db, tokens)
    names = [r["title"] for r in results]
    assert any("Komputer" in n for n in names)


def test_lookup_programs_returns_informatika(seeded_db):
    tokens = _tokenize("program studi teknik informatika S1")
    results = _lookup_programs(seeded_db, tokens)
    texts = " ".join(r["chunk_text"] for r in results)
    assert "Teknik Informatika" in texts


def test_lookup_campuses_returns_meruya(seeded_db):
    tokens = _tokenize("alamat kampus meruya")
    results = _lookup_campuses(seeded_db, tokens)
    assert len(results) == 1
    assert results[0]["title"] and "Meruya" in results[0]["title"]
    assert "Jl." in results[0]["chunk_text"] or "alamat" in results[0]["chunk_text"].lower()


def test_lookup_campuses_returns_all_on_generic(seeded_db):
    tokens = _tokenize("lokasi kampus UMB")
    results = _lookup_campuses(seeded_db, tokens)
    assert len(results) == 4


def test_lookup_scholarships_returns_kip(seeded_db):
    tokens = _tokenize("beasiswa KIP kuliah")
    results = _lookup_scholarships(seeded_db, tokens)
    names = [r["title"] for r in results]
    assert any("KIP" in n for n in names)


def test_lookup_contacts_returns_pmb_for_pendaftaran(seeded_db):
    tokens = _tokenize("kontak pendaftaran mahasiswa baru")
    results = _lookup_contacts(seeded_db, tokens)
    types = {r.get("entity_type") for r in results}
    assert "contact" in types
    texts = " ".join(r["chunk_text"] for r in results)
    assert "PMB" in texts or "Mahasiswa Baru" in texts


# ---------------------------------------------------------------------------
# entity_retriever: query_entities integration
# ---------------------------------------------------------------------------


def test_query_entities_faculty_query(seeded_db):
    results = query_entities(seeded_db, "Siapa dekan Fakultas Ilmu Komputer UMB?")
    assert len(results) > 0
    assert all(r["entity_type"] in {"faculty", "study_program"} for r in results)


def test_query_entities_campus_query(seeded_db):
    results = query_entities(seeded_db, "Dimana alamat kampus Meruya UMB?")
    assert len(results) > 0
    campus_results = [r for r in results if r["entity_type"] == "campus"]
    assert len(campus_results) >= 1
    assert "Meruya" in campus_results[0]["chunk_text"]


def test_query_entities_scholarship_query(seeded_db):
    results = query_entities(seeded_db, "Ada beasiswa apa saja di UMB?")
    assert len(results) > 0
    assert any(r["entity_type"] == "scholarship" for r in results)


def test_query_entities_returns_empty_for_irrelevant_query(seeded_db):
    results = query_entities(seeded_db, "Apa itu kecerdasan buatan?")
    assert results == []


def test_query_entities_demotes_program_under_tuition_intent(seeded_db):
    # v2: a tuition question that mentions a program name must NOT surface the
    # program/faculty entity at a high (pinned) score.
    results = query_entities(seeded_db, "Berapa biaya kuliah program studi Akuntansi di UMB?")
    for c in results:
        if c["entity_type"] in {"study_program", "faculty"}:
            assert c.get("intent_demoted") is True
            assert c["score"] <= 2.0


def test_query_entities_keeps_scholarship_under_scholarship_intent(seeded_db):
    results = query_entities(seeded_db, "Apakah ada beasiswa untuk mahasiswa Akuntansi?")
    sch = [c for c in results if c["entity_type"] == "scholarship"]
    assert sch and not sch[0].get("intent_demoted")
    assert results[0]["entity_type"] == "scholarship"  # compatible entity ranks first


def test_query_entities_biaya_no_longer_triggers_scholarship(seeded_db):
    # "biaya" was removed from scholarship terms → a pure tuition query must not
    # return scholarship entities at full score.
    results = query_entities(seeded_db, "Berapa biaya kuliah di UMB?")
    non_demoted = [c for c in results if not c.get("intent_demoted")]
    assert not any(c["entity_type"] == "scholarship" for c in non_demoted)


def test_query_entities_scores_above_typical_tahf(seeded_db):
    results = query_entities(seeded_db, "Apa akreditasi Fakultas Teknik UMB?")
    assert all(r["score"] >= 7.0 for r in results)


def test_query_entities_capped_at_six(seeded_db):
    # Broad query that could match many entity types
    results = query_entities(seeded_db, "fakultas program beasiswa kontak kampus UMB")
    assert len(results) <= 6


def test_query_entities_deduplicates_results(seeded_db):
    results = query_entities(seeded_db, "Siapa dekan fasilkom fakultas ilmu komputer?")
    ids = [r.get("entity_id") for r in results if r.get("entity_id")]
    assert len(ids) == len(set(ids))


def test_query_entities_graceful_on_missing_tables():
    """If entity tables don't exist, returns [] without raising."""
    from app.db.database import configure_test_database
    from app.db.models import Base

    engine = configure_test_database()
    # Create ONLY the non-entity tables (skip umb_* tables)
    from sqlalchemy import text

    Base.metadata.create_all(engine, checkfirst=True)
    # Drop entity tables to simulate pre-migration state
    from app.db.database import get_session_local

    session = get_session_local()()
    try:
        with engine.begin() as conn:
            for tbl in ("umb_services", "umb_contacts", "umb_scholarships", "umb_campuses",
                        "umb_study_programs", "umb_faculties"):
                conn.execute(text(f"DROP TABLE IF EXISTS {tbl}"))
        # Should not raise, and returns [] because tables are gone
        results = query_entities(session, "dekan fasilkom")
        assert results == []
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Context dict shape
# ---------------------------------------------------------------------------


def test_faculty_context_has_required_fields(seeded_db):
    results = query_entities(seeded_db, "fakultas teknik UMB")
    for ctx in results:
        if ctx["entity_type"] == "faculty":
            assert ctx["chunk_text"]
            assert ctx["url"]
            assert ctx["hostname"]
            assert ctx["score"] > 0
            assert ctx["source_type"] == "entity"
            break


def test_campus_context_contains_address(seeded_db):
    results = query_entities(seeded_db, "alamat kampus bekasi UMB")
    for ctx in results:
        if ctx["entity_type"] == "campus":
            assert "Alamat:" in ctx["chunk_text"] or "Kampus:" in ctx["chunk_text"]
            break
