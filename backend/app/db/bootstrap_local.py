"""
v3 P6 — bootstrap a local Postgres (docker-compose) for fully-local deployment.

Creates the pgvector + pg_trgm extensions, all ORM tables, and the special
trigram / HNSW indexes — so the app runs without Supabase. Idempotent.

Usage (with LOCAL_POSTGRES_MODE=true, docker compose up -d postgres):
    PYTHONPATH=. .venv/Scripts/python.exe -m app.db.bootstrap_local
"""

from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

_EXTENSIONS = ("vector", "pg_trgm")

_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS ix_chunks_chunk_text_trgm ON chunks USING gin (chunk_text gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS ix_sources_title_trgm ON sources USING gin (title gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS ix_sources_url_trgm ON sources USING gin (url gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS ix_sources_path_trgm ON sources USING gin (path gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_embedding_hnsw "
    "ON chunk_embeddings USING hnsw (embedding vector_cosine_ops)",
)


def bootstrap(engine=None) -> dict:
    from app.db.database import get_engine
    from app.db.models import Base

    engine = engine or get_engine()
    if engine.dialect.name != "postgresql":
        return {"skipped": f"non-postgresql backend ({engine.dialect.name})"}

    # 1) extensions — each in its own committed tx (a combined tx rolls the
    #    extension back if a later statement fails).
    for ext in _EXTENSIONS:
        with engine.begin() as conn:
            conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS {ext}"))
        logger.info("extension ready: %s", ext)

    # 2) all ORM tables.
    Base.metadata.create_all(engine, checkfirst=True)
    logger.info("ORM tables created (checkfirst).")

    # 3) special indexes (trigram + HNSW), each in its own tx.
    created = 0
    for ddl in _INDEX_DDL:
        try:
            with engine.begin() as conn:
                conn.execute(text(ddl))
            created += 1
        except Exception as exc:
            logger.warning("index DDL skipped (%s): %s", ddl.split()[5], exc)
    return {"extensions": list(_EXTENSIONS), "tables": "created", "indexes": created}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from app.core.config import get_settings

    s = get_settings()
    logger.info("LOCAL_POSTGRES_MODE=%s database_url=%s", s.local_postgres_mode,
                (s.database_url or "").split("@")[-1])
    result = bootstrap()
    logger.info("bootstrap complete: %s", result)


if __name__ == "__main__":
    main()
