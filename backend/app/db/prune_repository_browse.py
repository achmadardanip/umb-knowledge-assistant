"""Phase 14 P1/P5 — prune EPrints repository *browse-index* pages from the KB.

``repository.mercubuana.ac.id/view/{subjects,creators,year,divisions,types}/...``
are navigation/listing pages ("Browse by Subject", "Items where Year is 2014"),
not answer-bearing content. They were ingested during the Phase 7-9 coverage
crawl and account for ~48% of all chunks. With no FAQ/Tier-1 match they win the
vector layer for topical questions and drag ``official_top`` down (they are a
Tier-4 archive host, authority 0.25). Removing them is pure noise reduction — a
browse-index page can never be the correct answer to a user question.

Deletes, in FK-safe order, the chunk embeddings, chunks, and now-empty sources
(documents / segments / assets cascade). Run with --apply to commit; default is
a dry run that only reports counts.

    python -m app.db.prune_repository_browse            # dry run
    python -m app.db.prune_repository_browse --apply    # delete
"""

from __future__ import annotations

import argparse

from sqlalchemy import text

from app.db.database import get_session_local

_LIKE = "%repository.mercubuana.ac.id/view/%"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="commit the deletions")
    args = ap.parse_args()

    db = get_session_local()()
    try:
        scalar = lambda q: db.execute(text(q), {"p": _LIKE}).scalar()
        before_chunks = scalar("SELECT count(*) FROM chunks")
        sources = scalar("SELECT count(*) FROM sources WHERE url LIKE :p")
        chunks = scalar(
            "SELECT count(*) FROM chunks c JOIN sources s ON c.source_id=s.id WHERE s.url LIKE :p"
        )
        embs = scalar(
            "SELECT count(*) FROM chunk_embeddings e JOIN chunks c ON e.chunk_id=c.id "
            "JOIN sources s ON c.source_id=s.id WHERE s.url LIKE :p"
        )
        print(f"total chunks (before): {before_chunks}")
        print(f"repository /view/ browse  sources={sources}  chunks={chunks}  embeddings={embs}")

        if not args.apply:
            print("dry run — pass --apply to delete")
            return

        db.execute(text(
            "DELETE FROM chunk_embeddings WHERE chunk_id IN ("
            "  SELECT c.id FROM chunks c JOIN sources s ON c.source_id=s.id WHERE s.url LIKE :p)"
        ), {"p": _LIKE})
        db.execute(text(
            "DELETE FROM chunks WHERE source_id IN (SELECT id FROM sources WHERE url LIKE :p)"
        ), {"p": _LIKE})
        # documents / extracted_segments / source_assets cascade on source delete.
        deleted_sources = db.execute(text(
            "DELETE FROM sources WHERE url LIKE :p"
        ), {"p": _LIKE}).rowcount
        db.commit()

        after_chunks = scalar("SELECT count(*) FROM chunks")
        print(f"deleted sources={deleted_sources}  chunks_removed={before_chunks - after_chunks}")
        print(f"total chunks (after): {after_chunks}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
