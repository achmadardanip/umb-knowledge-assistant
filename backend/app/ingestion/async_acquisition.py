"""
Batch 4 — asynchronous knowledge acquisition.

When a live-web (Tavily) result answers a question, the user is answered FIRST;
acquisition into the KB (persist sources/chunks + record the discovery cache) runs
in a background daemon thread with its OWN DB session, so it never blocks or breaks
the response. A later similar question is then served from the indexed KB.
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


def _acquire(question: str, web_contexts: list[dict]) -> None:
    from app.db.database import get_session_local
    from app.ingestion.web_kb_ingest import persist_web_contexts
    from app.rag.discovery_cache import record_discoveries

    session_factory = get_session_local()
    db = session_factory()
    try:
        chunks = persist_web_contexts(db, web_contexts)
        record_discoveries(db, question, web_contexts, indexed=chunks > 0)
        logger.info("async KB acquisition: %s chunks persisted for %r", chunks, question[:80])
    except Exception as exc:  # never propagate from the background thread
        logger.warning("async KB acquisition failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


def schedule_kb_acquisition(question: str, web_contexts: list[dict]) -> bool:
    """Spawn a background thread to persist live-web contexts + record the discovery
    cache. Returns True if a job was scheduled. Non-blocking; safe to call inline."""
    web_used = [c for c in (web_contexts or []) if (c.get("url") and (c.get("chunk_text") or c.get("content")))]
    if not web_used:
        return False
    thread = threading.Thread(
        target=_acquire,
        args=(question, web_used),
        name="kb-acquisition",
        daemon=True,
    )
    thread.start()
    return True
