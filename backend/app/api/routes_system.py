"""Phase 19 P19.3 — operations / monitoring endpoints.

Read-only system observability so an administrator can spot any KB issue in
seconds: /system/health, /stats, /crawl, /freshness, /graph, /database.
All values are read live from PostgreSQL (never hardcoded).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.database import get_db

router = APIRouter(tags=["system"])


def _scalar(db: Session, q: str):
    try:
        return db.execute(text(q)).scalar()
    except Exception:
        return None


@router.get("/system/health")
def system_health(db: Session = Depends(get_db)) -> dict:
    db_ok = _scalar(db, "SELECT 1") == 1
    chunks = _scalar(db, "SELECT count(*) FROM chunks") or 0
    return {
        "status": "ok" if (db_ok and chunks > 0) else "degraded",
        "database": "up" if db_ok else "down",
        "chunks": chunks,
        "service": "UMB Knowledge Assistant",
    }


@router.get("/system/stats")
def system_stats(db: Session = Depends(get_db)) -> dict:
    ent_tables = ("umb_faculties", "umb_study_programs", "umb_campuses",
                  "umb_scholarships", "umb_contacts", "umb_services")
    return {
        "chunks": _scalar(db, "SELECT count(*) FROM chunks") or 0,
        "sources": _scalar(db, "SELECT count(*) FROM sources") or 0,
        "entities": sum(_scalar(db, f"SELECT count(*) FROM {t}") or 0 for t in ent_tables),
        "faculties": _scalar(db, "SELECT count(*) FROM umb_faculties") or 0,
        "programs": _scalar(db, "SELECT count(*) FROM umb_study_programs") or 0,
    }


@router.get("/system/crawl")
def system_crawl(db: Session = Depends(get_db)) -> dict:
    try:
        from app.crawl.incremental import registry_status
        s = registry_status(db)
        by_status = s.get("by_status", {})
        return {
            "available": True,
            "total_urls": s.get("total_urls", 0),
            "pending_urls": s.get("due_now", 0),
            "processed_urls": by_status.get("crawled", 0),
            "skipped_urls": by_status.get("skipped", 0),
            "failed_urls": s.get("failed", 0),
            "by_frequency": s.get("by_frequency", {}),
            "changed_last_7d": s.get("changed_last_7d", 0),
            "last_crawl": s.get("last_crawl"),
        }
    except Exception:
        return {"available": False}


@router.get("/system/freshness")
def system_freshness(db: Session = Depends(get_db)) -> dict:
    age = "EXTRACT(DAY FROM now() - fetched_at)"
    total = _scalar(db, "SELECT count(*) FROM sources") or 0
    verified_today = _scalar(db, "SELECT count(*) FROM sources WHERE last_verified_date >= now() - interval '1 day'") or 0
    stale = _scalar(db, f"SELECT count(*) FROM sources WHERE {age} > 180") or 0
    aging = _scalar(db, f"SELECT count(*) FROM sources WHERE {age} > 30 AND {age} <= 180") or 0
    oldest = _scalar(db, "SELECT min(fetched_at) FROM sources")
    newest = _scalar(db, "SELECT max(fetched_at) FROM sources")
    return {
        "total_sources": total,
        "verified_today": verified_today,
        "fresh_sources": total - aging - stale,
        "aging_sources": aging,
        "stale_sources": stale,
        "oldest_source": oldest.isoformat() if oldest else None,
        "newest_source": newest.isoformat() if newest else None,
    }


@router.get("/system/graph")
def system_graph(db: Session = Depends(get_db)) -> dict:
    try:
        from app.evaluation.graph_audit import audit
        from app.graph.typed_graph_store import build_typed_graph_from_db
        a = audit(build_typed_graph_from_db(db))
        return {
            "available": True,
            "nodes": a["node_count"],
            "edges": a["edge_count"],
            "orphan_nodes": a["orphan_node_count"],
            "dangling_edges": a["dangling_edge_count"],
            "duplicate_entities": a["duplicate_entity_count"],
            "nodes_by_type": a["nodes_by_type"],
        }
    except Exception:
        return {"available": False}


@router.get("/system/alerts")
def system_alerts(db: Session = Depends(get_db)) -> dict:
    """Phase 25 P25.3 — active operational alerts (retrieval regression, crawl
    failures, DB health, embedding failures, stale-source growth)."""
    try:
        from app.ops.alerts import alerts_payload
        return alerts_payload(db)
    except Exception as exc:
        return {"status": "unknown", "active_alerts": [], "alert_count": 0, "error": str(exc)[:120]}


@router.get("/system/database")
def system_database(db: Session = Depends(get_db)) -> dict:
    chunks = _scalar(db, "SELECT count(*) FROM chunks") or 0
    embeddings = _scalar(db, "SELECT count(DISTINCT chunk_id) FROM chunk_embeddings") or 0
    missing = _scalar(db, "SELECT count(*) FROM chunks c WHERE NOT EXISTS (SELECT 1 FROM chunk_embeddings e WHERE e.chunk_id=c.id)") or 0
    orphan = _scalar(db, "SELECT count(*) FROM chunks c WHERE NOT EXISTS (SELECT 1 FROM sources s WHERE s.id=c.source_id) AND (c.metadata->>'url') IS NULL") or 0
    db_size = _scalar(db, "SELECT pg_size_pretty(pg_database_size(current_database()))")
    return {
        "database_size": db_size,
        "chunks": chunks,
        "embeddings": embeddings,
        "missing_embeddings": missing,
        "orphan_chunks": orphan,
    }
