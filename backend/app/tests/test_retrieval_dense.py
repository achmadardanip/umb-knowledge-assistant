from app.db.models import Chunk, Document, Source
from app.retrieval.dense import cosine_similarity, dense_search


def test_cosine_similarity_basic_cases():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine_similarity([], [1.0, 0.0]) == 0.0


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
            token_count=5,
            source_type="html",
            embedding=embedding,
            meta={"url": url, "hostname": hostname, "source_type": "html"},
        )
    )
    db.commit()


def test_dense_search_returns_nearest_by_cosine(db):
    _insert_chunk(db, url="https://lib.mercubuana.ac.id/a", hostname="lib.mercubuana.ac.id", text="uang kuliah", embedding=[1.0, 0.0, 0.0])
    _insert_chunk(db, url="https://lib.mercubuana.ac.id/b", hostname="lib.mercubuana.ac.id", text="jadwal", embedding=[0.0, 1.0, 0.0])

    results = dense_search(db, [0.9, 0.1, 0.0], top_k=1)

    assert len(results) == 1
    assert results[0]["url"] == "https://lib.mercubuana.ac.id/a"


def test_dense_search_excludes_out_of_scope_host(db):
    _insert_chunk(db, url="https://evil.com/x", hostname="evil.com", text="x", embedding=[1.0, 0.0])
    assert dense_search(db, [1.0, 0.0], top_k=5) == []
