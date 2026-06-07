from datetime import datetime, timedelta, timezone

from app.agent.umb_agent import run_umb_agent
from app.db.models import Chunk, Document, Source


def _insert_stale_chunk(db):
    fetched = datetime.now(timezone.utc) - timedelta(days=120)
    source = Source(
        url="https://pmb.mercubuana.ac.id/biaya",
        title="Biaya",
        hostname="pmb.mercubuana.ac.id",
        path="/biaya",
        status="indexed",
        discovery_source="katana",
        fetched_at=fetched,
    )
    db.add(source)
    db.flush()
    document = Document(source_id=source.id, raw_text="biaya pendaftaran", cleaned_text="biaya pendaftaran")
    db.add(document)
    db.flush()
    db.add(
        Chunk(
            document_id=document.id,
            source_id=source.id,
            chunk_text="Biaya pendaftaran semester lama tersedia.",
            chunk_index=0,
            token_count=5,
            source_type="html",
            meta={"url": source.url, "hostname": source.hostname, "source_type": "html"},
        )
    )
    db.commit()


def test_va_jit_reverifies_for_volatile_stale_query(db, monkeypatch):
    _insert_stale_chunk(db)
    monkeypatch.setattr("app.agent.umb_agent._va_jit_enabled", lambda: True)

    fresh = {
        "url": "https://pmb.mercubuana.ac.id/live-biaya",
        "hostname": "pmb.mercubuana.ac.id",
        "chunk_text": "Biaya pendaftaran terbaru Rp600.000.",
        "source_type": "html",
    }
    monkeypatch.setattr(
        "app.agent.umb_agent.UMBLiveWebRetriever.search",
        lambda self, query, top_k=None: [dict(fresh)],
    )

    result = run_umb_agent(db=db, query="biaya pendaftaran", retrieval_mode="indexed", top_k=5, root_domain="mercubuana.ac.id")

    assert any(context["url"].endswith("/live-biaya") for context in result.contexts)
    live = next(context for context in result.contexts if context["url"].endswith("/live-biaya"))
    assert live.get("last_verified")


def test_va_jit_disabled_by_default_does_not_refetch(db, monkeypatch):
    _insert_stale_chunk(db)
    calls = []
    monkeypatch.setattr(
        "app.agent.umb_agent.UMBLiveWebRetriever.search",
        lambda self, query, top_k=None: calls.append(1) or [],
    )

    run_umb_agent(db=db, query="biaya pendaftaran", retrieval_mode="indexed", top_k=5, root_domain="mercubuana.ac.id")

    assert not calls  # VA_JIT_ENABLED is off by default, and indexed mode doesn't call live web
