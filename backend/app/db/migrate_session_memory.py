"""Phase 24 P24.1 — make chat_memories carry structured per-key session entity memory.

Adds `memory_key` and `memory_value` columns (additive, backward compatible) so the
PostgresProvider can store one row per entity kind (faculty / program / dean / kaprodi /
accreditation / service / topic). `importance_score` is reused as `confidence`,
`expires_at` already exists for TTL. Idempotent.

    python -m app.db.migrate_session_memory
"""

from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


def migrate(engine=None) -> dict:
    from app.db.database import get_engine

    engine = engine or get_engine()
    if engine.dialect.name != "postgresql":
        return {"skipped": f"non-postgresql backend ({engine.dialect.name})"}

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE chat_memories ADD COLUMN IF NOT EXISTS memory_key text"))
        conn.execute(text("ALTER TABLE chat_memories ADD COLUMN IF NOT EXISTS memory_value text"))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_chat_memories_session_key "
            "ON chat_memories (session_id, memory_key) WHERE is_active"
        ))
    with engine.begin() as conn:
        n = conn.execute(text("SELECT count(*) FROM chat_memories")).scalar()
    return {"chat_memories_rows": n, "columns_added": ["memory_key", "memory_value"]}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(migrate())


if __name__ == "__main__":
    main()
