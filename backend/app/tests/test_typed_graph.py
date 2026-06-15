"""Tests for Phase 4 — Typed University GraphRAG."""

from __future__ import annotations

import pytest

from app.ingestion.entity_extractor import seed_entities
from app.graph.typed_graph import (
    FACULTY_HAS_DEAN,
    FACULTY_HAS_PROGRAM,
    NODE_FACULTY,
    NODE_PROGRAM,
    PROGRAM_BELONGS_TO_FACULTY,
    TypedGraph,
    node_id,
    slugify,
)
from app.graph.typed_graph_store import (
    build_typed_graph_from_db,
    load_typed_graph,
    save_typed_graph,
    typed_expansion_contexts,
)


@pytest.fixture()
def graph_db(db):
    seed_entities(db, confidence=0.85)
    return db


@pytest.fixture()
def typed_graph(graph_db):
    return build_typed_graph_from_db(graph_db)


# ---------------------------------------------------------------------------
# Structure primitives
# ---------------------------------------------------------------------------


def test_slugify_normalizes():
    assert slugify("Fakultas Ilmu Komputer") == "fakultas-ilmu-komputer"
    assert slugify("Teknik Informatika (S1)") == "teknik-informatika-s1"


def test_node_id_is_typed():
    assert node_id(NODE_FACULTY, "Fakultas Teknik") == "faculty:fakultas-teknik"


def test_upsert_node_merges_attrs_and_aliases():
    g = TypedGraph()
    nid = g.upsert_node(NODE_FACULTY, "Fakultas Teknik", attrs={"dean": None}, aliases=["FT"])
    g.upsert_node(NODE_FACULTY, "Fakultas Teknik", attrs={"dean": "Dr. X"}, aliases=["Teknik"])
    assert g.node_count == 1
    node = g.nodes[nid]
    assert node.attrs["dean"] == "Dr. X"
    assert "FT" in node.aliases and "Teknik" in node.aliases


def test_add_edge_requires_both_nodes():
    g = TypedGraph()
    a = g.upsert_node(NODE_FACULTY, "Fak A")
    g.add_edge(a, FACULTY_HAS_PROGRAM, "program:missing")  # dst missing → ignored
    assert g.edge_count == 0


def test_match_nodes_word_boundary():
    g = TypedGraph()
    g.upsert_node(NODE_FACULTY, "Fakultas Ilmu Komputer", aliases=["FASILKOM"])
    assert g.match_nodes("siapa dekan fasilkom?")[0].name == "Fakultas Ilmu Komputer"
    # 'komputerisasi' must NOT match 'komputer' (word boundary)
    assert g.match_nodes("apa itu komputerisasi") == []


# ---------------------------------------------------------------------------
# Build from DB
# ---------------------------------------------------------------------------


def test_build_creates_faculty_and_program_nodes(typed_graph):
    counts = typed_graph.type_counts()
    assert counts.get(NODE_FACULTY, 0) == 7
    assert counts.get(NODE_PROGRAM, 0) >= 18


def test_build_creates_faculty_has_program_edges(typed_graph):
    fid = node_id(NODE_FACULTY, "Fakultas Ilmu Komputer")
    programs = typed_graph.neighbors(fid, FACULTY_HAS_PROGRAM, direction="out")
    names = {p.attrs.get("program_name") for p in programs}
    assert "Teknik Informatika" in names
    assert "Sistem Informasi" in names


def test_program_belongs_to_faculty_inverse(typed_graph):
    # Find the Teknik Informatika program node
    ti = next(n for n in typed_graph.nodes.values()
              if n.type == NODE_PROGRAM and n.attrs.get("program_name") == "Teknik Informatika")
    faculties = typed_graph.neighbors(ti.id, PROGRAM_BELONGS_TO_FACULTY, direction="out")
    assert faculties and faculties[0].name == "Fakultas Ilmu Komputer"


def test_build_has_edges(typed_graph):
    assert typed_graph.edge_count > 0


# ---------------------------------------------------------------------------
# Persistence round-trip
# ---------------------------------------------------------------------------


def test_save_load_roundtrip(typed_graph, tmp_path):
    path = str(tmp_path / "typed.json")
    save_typed_graph(typed_graph, path)
    loaded = load_typed_graph(path)
    assert loaded is not None
    assert loaded.node_count == typed_graph.node_count
    assert loaded.edge_count == typed_graph.edge_count
    # adjacency survives
    fid = node_id(NODE_FACULTY, "Fakultas Teknik")
    assert loaded.neighbors(fid, FACULTY_HAS_PROGRAM, direction="out")


def test_load_missing_returns_none(tmp_path):
    assert load_typed_graph(str(tmp_path / "nope.json")) is None


# ---------------------------------------------------------------------------
# Relational retrieval
# ---------------------------------------------------------------------------


def test_expansion_faculty_lists_programs(typed_graph):
    ctxs = typed_expansion_contexts("program studi apa saja di Fakultas Teknik?", typed_graph)
    assert ctxs
    text = ctxs[0]["chunk_text"]
    assert "program studi" in text.lower()
    assert "Teknik Mesin" in text or "Teknik Sipil" in text
    assert ctxs[0]["source_type"] == "graph"
    assert ctxs[0]["score"] == 9.0


def test_expansion_program_resolves_faculty(typed_graph):
    ctxs = typed_expansion_contexts("Teknik Informatika ada di fakultas apa?", typed_graph)
    assert ctxs
    joined = " ".join(c["chunk_text"] for c in ctxs)
    assert "Fakultas Ilmu Komputer" in joined


def test_expansion_empty_for_unrelated(typed_graph):
    assert typed_expansion_contexts("bagaimana cuaca hari ini", typed_graph) == []


def test_expansion_respects_limit(typed_graph):
    ctxs = typed_expansion_contexts(
        "Fakultas Teknik Fakultas Ilmu Komputer Fakultas Psikologi Fakultas Ekonomi dan Bisnis",
        typed_graph,
        limit=2,
    )
    assert len(ctxs) <= 2


def test_expansion_context_has_source_url(typed_graph):
    ctxs = typed_expansion_contexts("program di Fakultas Ilmu Komputer", typed_graph)
    assert ctxs
    assert ctxs[0]["url"].startswith("http")
    assert "mercubuana.ac.id" in ctxs[0]["hostname"]


# ---------------------------------------------------------------------------
# Agent integration
# ---------------------------------------------------------------------------


def test_agent_typed_graph_surfaces_relation(graph_db, monkeypatch):
    from app.agent import umb_agent

    class _StubRetriever:
        def __init__(self, db, root_domain="mercubuana.ac.id", **kwargs):
            pass

        def search(self, query, top_k=5, **kwargs):
            return [{
                "chunk_id": "c1", "chunk_text": "info", "url": "https://ft.mercubuana.ac.id/x",
                "title": "x", "score": 2.0, "hostname": "ft.mercubuana.ac.id", "source_type": "html",
            }]

    steps: list = []
    result = umb_agent.run_umb_agent(
        db=graph_db,
        query="program studi apa saja di Fakultas Teknik?",
        retrieval_mode="indexed",
        top_k=5,
        root_domain="mercubuana.ac.id",
        emit=lambda *a: steps.append(a),
        indexed_retriever_cls=_StubRetriever,
    )
    # A typed-graph relational context should be present and outrank the chunk
    types = [c.get("source_type") for c in result.contexts]
    assert "graph" in types
    graph_idx = types.index("graph")
    html_idx = types.index("html") if "html" in types else len(types)
    assert graph_idx < html_idx
    assert any(s[0] == "typed_graph" for s in steps)
