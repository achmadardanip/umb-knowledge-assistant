from app.db.models import Chunk, Document, Source
from app.retrieval.hybrid_retriever import HybridRetriever


def _insert_identical_chunk(db, *, url: str, hostname: str):
    source = Source(url=url, title="Info", hostname=hostname, path="/info", status="indexed", discovery_source="katana")
    db.add(source)
    db.flush()
    document = Document(source_id=source.id, raw_text="x", cleaned_text="x")
    db.add(document)
    db.flush()
    db.add(
        Chunk(
            document_id=document.id,
            source_id=source.id,
            chunk_text="Informasi pendaftaran mahasiswa baru tersedia di sini.",
            chunk_index=0,
            token_count=8,
            source_type="html",
            meta={
                "url": url,
                "hostname": hostname,
                "path": "/info",
                "title": "Info",
                "source_type": "html",
                "discovery_source": "katana",
            },
        )
    )
    db.commit()


def test_authority_breaks_ties_between_equal_relevance_sources(db):
    # Identical text on two official hosts: only authority differs.
    _insert_identical_chunk(db, url="https://klubmahasiswa.mercubuana.ac.id/info", hostname="klubmahasiswa.mercubuana.ac.id")
    _insert_identical_chunk(db, url="https://pmb.mercubuana.ac.id/info", hostname="pmb.mercubuana.ac.id")

    contexts = HybridRetriever(db).search("informasi pendaftaran mahasiswa baru", top_k=5)

    assert contexts[0]["hostname"] == "pmb.mercubuana.ac.id"
    assert contexts[0]["authority"] >= contexts[1]["authority"]
