from urllib.parse import urlparse

import pytest

from app.db.models import Chunk, Source
from app.ingestion.embedder import BaseEmbedder
from app.ingestion.web_kb_ingest import persist_web_contexts


class _FakeEmbedder(BaseEmbedder):
    """Deterministic, offline embedder so ingest tests never hit the network."""

    def embed_texts(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed_query(self, query):
        return [0.1, 0.2, 0.3]


@pytest.fixture(autouse=True)
def _offline_embedder(monkeypatch):
    monkeypatch.setattr("app.ingestion.pipeline.get_embedder", lambda: _FakeEmbedder())


def _ctx(url: str, text: str, title: str = "Judul") -> dict:
    return {
        "chunk_text": text,
        "url": url,
        "title": title,
        "hostname": (urlparse(url).hostname or "").lower(),
        "discovery_source": "live_web_search",
        "source_type": "html",
        "score": 0.8,
        "metadata": {},
    }


def test_persists_new_web_source_and_chunks(db):
    n = persist_web_contexts(db, [_ctx("https://pmb.mercubuana.ac.id/x", "Biaya pendaftaran Rp500.000 gelombang 1.")])
    db.commit()
    assert n >= 1
    src = db.query(Source).filter(Source.url == "https://pmb.mercubuana.ac.id/x").first()
    assert src is not None and src.status == "indexed"
    assert db.query(Chunk).filter(Chunk.source_id == src.id).count() >= 1


def test_groups_multiple_chunks_of_same_url(db):
    ctxs = [
        _ctx("https://x.mercubuana.ac.id/a", "Bagian satu konten resmi."),
        _ctx("https://x.mercubuana.ac.id/a", "Bagian dua konten resmi."),
    ]
    persist_web_contexts(db, ctxs)
    db.commit()
    assert db.query(Source).filter(Source.url == "https://x.mercubuana.ac.id/a").count() == 1


def test_dedups_on_repeat_ingest_of_same_content(db):
    c = _ctx("https://x.mercubuana.ac.id/b", "Konten stabil yang sama persis.")
    persist_web_contexts(db, [c])
    db.commit()
    chunks_after_first = db.query(Chunk).count()
    persist_web_contexts(db, [c])
    db.commit()
    assert db.query(Source).filter(Source.url == "https://x.mercubuana.ac.id/b").count() == 1
    assert db.query(Chunk).count() == chunks_after_first  # unchanged content -> no new chunks


def test_skips_contexts_without_url_or_text(db):
    n = persist_web_contexts(
        db,
        [
            {"chunk_text": "", "url": "https://x.mercubuana.ac.id/y"},
            {"chunk_text": "ada teks", "url": ""},
            {"url": "https://x.mercubuana.ac.id/z"},
        ],
    )
    db.commit()
    assert n == 0
    assert db.query(Source).count() == 0


def test_returns_zero_for_empty_input(db):
    assert persist_web_contexts(db, []) == 0
