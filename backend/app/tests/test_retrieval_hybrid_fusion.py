from app.db.models import Chunk, Document, Source
from app.retrieval.hybrid_retriever import HybridRetriever


class _FakeEmbedder:
    """Maps everything to the same vector, so the query is 'near' the seeded chunk."""

    def embed_query(self, query: str):
        return [1.0, 0.0, 0.0]

    def embed_texts(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


def _insert_chunk(db, *, url, hostname, text, embedding):
    source = Source(url=url, title="t", hostname=hostname, path="/p", status="indexed", discovery_source="katana")
    db.add(source)
    db.flush()
    document = Document(source_id=source.id, raw_text=text, cleaned_text=text)
    db.add(document)
    db.flush()
    db.add(
        Chunk(
            document_id=document.id,
            source_id=source.id,
            chunk_text=text,
            chunk_index=0,
            token_count=6,
            source_type="html",
            embedding=embedding,
            meta={"url": url, "hostname": hostname, "source_type": "html"},
        )
    )
    db.commit()


def test_hybrid_dense_finds_semantic_match_that_keyword_misses(db):
    # The chunk shares no query keywords ("biaya pendidikan") but is semantically near.
    _insert_chunk(
        db,
        url="https://pmb.mercubuana.ac.id/x",
        hostname="pmb.mercubuana.ac.id",
        text="Uang kuliah tunggal mahasiswa program reguler.",
        embedding=[1.0, 0.0, 0.0],
    )

    keyword_only = HybridRetriever(db, dense_enabled=False).search("ongkos pendidikan", top_k=5)
    assert all(context["url"] != "https://pmb.mercubuana.ac.id/x" for context in keyword_only)

    hybrid = HybridRetriever(db, embedder=_FakeEmbedder(), dense_enabled=True).search("ongkos pendidikan", top_k=5)
    assert any(context["url"] == "https://pmb.mercubuana.ac.id/x" for context in hybrid)
