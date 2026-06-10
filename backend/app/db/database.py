from __future__ import annotations

import json
from collections.abc import Generator
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.paths import project_path
from app.db.models import Base


def _json_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)


def _json_dumps(obj) -> str:
    return json.dumps(obj, default=_json_default)


# JSONB writes must tolerate datetime/date values (e.g. source freshness
# timestamps) on both the psycopg (Postgres) and SQLAlchemy (SQLite) paths.
try:
    from psycopg.types.json import set_json_dumps

    set_json_dumps(_json_dumps)
except Exception:
    pass


_engine = None
_session_local: sessionmaker[Session] | None = None


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    return database_url


def _engine_kwargs(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}, "json_serializer": _json_dumps}
    # Supabase's transaction-mode pooler does not persist psycopg3 prepared
    # statements across reused connections ("prepared statement _pgN does not
    # exist"); disabling auto-prepare makes pooled writes (crawl/backfill) safe.
    return {"pool_pre_ping": True, "json_serializer": _json_dumps, "connect_args": {"prepare_threshold": None}}


def _create_verified_engine(database_url: str):
    engine = create_engine(normalize_database_url(database_url), **_engine_kwargs(database_url))
    with engine.connect() as connection:
        connection.execute(text("select 1"))
    return engine


def _local_sqlite_url() -> str | None:
    settings = get_settings()
    if not settings.local_sqlite_fallback_enabled:
        return None
    configured_path = Path(settings.local_sqlite_path)
    db_path = configured_path if configured_path.is_absolute() else project_path("backend", configured_path.as_posix())
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}"


def get_engine():
    global _engine
    if _engine is None:
        database_url = get_settings().database_url
        if not database_url:
            fallback_url = _local_sqlite_url()
            if not fallback_url:
                raise RuntimeError("DATABASE_URL is not configured.")
            _engine = create_engine(fallback_url, **_engine_kwargs(fallback_url))
            Base.metadata.create_all(_engine)
            return _engine
        try:
            _engine = _create_verified_engine(database_url)
        except OperationalError:
            fallback_url = _local_sqlite_url()
            if not fallback_url:
                raise
            _engine = create_engine(fallback_url, **_engine_kwargs(fallback_url))
            Base.metadata.create_all(_engine)
    return _engine


def get_session_local() -> sessionmaker[Session]:
    global _session_local
    if _session_local is None:
        _session_local = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
            expire_on_commit=False,
        )
    return _session_local


def get_db() -> Generator[Session, None, None]:
    db = get_session_local()()
    try:
        yield db
    finally:
        db.close()


def configure_test_database(database_url: str = "sqlite:///:memory:"):
    global _engine, _session_local
    _engine = create_engine(database_url, connect_args={"check_same_thread": False})
    _session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=_engine,
        expire_on_commit=False,
    )
    return _engine
