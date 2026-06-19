"""Phase 14 P4 — typed GraphRAG audit.

Builds the in-memory typed property graph from the umb_* tables and reports node
counts, edge counts, orphan nodes, disconnected entities and duplicate entities
so we can verify GraphRAG adds relations rather than ambiguity.

    python -m app.evaluation.graph_audit --out ../reports/graph_audit_report.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from app.db.database import get_session_local
from app.graph.typed_graph_store import build_typed_graph_from_db


def audit(graph) -> dict:
    nodes = graph.nodes
    edges = graph.edges

    nodes_by_type = Counter(n.type for n in nodes.values())
    edges_by_rel = Counter(e.rel for e in edges)

    degree: dict[str, int] = defaultdict(int)
    for e in edges:
        degree[e.src] += 1
        degree[e.dst] += 1

    orphans = [
        {"id": n.id, "type": n.type, "name": n.name}
        for n in nodes.values() if degree[n.id] == 0
    ]

    # Dangling edges (endpoint missing) — should be 0 since add_edge guards them.
    dangling = [e.to_dict() for e in edges if e.src not in nodes or e.dst not in nodes]

    # Duplicate entities: distinct node ids that share the same (type, normalized
    # name). upsert_node dedupes by id (type:slug), so any collision here is a
    # genuine near-duplicate worth flagging.
    by_key: dict[tuple[str, str], list[str]] = defaultdict(list)
    for n in nodes.values():
        by_key[(n.type, n.name.strip().lower())].append(n.id)
    duplicates = {f"{k[0]}::{k[1]}": ids for k, ids in by_key.items() if len(ids) > 1}

    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes_by_type": dict(nodes_by_type),
        "edges_by_relation": dict(edges_by_rel),
        "orphan_node_count": len(orphans),
        "orphan_nodes": orphans[:50],
        "dangling_edge_count": len(dangling),
        "duplicate_entity_count": len(duplicates),
        "duplicate_entities": duplicates,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../reports/graph_audit_report.json")
    args = ap.parse_args()

    db = get_session_local()()
    try:
        graph = build_typed_graph_from_db(db)
    finally:
        db.close()

    report = audit(graph)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"nodes={report['node_count']} edges={report['edge_count']} "
          f"orphans={report['orphan_node_count']} dangling={report['dangling_edge_count']} "
          f"duplicates={report['duplicate_entity_count']}")
    print("nodes_by_type:", report["nodes_by_type"])
    print("edges_by_relation:", report["edges_by_relation"])


if __name__ == "__main__":
    main()
