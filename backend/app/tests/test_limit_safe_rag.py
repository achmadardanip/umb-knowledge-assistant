from app.api.routes_chat import ChatRequest, process_chat
from app.api.routes_chat import _build_retrieval_query
from app.db.models import Chunk, Document, Source
from app.llm.base import LLMResponse
from app.llm.provider_factory import get_provider
from app.rag.answer_cache import build_cache_key, get_cached_answer, store_cached_answer
from app.rag.answer_generator import generate_answer
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


def _add_library_chunk(db):
    source = Source(
        url="https://lib.mercubuana.ac.id/id/layanan",
        title="Layanan | Perpustakaan Universitas Mercu Buana",
        hostname="lib.mercubuana.ac.id",
        path="/id/layanan",
        status="indexed",
        discovery_source="katana",
    )
    db.add(source)
    db.flush()
    document = Document(source_id=source.id, raw_text="layanan perpustakaan", cleaned_text="layanan perpustakaan")
    db.add(document)
    db.flush()
    db.add(
        Chunk(
            document_id=document.id,
            source_id=source.id,
            chunk_text="Informasi layanan Perpustakaan Universitas Mercu Buana tersedia melalui portal lib UMB.",
            chunk_index=0,
            token_count=12,
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


def _patch_answer_generation(monkeypatch):
    def fake_provider_meta(provider_override):
        return provider_override or "openrouter", "test-model"

    def fake_generate_answer(**kwargs):
        context = kwargs["contexts"][0]
        return {
            "answer": f"Informasi tersedia melalui {context['title']} [1].",
            "sources": [
                {
                    "title": context["title"],
                    "url": context["url"],
                    "hostname": context["hostname"],
                    "source_type": context["source_type"],
                    "relevance_score": context["score"],
                    "discovery_source": context["discovery_source"],
                }
            ],
            "confidence": "high",
            "not_found": False,
            "provider_used": "openrouter",
            "model_used": "test-model",
            "memory_used": False,
        }

    monkeypatch.setattr("app.api.routes_chat._provider_meta", fake_provider_meta)
    monkeypatch.setattr("app.api.routes_chat.generate_answer", fake_generate_answer)


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
    result = process_chat(
        ChatRequest(anonymous_session_id="anon-cache", question=question, retrieval_mode="indexed", memory_enabled=False),
        db,
    )
    assert result["answer"] == payload["answer"]
    assert result["sources"][0]["hostname"] == "pmb.mercubuana.ac.id"
    assert result["visible_steps"]
    assert result["intent"] == "official_info_query"


def test_hybrid_library_query_uses_indexed_library_context(db, monkeypatch):
    _add_library_chunk(db)
    _patch_answer_generation(monkeypatch)
    monkeypatch.setattr("app.agent.umb_agent.UMBLiveWebRetriever.search", lambda self, query, top_k=None: [])

    result = process_chat(
        ChatRequest(
            anonymous_session_id="anon-library",
            question="Di mana informasi perpustakaan UMB?",
            retrieval_mode="hybrid",
            memory_enabled=False,
        ),
        db,
    )

    assert result["not_found"] is False
    assert result["sources"][0]["hostname"] == "lib.mercubuana.ac.id"
    assert result["retrieval_mode"] == "hybrid"


def test_web_mode_falls_back_to_indexed_when_live_web_is_empty(db, monkeypatch):
    _add_library_chunk(db)
    _patch_answer_generation(monkeypatch)
    monkeypatch.setattr("app.agent.umb_agent.UMBLiveWebRetriever.search", lambda self, query, top_k=None: [])

    result = process_chat(
        ChatRequest(
            anonymous_session_id="anon-web-fallback",
            question="Di mana informasi perpustakaan UMB?",
            retrieval_mode="web",
            memory_enabled=False,
        ),
        db,
    )

    assert result["not_found"] is False
    assert result["sources"][0]["hostname"] == "lib.mercubuana.ac.id"
    assert result["retrieval_fallback_used"] is True
    assert result["indexed_context_count"] >= 1


def test_hybrid_uses_indexed_when_live_web_errors(db, monkeypatch):
    _add_library_chunk(db)
    _patch_answer_generation(monkeypatch)

    def fail_web(self, query, top_k=None):
        raise RuntimeError("live web unavailable")

    monkeypatch.setattr("app.agent.umb_agent.UMBLiveWebRetriever.search", fail_web)

    result = process_chat(
        ChatRequest(
            anonymous_session_id="anon-hybrid-error",
            question="Di mana informasi perpustakaan UMB?",
            retrieval_mode="hybrid",
            memory_enabled=False,
        ),
        db,
    )

    assert result["not_found"] is False
    assert result["sources"][0]["hostname"] == "lib.mercubuana.ac.id"
    assert result["retrieval_fallback_used"] is True
    assert result["retrieval_warnings"]
    rendered_steps = str(result["visible_steps"]).lower()
    for forbidden in ("<think>", "chain-of-thought", "thought", "action", "observation"):
        assert forbidden not in rendered_steps


def test_contextual_query_uses_previous_context_without_duplicate_current_question():
    question = "yang tadi lokasinya di mana?"
    history = [
        {"role": "user", "content": "Di mana informasi perpustakaan UMB?"},
        {
            "role": "assistant",
            "content": "Informasi perpustakaan tersedia.",
            "sources": [
                {
                    "title": "Layanan | Perpustakaan Universitas Mercu Buana",
                    "hostname": "lib.mercubuana.ac.id",
                    "url": "https://lib.mercubuana.ac.id/id/layanan",
                }
            ],
        },
        {"role": "user", "content": question},
    ]

    query = _build_retrieval_query(question, history, "Informasi Perpustakaan UMB")

    assert query.lower().count(question) == 1
    assert "lib.mercubuana.ac.id" in query
    assert "Di mana informasi perpustakaan UMB?" in query


def test_provider_answer_without_valid_citation_uses_extractive_fallback(monkeypatch):
    class FakeProvider:
        provider_name = "openrouter"
        model = "test-model"

    contexts = [
        {
            "title": "Layanan | Perpustakaan Universitas Mercu Buana",
            "url": "https://lib.mercubuana.ac.id/id/layanan",
            "hostname": "lib.mercubuana.ac.id",
            "source_type": "html",
            "score": 0.91,
            "chunk_text": "Informasi layanan Perpustakaan Universitas Mercu Buana tersedia melalui portal lib UMB.",
            "discovery_source": "katana",
        }
    ]

    def fake_chat_with_failover(messages, provider_override, max_retries):
        return (
            FakeProvider(),
            LLMResponse(
                content='{"answer":"Saya belum menemukan informasi resmi.","sources":[],"confidence":"low","not_found":true}',
                provider_used="openrouter",
                model_used="test-model",
            ),
            None,
        )

    monkeypatch.setattr("app.rag.answer_generator._chat_with_failover", fake_chat_with_failover)

    result = generate_answer(
        question="Di mana informasi perpustakaan UMB?",
        contexts=contexts,
        recent_messages=[],
        memories=[],
        provider_override="openrouter",
        language="id",
    )

    assert result["not_found"] is False
    assert result["sources"][0]["hostname"] == "lib.mercubuana.ac.id"
    assert "kutipan paling relevan" in result["answer"]
    assert "[1]" in result["answer"]


def test_top_k_is_capped_before_retrieval(db, monkeypatch):
    captured = {}

    def fake_search(self, query, top_k=5, source_types=None):
        captured["top_k"] = top_k
        return []

    monkeypatch.setattr("app.api.routes_chat.HybridRetriever.search", fake_search)
    result = process_chat(
        ChatRequest(
            anonymous_session_id="anon-topk",
            question="Apa saja program akademik UMB?",
            top_k=20,
            retrieval_mode="indexed",
            memory_enabled=False,
        ),
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
