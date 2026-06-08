from app.db.models import Chunk, Source
from app.graph.graph_store import (
    build_graph_from_db,
    expansion_contexts,
    load_graph,
    save_graph,
)


def _add(db, url: str, text: str) -> str:
    src = Source(url=url, hostname="x.mercubuana.ac.id", path="/", status="indexed", title="Judul")
    db.add(src)
    db.flush()
    ch = Chunk(
        source_id=src.id,
        chunk_text=text,
        chunk_index=0,
        source_type="html",
        meta={"url": url, "hostname": "x.mercubuana.ac.id"},
    )
    db.add(ch)
    db.flush()
    return str(ch.id)


def test_build_graph_from_db_indexes_entities(db):
    c1 = _add(db, "https://x.mercubuana.ac.id/a", "Teknik Informatika di Fakultas Ilmu Komputer")
    db.commit()
    g = build_graph_from_db(db)
    assert c1 in g.chunks_for_entity("Teknik Informatika")


def test_expansion_returns_neighbor_chunk_in_retriever_shape(db):
    c1 = _add(db, "https://x.mercubuana.ac.id/a", "Teknik Informatika berada di Fakultas Ilmu Komputer")
    c2 = _add(db, "https://x.mercubuana.ac.id/b", "Fakultas Ilmu Komputer memiliki akreditasi unggul")
    db.commit()
    g = build_graph_from_db(db)
    ctx = expansion_contexts(
        db, "akreditasi Teknik Informatika", g,
        root_domain="mercubuana.ac.id", limit=5, exclude_chunk_ids={c1},
    )
    ids = {c["chunk_id"] for c in ctx}
    assert c2 in ids and c1 not in ids
    sample = next(c for c in ctx if c["chunk_id"] == c2)
    for key in ("chunk_text", "url", "title", "score", "hostname", "source_type", "discovery_source"):
        assert key in sample
    assert sample["discovery_source"] == "graph_expand"


def test_expansion_empty_without_query_entities(db):
    _add(db, "https://x.mercubuana.ac.id/a", "Teknik Informatika di Fakultas Ilmu Komputer")
    db.commit()
    g = build_graph_from_db(db)
    assert expansion_contexts(db, "berapa biaya kuliah?", g, root_domain="mercubuana.ac.id", limit=5) == []


def test_save_and_load_roundtrip(db, tmp_path):
    _add(db, "https://x.mercubuana.ac.id/a", "Teknik Informatika di Fakultas Ilmu Komputer")
    db.commit()
    g = build_graph_from_db(db)
    path = str(tmp_path / "graph.json")
    save_graph(g, path)
    g2 = load_graph(path)
    assert g2 is not None
    assert g2.chunks_for_entity("Teknik Informatika") == g.chunks_for_entity("Teknik Informatika")


def test_load_missing_returns_none(tmp_path):
    assert load_graph(str(tmp_path / "does-not-exist.json")) is None
