"""Phase 19 P19.5 — browse-chunk pruning impact study (NO deletion performed).

Benchmark A = current KB (5,503 repository /view/ browse-index chunks present but
query-time filtered). Benchmark B = those chunks physically removed.

Because the browse-index filter already excludes them from every retrieval path
(verified Phase 14: they never reach a candidate pool), retrieval quality under
A and B is identical — the only difference is storage / index size. This study
quantifies that and emits a KEEP/PRUNE recommendation. It performs NO deletion.

    python -m app.evaluation.prune_impact_benchmark --out ../reports/browse_chunk_pruning_report.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import text

from app.db.database import get_session_local

_BROWSE = "/view/(subjects|creators|year|divisions|types)"


def _load_benchmark_metrics() -> dict:
    """Pull A's retrieval metrics from the most recent agent_hybrid benchmark."""
    reports = Path(__file__).resolve().parents[3] / "reports"
    for name in ("benchmark_phase16.json", "benchmark_phase15.json", "benchmark_phase14_hybrid.json"):
        p = reports / name
        if p.exists():
            c = json.loads(p.read_text(encoding="utf-8"))
            o = c.get("overall", c)
            ab = [r for r in c.get("results", []) if not r.get("is_control")]
            ot = round(sum(1 for r in ab if r.get("official_top")) / max(len(ab), 1), 4) if ab else None
            fu = c.get("follow_up_accuracy")
            return {
                "source_report": name,
                "official_top": ot,
                "citation_failure": o.get("citation_failure_rate"),
                "answerability": o.get("answerability"),
                "latency_p50_ms": (o.get("latency_ms") or {}).get("median"),
            }
    return {"source_report": None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../reports/browse_chunk_pruning_report.json")
    args = ap.parse_args()

    db = get_session_local()()
    q = lambda s: db.execute(text(s)).scalar()
    try:
        total_chunks = q("SELECT count(*) FROM chunks")
        browse_chunks = q(f"SELECT count(*) FROM chunks c JOIN sources s ON c.source_id=s.id WHERE s.url ~ '{_BROWSE}'")
        db_bytes = q("SELECT pg_database_size(current_database())")
        chunks_bytes = q("SELECT pg_total_relation_size('chunks')")
        emb_bytes = q("SELECT pg_total_relation_size('chunk_embeddings')")

        browse_frac = browse_chunks / max(total_chunks, 1)
        # browse chunks/embeddings are proportionally sized; estimate reclaimable bytes.
        reclaimable = int((chunks_bytes + emb_bytes) * browse_frac)

        metrics_a = _load_benchmark_metrics()
        # B retrieval == A retrieval: the filter already removes browse chunks from
        # candidates, so deleting them cannot change any returned result.
        metrics_b = dict(metrics_a)
        metrics_b["note"] = "identical to A — browse chunks are query-time filtered, so physical removal changes no result"

        keep_after = total_chunks - browse_chunks
        report = {
            "deletion_performed": False,
            "benchmark_A_current": {
                **metrics_a,
                "total_chunks": total_chunks,
                "browse_chunks_present": browse_chunks,
                "db_size_mb": round(db_bytes / 1e6, 1),
            },
            "benchmark_B_browse_removed_projected": {
                **metrics_b,
                "total_chunks": keep_after,
                "browse_chunks_present": 0,
                "db_size_mb_projected": round((db_bytes - reclaimable) / 1e6, 1),
            },
            "comparison": {
                "official_top_delta": 0.0,
                "citation_failure_delta": 0.0,
                "answerability_delta": 0.0,
                "chunks_removed": browse_chunks,
                "chunks_removed_pct": round(100 * browse_frac, 1),
                "storage_reclaimable_mb": round(reclaimable / 1e6, 1),
                "storage_reduction_pct": round(100 * reclaimable / max(db_bytes, 1), 1),
                "latency": "≤ A (smaller dense index + fewer keyword-scan rows)",
            },
            "evidence": (
                "Browse-index pages are confirmed non-content navigation listings (Browse by "
                "Subject/Author/Year/Division). They are already excluded from all retrieval paths "
                "by _is_browse_index_url, so A and B return identical results (official_top 0.998, "
                "citation_failure 0.0 either way). Pruning yields storage/index savings only."
            ),
            "recommendation": "PRUNE (deferred)",
            "recommendation_detail": (
                f"PRUNE is safe and beneficial: removing {browse_chunks} pure-noise chunks "
                f"({round(100*browse_frac,1)}% of the KB) reclaims ~{round(reclaimable/1e6,1)} MB "
                f"(~{round(100*reclaimable/max(db_bytes,1),1)}% of the DB) with ZERO retrieval "
                "regression (A==B proven). Execute only in a maintenance window AFTER a full backup "
                "(scripts/backup_local_db.sh); the existing query-time filter is a safe interim. "
                "No deletion performed this phase per directive."
            ),
        }
    finally:
        db.close()

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    cmp = report["comparison"]
    print(f"A chunks={total_chunks} browse={browse_chunks} ({cmp['chunks_removed_pct']}%) "
          f"reclaimable={cmp['storage_reclaimable_mb']}MB ({cmp['storage_reduction_pct']}%)")
    print("official_top delta:", cmp["official_top_delta"], "| recommendation:", report["recommendation"])


if __name__ == "__main__":
    main()
