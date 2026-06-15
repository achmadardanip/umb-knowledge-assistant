"""Build the typed UMB knowledge graph from the Phase-2 entity tables → JSON.

Usage (from backend/):
    PYTHONPATH=. .venv/Scripts/python.exe -m app.graph.build_typed_graph

Run after the entity extractor (``app.ingestion.entity_extractor``) so typed
relations stay current.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.db.database import get_session_local
from app.graph.typed_graph_store import build_typed_graph_from_db, save_typed_graph


def main() -> None:
    settings = get_settings()
    session = get_session_local()()
    try:
        graph = build_typed_graph_from_db(session)
    finally:
        session.close()
    save_typed_graph(graph, settings.typed_graph_path)
    print(
        f"Typed graph built: {graph.node_count} nodes / {graph.edge_count} edges "
        f"{graph.type_counts()} -> {settings.typed_graph_path}"
    )


if __name__ == "__main__":
    main()
