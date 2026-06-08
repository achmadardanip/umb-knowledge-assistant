from app.graph.graph_index import KnowledgeGraph, build_graph


def test_links_entities_to_chunks():
    g = build_graph([
        ("c1", "Teknik Informatika berada di Fakultas Ilmu Komputer"),
        ("c2", "Akun SIA untuk mahasiswa"),
    ])
    assert "c1" in g.chunks_for_entity("Teknik Informatika")
    assert "c2" in g.chunks_for_entity("SIA")


def test_cooccurrence_creates_neighbors():
    g = build_graph([("c1", "Teknik Informatika di Fakultas Ilmu Komputer")])
    assert "Fakultas Ilmu Komputer" in g.neighbors("Teknik Informatika")


def test_related_chunk_ids_expands_through_neighbor():
    # c1 ties TI <-> FIK; c2 mentions only FIK. A query about TI should still reach c2.
    g = build_graph([
        ("c1", "Teknik Informatika berada di Fakultas Ilmu Komputer"),
        ("c2", "Fakultas Ilmu Komputer memiliki akreditasi unggul"),
        ("c3", "Beasiswa untuk semua mahasiswa"),
    ])
    related = g.related_chunk_ids("akreditasi Teknik Informatika", limit=5)
    assert "c1" in related
    assert "c2" in related      # reached via the TI–FIK edge (1 hop)
    assert "c3" not in related  # unrelated entity


def test_related_is_empty_without_query_entities():
    g = build_graph([("c1", "Teknik Informatika")])
    assert g.related_chunk_ids("berapa biaya kuliah?", limit=5) == []


def test_prune_drops_rare_unprotected_entities_and_edges():
    g = build_graph([
        ("c1", "RARE muncul sekali bersama Manajemen"),
        ("c2", "Manajemen disebut lagi"),
    ])
    assert "RARE" in g.neighbors("Manajemen")  # edge exists before prune
    g.prune(min_chunks=2, protected={"Manajemen"})
    assert g.chunks_for_entity("RARE") == set()      # rare, unprotected -> removed
    assert g.chunks_for_entity("Manajemen")          # protected -> kept
    assert "RARE" not in g.neighbors("Manajemen")    # dangling edge cleaned


def test_add_chunk_caps_entities():
    g = KnowledgeGraph()
    g.add_chunk("c1", "SIA SSO KRS KHS PMB", max_entities=2)
    # only the first 2 distinct entities are indexed
    indexed = [e for e in ("SIA", "SSO", "KRS", "KHS", "PMB") if g.chunks_for_entity(e)]
    assert len(indexed) == 2


def test_serialization_roundtrip():
    g = build_graph([
        ("c1", "Teknik Informatika di Fakultas Ilmu Komputer"),
        ("c2", "Fakultas Ilmu Komputer dan SIA"),
    ])
    g2 = KnowledgeGraph.from_dict(g.to_dict())
    assert g2.neighbors("Teknik Informatika") == g.neighbors("Teknik Informatika")
    assert g2.chunks_for_entity("Fakultas Ilmu Komputer") == g.chunks_for_entity("Fakultas Ilmu Komputer")
