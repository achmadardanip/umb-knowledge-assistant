"""
v3 P5 — pre-prune safety backup + baseline metrics for the one-time chunk metadata
prune (see ``app.ingestion.metadata_pruning`` / ``007_prune_chunk_metadata.sql``).

Because the prune is DESTRUCTIVE & IRREVERSIBLE (stripped keys live nowhere else),
this exports ``(id, metadata)`` for every row the prune will rewrite — i.e. the rows
whose serialized metadata exceeds ``min_len`` — to a gzipped JSON-lines file. That is
the complete recovery set for this operation. A full cluster ``pg_dump`` is avoided on
purpose: the Supabase project is already over its egress budget and the daily managed
backups cover full-cluster recovery; here we only need the column the prune mutates.

Run BEFORE the prune:

    PYTHONPATH=. .venv/Scripts/python.exe -m app.db.prune_backup

It writes ``reports/prune_backup_<UTC>.jsonl.gz`` + ``reports/prune_baseline_<UTC>.json``
and prints the baseline metrics (row count, bloated rows, avg/max metadata chars).
"""

from __future__ import annotations

import gzip
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

logger = logging.getLogger(__name__)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def baseline_metrics(db, *, min_len: int = 600) -> dict:
    total, avg_chars, max_chars = db.execute(
        text(
            "SELECT count(*), round(avg(length(metadata::text))), max(length(metadata::text)) "
            "FROM chunks WHERE metadata IS NOT NULL"
        )
    ).fetchone()
    bloated, bloated_bytes = db.execute(
        text(
            "SELECT count(*), COALESCE(sum(length(metadata::text)), 0) "
            "FROM chunks WHERE metadata IS NOT NULL AND length(metadata::text) > :n"
        ),
        {"n": min_len},
    ).fetchone()
    return {
        "rows_with_metadata": int(total or 0),
        "avg_metadata_chars": float(avg_chars) if avg_chars is not None else None,
        "max_metadata_chars": int(max_chars) if max_chars is not None else None,
        "rows_bloated": int(bloated or 0),
        "bloated_total_chars": int(bloated_bytes or 0),
        "min_len_threshold": min_len,
    }


def export_backup(db, out_dir: Path, *, min_len: int = 600, batch: int = 2000) -> tuple[Path, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"prune_backup_{_utc_stamp()}.jsonl.gz"
    written = 0
    last_id = None
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        while True:
            if last_id is None:
                rows = db.execute(
                    text(
                        "SELECT id, metadata FROM chunks "
                        "WHERE metadata IS NOT NULL AND length(metadata::text) > :n "
                        "ORDER BY id LIMIT :lim"
                    ),
                    {"n": min_len, "lim": batch},
                ).fetchall()
            else:
                rows = db.execute(
                    text(
                        "SELECT id, metadata FROM chunks "
                        "WHERE metadata IS NOT NULL AND length(metadata::text) > :n AND id > :last "
                        "ORDER BY id LIMIT :lim"
                    ),
                    {"n": min_len, "lim": batch, "last": last_id},
                ).fetchall()
            if not rows:
                break
            for row_id, meta in rows:
                fh.write(json.dumps({"id": str(row_id), "metadata": meta}, ensure_ascii=False) + "\n")
                written += 1
                last_id = row_id
    return path, written


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from app.db.database import get_session_local

    repo_root = Path(__file__).resolve().parents[3]
    reports = repo_root / "reports"

    db = get_session_local()()
    try:
        metrics = baseline_metrics(db)
        logger.info("pre-prune baseline: %s", metrics)
        backup_path, written = export_backup(db, reports)
        metrics["backup_file"] = backup_path.name
        metrics["backup_rows"] = written
        baseline_path = reports / f"prune_baseline_{_utc_stamp()}.json"
        baseline_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        logger.info("wrote %s rows to %s; baseline -> %s", written, backup_path, baseline_path)
    finally:
        db.close()


if __name__ == "__main__":
    main()
