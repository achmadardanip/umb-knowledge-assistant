"""Build the UMB knowledge graph from indexed chunks and persist it to JSON.

Usage:
    python -m app.graph.build_graph

Run after each (incremental) crawl/index so relation-aware retrieval stays current.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.db.database import get_session_local
from app.graph.graph_store import build_graph_from_db, save_graph


def main() -> None:
    settings = get_settings()
    session = get_session_local()()
    try:
        graph = build_graph_from_db(session)
    finally:
        session.close()
    save_graph(graph, settings.graph_path)
    print(f"Knowledge graph built: {graph.entity_count} entities -> {settings.graph_path}")


if __name__ == "__main__":
    main()
