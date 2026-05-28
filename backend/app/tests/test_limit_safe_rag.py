from app.api.routes_chat import ChatRequest, process_chat
from app.db.models import Chunk, Document, Source
from app.llm.provider_factory import get_provider
from app.rag.answer_cache import build_cache_key, get_cached_answer, store_cached_answer
from app.retrieval.hybrid_retriever import HybridRetriever


def _add_pendaftaran_chunk(db):
    source = Source(
        url="https://pmb.mercubuana.ac.id/pendaftaran",
        title="Pendaftaran Mahasiswa Baru",
        hostname="pmb.mercubuana.ac.id",
        path="/pendaftaran",
        status="indexed",
        discovery_source="katana",
    )
    db.add(source)
    db.flush()
    document = Document(source_id=source.id, raw_text="pendaftaran mahasiswa baru", cleaned_text="pendaftaran mahasiswa baru")
    db.add(document)
    db.flush()
    db.add(
        Chunk(
            document_id=document.id,
            source_id=source.id,
            chunk_text="Informasi pendaftaran mahasiswa baru Universitas Mercu Buana melalui PMB.",
            chunk_index=0,
            token_count=10,
            source_type="html",
            meta={
                "url": source.url,
                "hostname": source.hostname,
                "path": source.path,
                "title": source.title,
                "source_type": "html",
                "discovery_source": "katana",
            },
        )
    )
    db.commit()


def test_answer_cache_hit_avoids_provider_call(db, monkeypatch):
    question = "Bagaimana cara daftar mahasiswa baru?"
    _add_pendaftaran_chunk(db)
    contexts = HybridRetriever(db).search(question, top_k=5)
    provider = get_provider(None)
    payload = {
        "answer": "Pendaftaran tersedia melalui PMB.",
        "sources": [
            {
                "title": contexts[0]["title"],
                "url": contexts[0]["url"],
                "hostname": contexts[0]["hostname"],
                "source_type": contexts[0]["source_type"],
                "relevance_score": contexts[0]["score"],
                "discovery_source": contexts[0]["discovery_source"],
            }
        ],
        "confidence": "high",
        "not_found": False,
        "provider_used": provider.provider_name,
        "model_used": provider.model,
        "memory_used": False,
    }
    cache_key = build_cache_key(
        question=question,
        intent="official_info_query",
        provider_used=provider.provider_name,
        model_used=provider.model,
        contexts=contexts,
        memory_enabled=False,
    )
    store_cached_answer(
        db,
        cache_key=cache_key,
        question=question,
        intent="official_info_query",
        provider_used=provider.provider_name,
        model_used=provider.model,
        answer_payload=payload,
        ttl_seconds=3600,
    )
    db.commit()
    assert get_cached_answer(db, cache_key)

    def fail_generate_answer(**_kwargs):
        raise AssertionError("provider should not be called on cache hit")

    monkeypatch.setattr("app.api.routes_chat.generate_answer", fail_generate_answer)
    result = process_chat(ChatRequest(anonymous_session_id="anon-cache", question=question, memory_enabled=False), db)
    assert result["answer"] == payload["answer"]
    assert result["sources"][0]["hostname"] == "pmb.mercubuana.ac.id"
    assert result["visible_steps"]
    assert result["intent"] == "official_info_query"


def test_top_k_is_capped_before_retrieval(db, monkeypatch):
    captured = {}

    def fake_search(self, query, top_k=5, source_types=None):
        captured["top_k"] = top_k
        return []

    monkeypatch.setattr("app.api.routes_chat.HybridRetriever.search", fake_search)
    result = process_chat(
        ChatRequest(anonymous_session_id="anon-topk", question="Apa saja program akademik UMB?", top_k=20, memory_enabled=False),
        db,
    )
    assert captured["top_k"] == 8
    assert result["not_found"] is True


def test_sia_query_does_not_match_indonesia_substring(db):
    psych_source = Source(
        url="https://lib.mercubuana.ac.id/psikologi",
        title="Bidang Ilmu Psikologi",
        hostname="lib.mercubuana.ac.id",
        path="/psikologi",
        status="indexed",
        discovery_source="katana",
    )
    db.add(psych_source)
    db.flush()
    psych_doc = Document(source_id=psych_source.id, raw_text="Indonesia psikologi", cleaned_text="Indonesia psikologi")
    db.add(psych_doc)
    db.flush()
    db.add(
        Chunk(
            document_id=psych_doc.id,
            source_id=psych_source.id,
            chunk_text="Artikel jurnal psikologi Indonesia dan human behavior studies.",
            chunk_index=0,
            token_count=8,
            source_type="html",
            meta={
                "url": psych_source.url,
                "hostname": psych_source.hostname,
                "path": psych_source.path,
                "title": psych_source.title,
                "source_type": "html",
                "discovery_source": "katana",
            },
        )
    )
    sia_source = Source(
        url="https://sso.mercubuana.ac.id/help",
        title="Panduan SSO dan SIA",
        hostname="sso.mercubuana.ac.id",
        path="/help",
        status="indexed",
        discovery_source="katana",
    )
    db.add(sia_source)
    db.flush()
    sia_doc = Document(source_id=sia_source.id, raw_text="SIA login", cleaned_text="SIA login")
    db.add(sia_doc)
    db.flush()
    db.add(
        Chunk(
            document_id=sia_doc.id,
            source_id=sia_source.id,
            chunk_text="Panduan login SIA dan SSO Universitas Mercu Buana untuk bantuan akun.",
            chunk_index=0,
            token_count=11,
            source_type="html",
            meta={
                "url": sia_source.url,
                "hostname": sia_source.hostname,
                "path": sia_source.path,
                "title": sia_source.title,
                "source_type": "html",
                "discovery_source": "katana",
            },
        )
    )
    db.commit()

    contexts = HybridRetriever(db).search("Bagaimana jika tidak bisa login SIA?", top_k=5)
    assert contexts
    assert all("psikologi" not in context["url"] for context in contexts)
    assert contexts[0]["hostname"] == "sso.mercubuana.ac.id"
