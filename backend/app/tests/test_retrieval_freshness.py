from datetime import datetime, timedelta, timezone

from app.db.models import Chunk, Document, Source
from app.retrieval.hybrid_retriever import HybridRetriever


def _insert(db, *, url, hostname, text, fetched_at):
    source = Source(
        url=url, title="t", hostname=hostname, path="/p", status="indexed", discovery_source="katana", fetched_at=fetched_at
    )
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
            token_count=4,
            source_type="html",
            meta={"url": url, "hostname": hostname, "source_type": "html"},
        )
    )
    db.commit()


def test_fresher_source_outranks_stale_for_volatile_query(db):
    now = datetime.now(timezone.utc)
    _insert(db, url="https://pmb.mercubuana.ac.id/fresh", hostname="pmb.mercubuana.ac.id", text="Biaya pendaftaran terbaru tersedia.", fetched_at=now)
    _insert(db, url="https://pmb.mercubuana.ac.id/stale", hostname="pmb.mercubuana.ac.id", text="Biaya pendaftaran terbaru tersedia.", fetched_at=now - timedelta(days=120))

    contexts = HybridRetriever(db).search("biaya pendaftaran", top_k=5)

    assert contexts[0]["url"].endswith("/fresh")
    assert contexts[0].get("last_verified")
