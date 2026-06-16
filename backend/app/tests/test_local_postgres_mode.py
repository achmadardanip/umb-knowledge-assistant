"""v3 P6 — local Postgres deployment mode (config routing + migration plumbing)."""

from __future__ import annotations

from app.core.config import _resolve_database_url


def test_local_postgres_mode_routes_database_url(monkeypatch):
    # _resolve_database_url reads env at call time (no module reload needed)
    monkeypatch.setenv("LOCAL_POSTGRES_MODE", "true")
    monkeypatch.setenv("LOCAL_POSTGRES_URL", "postgresql://umb:umb@localhost:5432/umb")
    monkeypatch.setenv("SUPABASE_POOLER_DATABASE_URL", "postgresql://supabase/x")
    assert _resolve_database_url() == "postgresql://umb:umb@localhost:5432/umb"  # local wins


def test_default_mode_uses_supabase(monkeypatch):
    monkeypatch.delenv("LOCAL_POSTGRES_MODE", raising=False)
    monkeypatch.setenv("SUPABASE_POOLER_DATABASE_URL", "postgresql://supabase/x")
    assert _resolve_database_url() == "postgresql://supabase/x"


def test_local_mode_default_url(monkeypatch):
    monkeypatch.setenv("LOCAL_POSTGRES_MODE", "1")
    monkeypatch.delenv("LOCAL_POSTGRES_URL", raising=False)
    assert _resolve_database_url() == "postgresql://umb:umb@localhost:5432/umb"


def test_migration_table_order_parents_before_children():
    from app.db.supabase_to_local import TABLES

    assert TABLES.index("sources") < TABLES.index("chunks")
    assert TABLES.index("chunks") < TABLES.index("chunk_embeddings")
    assert TABLES.index("umb_faculties") < TABLES.index("umb_study_programs")
    # the structured + v3 tables are all included
    for t in ("umb_faqs", "canonical_urls", "knowledge_discovery_cache", "documents"):
        assert t in TABLES


def test_bootstrap_and_migrate_modules_import():
    # plumbing imports cleanly (no syntax/cycle errors)
    from app.db import bootstrap_local, supabase_to_local

    assert hasattr(bootstrap_local, "bootstrap")
    assert hasattr(supabase_to_local, "migrate")


def test_bootstrap_skips_non_postgres():
    # on the SQLite test engine, bootstrap reports a skip rather than erroring
    from app.db.bootstrap_local import bootstrap
    from app.db.database import configure_test_database

    engine = configure_test_database()
    result = bootstrap(engine=engine)
    assert "skipped" in result
