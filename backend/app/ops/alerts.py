"""Phase 25 P25.2/P25.3 — operational alerting.

Evaluates the production health conditions from live DB state + the latest benchmark
report and returns active alerts. Consumed by GET /system/alerts and the ops dashboard.
Pure read-only; never mutates data.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

_REPORTS = Path(__file__).resolve().parents[3] / "reports"

# Thresholds (tunable).
OFFICIAL_TOP_MIN = 0.99
CITATION_FAILURE_MAX = 0.01
STALE_SOURCES_MAX = 50
CRAWL_FAILURE_MAX = 0


@dataclass
class Alert:
    id: str
    severity: str          # critical | high | medium | low
    category: str          # retrieval | crawl | database | embeddings | freshness
    message: str
    value: object = None
    threshold: object = None


def _scalar(db: Session, q: str):
    try:
        return db.execute(text(q)).scalar()
    except Exception:
        return None


def _latest_benchmark() -> dict | None:
    cands = sorted(_REPORTS.glob("benchmark_phase*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in cands:
        try:
            c = json.loads(p.read_text(encoding="utf-8"))
            o = c.get("overall", c)
            ab = [r for r in c.get("results", []) if not r.get("is_control")]
            ot = round(sum(1 for r in ab if r.get("official_top")) / max(len(ab), 1), 4) if ab else None
            return {"official_top": ot, "citation_failure": o.get("citation_failure_rate"), "file": p.name}
        except Exception:
            continue
    return None


def evaluate_alerts(db: Session) -> list[Alert]:
    alerts: list[Alert] = []

    # database health
    chunks = _scalar(db, "SELECT count(*) FROM chunks")
    if chunks is None:
        alerts.append(Alert("db_unreachable", "critical", "database", "Database unreachable"))
        return alerts
    if chunks == 0:
        alerts.append(Alert("kb_empty", "critical", "database", "Knowledge base is empty (0 chunks)", chunks, ">0"))

    # embedding failures
    missing = _scalar(db, "SELECT count(*) FROM chunks c WHERE NOT EXISTS "
                          "(SELECT 1 FROM chunk_embeddings e WHERE e.chunk_id=c.id)") or 0
    if missing > 0:
        alerts.append(Alert("missing_embeddings", "high", "embeddings",
                            f"{missing} chunks are missing embeddings", missing, 0))

    # crawl failures
    try:
        failed = _scalar(db, "SELECT count(*) FROM crawl_registry WHERE crawl_status='failed'") or 0
        if failed > CRAWL_FAILURE_MAX:
            alerts.append(Alert("crawl_failures", "high", "crawl",
                                f"{failed} URLs failed to crawl", failed, CRAWL_FAILURE_MAX))
    except Exception:
        pass

    # stale source growth
    stale = _scalar(db, "SELECT count(*) FROM sources WHERE EXTRACT(DAY FROM now()-fetched_at) > 180") or 0
    if stale > STALE_SOURCES_MAX:
        alerts.append(Alert("stale_sources", "medium", "freshness",
                            f"{stale} sources are stale (>180d)", stale, STALE_SOURCES_MAX))

    # retrieval benchmark drop
    bench = _latest_benchmark()
    if bench and bench.get("official_top") is not None and bench["official_top"] < OFFICIAL_TOP_MIN:
        alerts.append(Alert("retrieval_regression", "critical", "retrieval",
                            f"official_top {bench['official_top']} < {OFFICIAL_TOP_MIN} ({bench['file']})",
                            bench["official_top"], OFFICIAL_TOP_MIN))
    if bench and (bench.get("citation_failure") or 0) > CITATION_FAILURE_MAX:
        alerts.append(Alert("citation_regression", "critical", "retrieval",
                            f"citation_failure {bench['citation_failure']} > {CITATION_FAILURE_MAX}",
                            bench["citation_failure"], CITATION_FAILURE_MAX))

    return alerts


def alerts_payload(db: Session) -> dict:
    alerts = [asdict(a) for a in evaluate_alerts(db)]
    by_sev = {s: sum(1 for a in alerts if a["severity"] == s) for s in ("critical", "high", "medium", "low")}
    return {
        "active_alerts": alerts,
        "alert_count": len(alerts),
        "by_severity": by_sev,
        "status": "critical" if by_sev["critical"] else "warning" if alerts else "ok",
        "coverage": {  # P25.2 conditions monitored (alert_coverage = 100%)
            "retrieval_benchmark_drop": True, "crawl_failures": True,
            "database_health": True, "embedding_failures": True, "stale_source_growth": True,
        },
    }
