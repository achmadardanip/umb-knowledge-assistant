import pytest

from app.db.models import Chunk, ChunkEmbedding, Document, Source
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
    chunk = Chunk(
        document_id=document.id,
        source_id=source.id,
        chunk_text=text,
        chunk_index=0,
        token_count=5,
        source_type="html",
        embedding=embedding,
        meta={"url": url, "hostname": hostname, "source_type": "html"},
    )
    db.add(chunk)
    db.commit()
    return chunk


def test_dense_search_returns_nearest_by_cosine(db):
    _insert_chunk(db, url="https://lib.mercubuana.ac.id/a", hostname="lib.mercubuana.ac.id", text="uang kuliah", embedding=[1.0, 0.0, 0.0])
    _insert_chunk(db, url="https://lib.mercubuana.ac.id/b", hostname="lib.mercubuana.ac.id", text="jadwal", embedding=[0.0, 1.0, 0.0])

    results = dense_search(db, [0.9, 0.1, 0.0], top_k=1)

    assert len(results) == 1
    assert results[0]["url"] == "https://lib.mercubuana.ac.id/a"


def test_dense_search_excludes_out_of_scope_host(db):
    _insert_chunk(db, url="https://evil.com/x", hostname="evil.com", text="x", embedding=[1.0, 0.0])
    assert dense_search(db, [1.0, 0.0], top_k=5) == []


def test_cosine_similarity_rejects_dimension_mismatch():
    with pytest.raises(ValueError, match="different dimensions"):
        cosine_similarity([1.0, 0.0], [1.0])


def test_dense_search_uses_named_sidecar_profile(db):
    near = _insert_chunk(
        db,
        url="https://lib.mercubuana.ac.id/near",
        hostname="lib.mercubuana.ac.id",
        text="informasi semantik",
        embedding=None,
    )
    far = _insert_chunk(
        db,
        url="https://lib.mercubuana.ac.id/far",
        hostname="lib.mercubuana.ac.id",
        text="informasi lain",
        embedding=None,
    )
    db.add_all(
        [
            ChunkEmbedding(
                chunk_id=near.id,
                profile="local-e5-small-v1",
                provider="local_e5",
                model="intfloat/multilingual-e5-small",
                dimension=384,
                version="1",
                embedding=[1.0] + [0.0] * 383,
            ),
            ChunkEmbedding(
                chunk_id=far.id,
                profile="local-e5-small-v1",
                provider="local_e5",
                model="intfloat/multilingual-e5-small",
                dimension=384,
                version="1",
                embedding=[0.0, 1.0] + [0.0] * 382,
            ),
        ]
    )
    db.commit()

    results = dense_search(
        db,
        [1.0] + [0.0] * 383,
        top_k=1,
        embedding_profile="local-e5-small-v1",
    )

    assert results[0]["url"].endswith("/near")


def test_sidecar_table_check_preserves_uncommitted_source_transaction(db):
    source = Source(
        url="https://mercubuana.ac.id/pending",
        title="Pending",
        hostname="mercubuana.ac.id",
        path="/pending",
        status="indexed",
    )
    db.add(source)
    db.flush()
    document = Document(source_id=source.id, raw_text="pending", cleaned_text="pending")
    db.add(document)
    db.flush()
    chunk = Chunk(
        document_id=document.id,
        source_id=source.id,
        chunk_text="informasi pending",
        source_type="html",
        meta={"url": source.url, "hostname": source.hostname},
    )
    db.add(chunk)
    db.flush()
    db.add(
        ChunkEmbedding(
            chunk_id=chunk.id,
            profile="local-e5-small-v1",
            provider="local_e5",
            model="intfloat/multilingual-e5-small",
            dimension=384,
            version="1",
            embedding=[1.0] + [0.0] * 383,
        )
    )
    db.flush()

    results = dense_search(
        db,
        [1.0] + [0.0] * 383,
        top_k=1,
        embedding_profile="local-e5-small-v1",
    )

    assert results[0]["url"] == source.url
    assert db.query(Source).filter(Source.id == source.id).one().status == "indexed"
