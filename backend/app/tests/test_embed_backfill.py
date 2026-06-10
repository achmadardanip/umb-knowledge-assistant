from app.db.models import Chunk, ChunkEmbedding, Document, Source
from app.ingestion.embed_backfill import backfill_embeddings


class _FakeEmbedder:
    calls = 0

    def embed_texts(self, texts):
        self.calls += 1
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed_query(self, query):
        return [0.1, 0.2, 0.3]


class _LocalFakeEmbedder:
    storage = "sidecar"
    provider_name = "local_e5"
    model = "intfloat/multilingual-e5-small"
    dimension = 384
    profile = "local-e5-small-v1"
    version = "1"

    def __init__(self):
        self.calls = 0

    def embed_texts(self, texts):
        self.calls += 1
        return [[1.0] + [0.0] * 383 for _ in texts]


def _insert_chunk_without_embedding(db, url, *, embedding=None):
    source = Source(url=url, title="t", hostname="mercubuana.ac.id", path="/p", status="indexed", discovery_source="katana")
    db.add(source)
    db.flush()
    document = Document(source_id=source.id, raw_text="teks", cleaned_text="teks")
    db.add(document)
    db.flush()
    db.add(
        Chunk(
            document_id=document.id,
            source_id=source.id,
            chunk_text="teks resmi umb",
            chunk_index=0,
            token_count=3,
            source_type="html",
            embedding=embedding,
        )
    )
    db.commit()
    return source


def test_backfill_populates_missing_embeddings(db):
    _insert_chunk_without_embedding(db, "https://mercubuana.ac.id/a")
    _insert_chunk_without_embedding(db, "https://mercubuana.ac.id/b")

    populated = backfill_embeddings(db, _FakeEmbedder())

    assert populated == 2
    assert db.query(Chunk).filter(Chunk.embedding.is_(None)).count() == 0


def test_backfill_dry_run_does_not_embed_or_write(db):
    _insert_chunk_without_embedding(db, "https://mercubuana.ac.id/a")
    embedder = _LocalFakeEmbedder()

    matched = backfill_embeddings(db, embedder, dry_run=True)

    assert matched == 1
    assert embedder.calls == 0
    assert db.query(ChunkEmbedding).count() == 0


def test_local_backfill_writes_profile_provenance_without_touching_legacy_vector(db):
    _insert_chunk_without_embedding(db, "https://mercubuana.ac.id/a")
    embedder = _LocalFakeEmbedder()

    populated = backfill_embeddings(db, embedder)

    row = db.query(ChunkEmbedding).one()
    assert populated == 1
    assert row.profile == "local-e5-small-v1"
    assert row.provider == "local_e5"
    assert row.dimension == 384
    assert db.query(Chunk).one().embedding is None


def test_local_backfill_refreshes_changed_profile_version(db):
    _insert_chunk_without_embedding(db, "https://mercubuana.ac.id/a")
    embedder = _LocalFakeEmbedder()
    backfill_embeddings(db, embedder)
    embedder.version = "2"

    populated = backfill_embeddings(db, embedder)

    assert populated == 1
    assert db.query(ChunkEmbedding).one().version == "2"


def test_only_keyword_only_excludes_partially_embedded_sources(db):
    _insert_chunk_without_embedding(db, "https://mercubuana.ac.id/keyword-only")
    partial = _insert_chunk_without_embedding(
        db,
        "https://mercubuana.ac.id/partial",
        embedding=[0.1, 0.2, 0.3],
    )
    document = Document(source_id=partial.id, raw_text="teks lain", cleaned_text="teks lain")
    db.add(document)
    db.flush()
    db.add(Chunk(document_id=document.id, source_id=partial.id, chunk_text="teks lain", source_type="html"))
    db.commit()

    populated = backfill_embeddings(db, _LocalFakeEmbedder(), only_keyword_only=True)

    assert populated == 1
    embedded_chunk = db.query(ChunkEmbedding).one().chunk
    assert embedded_chunk.source.url.endswith("/keyword-only")
