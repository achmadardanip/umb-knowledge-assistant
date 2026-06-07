from app.db.models import Chunk, Document, Source
from app.ingestion.embed_backfill import backfill_embeddings


class _FakeEmbedder:
    def embed_texts(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed_query(self, query):
        return [0.1, 0.2, 0.3]


def _insert_chunk_without_embedding(db, url):
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
        )
    )
    db.commit()


def test_backfill_populates_missing_embeddings(db):
    _insert_chunk_without_embedding(db, "https://mercubuana.ac.id/a")
    _insert_chunk_without_embedding(db, "https://mercubuana.ac.id/b")

    populated = backfill_embeddings(db, _FakeEmbedder())

    assert populated == 2
    assert db.query(Chunk).filter(Chunk.embedding.is_(None)).count() == 0
