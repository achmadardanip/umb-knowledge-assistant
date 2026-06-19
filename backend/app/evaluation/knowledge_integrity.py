"""Phase 14 P5 — knowledge-base integrity audit.

Verifies the combined local pgvector KB has no missing embeddings, no orphan
chunks/sources, intact provenance, and in-scope source URLs.

    python -m app.evaluation.knowledge_integrity --out ../reports/knowledge_integrity_report.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import text

from app.db.database import get_session_local


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../reports/knowledge_integrity_report.json")
    args = ap.parse_args()

    db = get_session_local()()
    s = lambda q: db.execute(text(q)).scalar()
    try:
        total_chunks = s("SELECT count(*) FROM chunks")
        embedded = s("SELECT count(DISTINCT chunk_id) FROM chunk_embeddings")
        missing_embeddings = s(
            "SELECT count(*) FROM chunks c "
            "WHERE NOT EXISTS (SELECT 1 FROM chunk_embeddings e WHERE e.chunk_id=c.id)"
        )
        # source_id is never null, but some chunks reference a source row that was
        # pruned earlier; their provenance survives via the chunk metadata url
        # (the retriever resolves meta.url OR source.url). So a dangling FK is not
        # a provenance loss — track it separately from true orphans.
        dangling_source_fk = s(
            "SELECT count(*) FROM chunks c "
            "WHERE NOT EXISTS (SELECT 1 FROM sources s WHERE s.id=c.source_id)"
        )
        orphan_chunks_no_source = s(
            "SELECT count(*) FROM chunks c "
            "WHERE NOT EXISTS (SELECT 1 FROM sources s WHERE s.id=c.source_id) "
            "AND (c.metadata->>'url') IS NULL"
        )
        orphan_embeddings = s(
            "SELECT count(*) FROM chunk_embeddings e "
            "WHERE NOT EXISTS (SELECT 1 FROM chunks c WHERE c.id=e.chunk_id)"
        )
        total_sources = s("SELECT count(*) FROM sources")
        orphan_sources = s(
            "SELECT count(*) FROM sources s "
            "WHERE NOT EXISTS (SELECT 1 FROM chunks c WHERE c.source_id=s.id)"
        )
        # Provenance = resolvable to a URL via the source row OR the chunk metadata.
        chunks_with_provenance = s(
            "SELECT count(*) FROM chunks c "
            "WHERE (c.metadata->>'url') IS NOT NULL "
            "OR EXISTS (SELECT 1 FROM sources s WHERE s.id=c.source_id "
            "           AND s.url IS NOT NULL AND length(s.url) > 0)"
        )
        out_of_scope_sources = s(
            "SELECT count(*) FROM sources WHERE url IS NOT NULL "
            "AND url NOT LIKE '%mercubuana.ac.id%'"
        )
        noncontent_browse_chunks = s(
            "SELECT count(*) FROM chunks c JOIN sources s ON c.source_id=s.id "
            "WHERE s.url ~ '/view/(subjects|creators|year|divisions|types)'"
        )

        # Entity-table integrity.
        ent = {
            t: s(f"SELECT count(*) FROM {t}")
            for t in ("umb_faculties", "umb_study_programs", "umb_campuses",
                      "umb_scholarships", "umb_contacts", "umb_services", "umb_faqs")
        }
        programs_orphan_faculty = s(
            "SELECT count(*) FROM umb_study_programs p WHERE p.faculty_name IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM umb_faculties f WHERE f.name=p.faculty_name)"
        )

        report = {
            "total_chunks": total_chunks,
            "embedded_chunks": embedded,
            "missing_embeddings": missing_embeddings,
            "orphan_chunks": orphan_chunks_no_source,
            "dangling_source_fk_provenance_via_meta": dangling_source_fk,
            "orphan_embeddings": orphan_embeddings,
            "total_sources": total_sources,
            "orphan_sources_no_chunks": orphan_sources,
            "chunks_with_provenance": chunks_with_provenance,
            "provenance_pct": round(100 * chunks_with_provenance / max(total_chunks, 1), 2),
            "out_of_scope_source_urls": out_of_scope_sources,
            "noncontent_browse_chunks": noncontent_browse_chunks,
            "entity_table_counts": ent,
            "programs_with_unresolved_faculty": programs_orphan_faculty,
            "targets": {
                "missing_embeddings": 0,
                "orphan_chunks": 0,
                "provenance_pct": 100.0,
            },
        }
    finally:
        db.close()

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for k in ("total_chunks", "missing_embeddings", "orphan_chunks", "orphan_embeddings",
              "orphan_sources_no_chunks", "provenance_pct", "out_of_scope_source_urls",
              "noncontent_browse_chunks"):
        print(f"  {k}: {report[k]}")


if __name__ == "__main__":
    main()
