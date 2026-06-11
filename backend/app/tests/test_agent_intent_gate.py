"""Agent wiring for the intent gate: junk contexts must not satisfy retrieval, and the
live (Tavily/Firecrawl) fallback must fire on low answerability — even in indexed mode."""

from types import SimpleNamespace

from app.agent.umb_agent import run_umb_agent


def _settings(**over):
    base = dict(
        agent_max_tool_iterations=4,
        web_search_strict_domain="mercubuana.ac.id",
        reranker_enabled=False,
        graph_rag_enabled=False,
        graph_path="unused.json",
        graph_expansion_top_k=3,
        va_jit_enabled=False,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _repo_junk() -> dict:
    return {
        "url": "https://repository.mercubuana.ac.id/12345/",
        "hostname": "repository.mercubuana.ac.id",
        "title": "IMPLEMENTASI CHATBOT CUACA BERBASIS SBERT",
        "chunk_text": "Skripsi penelitian chatbot cuaca SBERT Fakultas Teknik browse by year.",
        "score": 14.0,
        "source_type": "html",
    }


def _biaya() -> dict:
    return {
        "url": "https://pendaftaran.mercubuana.ac.id/rincian-pembayaran",
        "hostname": "pendaftaran.mercubuana.ac.id",
        "title": "Biaya Kuliah - Universitas Mercu Buana",
        "chunk_text": "Rincian pembayaran biaya kuliah PMB gelombang pendaftaran.",
        "score": 12.0,
        "source_type": "html",
    }


def _support() -> dict:
    return {
        "url": "https://support.mercubuana.ac.id/kb/faq.php?id=3",
        "hostname": "support.mercubuana.ac.id",
        "title": "Support Center UMB",
        "chunk_text": "Bantuan reset password akun SIA dan SSO. Hubungi helpdesk support center, buka tiket.",
        "score": 5.0,
        "source_type": "html",
    }


def test_junk_indexed_contexts_trigger_live_fallback_even_in_indexed_mode(db, monkeypatch):
    live_calls: list[str] = []

    class _Indexed:
        def __init__(self, db, root_domain):
            pass

        def search(self, query, top_k, **kwargs):
            return [_repo_junk(), _biaya()]

    class _Live:
        def search(self, query, top_k):
            live_calls.append(query)
            return [_support()]

    monkeypatch.setattr("app.agent.umb_agent.get_settings", lambda: _settings())
    monkeypatch.setattr("app.agent.umb_agent.UMBLiveWebRetriever", _Live)

    result = run_umb_agent(
        db=db,
        query="Bagaimana cara reset password SIA?",
        retrieval_mode="indexed",
        top_k=5,
        root_domain="mercubuana.ac.id",
        indexed_retriever_cls=_Indexed,
        intent="login_help",
    )

    urls = [c.get("url") for c in result.contexts]
    assert "https://support.mercubuana.ac.id/kb/faq.php?id=3" in urls
    assert all("repository." not in (u or "") for u in urls)
    assert all("pendaftaran." not in (u or "") for u in urls)
    assert result.retrieval_fallback_used is True
    assert live_calls, "live fallback should have run"
    assert "password" in live_calls[0].lower()
    debug = result.gate_debug or {}
    assert debug.get("fallback_triggered") is True
    assert debug.get("rejected_candidates", 0) >= 2


def test_relevant_indexed_context_does_not_trigger_fallback(db, monkeypatch):
    live_calls: list[str] = []

    class _Indexed:
        def __init__(self, db, root_domain):
            pass

        def search(self, query, top_k, **kwargs):
            return [_support()]

    class _Live:
        def search(self, query, top_k):
            live_calls.append(query)
            return []

    monkeypatch.setattr("app.agent.umb_agent.get_settings", lambda: _settings())
    monkeypatch.setattr("app.agent.umb_agent.UMBLiveWebRetriever", _Live)

    result = run_umb_agent(
        db=db,
        query="Bagaimana cara reset password SIA?",
        retrieval_mode="indexed",
        top_k=5,
        root_domain="mercubuana.ac.id",
        indexed_retriever_cls=_Indexed,
        intent="login_help",
    )

    assert live_calls == []
    assert result.retrieval_fallback_used is False
    assert [c.get("url") for c in result.contexts] == ["https://support.mercubuana.ac.id/kb/faq.php?id=3"]


def test_graph_expansion_is_intent_gated(db, monkeypatch):
    class _Indexed:
        def __init__(self, db, root_domain):
            pass

        def search(self, query, top_k, **kwargs):
            return [_support()]

    class _Live:
        def search(self, query, top_k):
            return []

    monkeypatch.setattr("app.agent.umb_agent.get_settings", lambda: _settings(graph_rag_enabled=True))
    monkeypatch.setattr("app.agent.umb_agent.UMBLiveWebRetriever", _Live)
    monkeypatch.setattr("app.graph.graph_store.load_graph", lambda path: object())
    monkeypatch.setattr("app.graph.graph_store.expansion_contexts", lambda *a, **k: [_repo_junk()])

    result = run_umb_agent(
        db=db,
        query="Bagaimana jika tidak bisa login SIA?",
        retrieval_mode="indexed",
        top_k=5,
        root_domain="mercubuana.ac.id",
        indexed_retriever_cls=_Indexed,
        intent="login_help",
    )

    assert all("repository." not in (c.get("url") or "") for c in result.contexts)
    debug = result.gate_debug or {}
    assert debug.get("graph_contexts_rejected", 0) >= 1


def test_conversation_context_dropped_on_intent_conflict():
    """Spec test 6: a 'Informasi Fasilkom UMB' chat must not steer a SIA-login query."""
    from app.api.routes_chat import _build_retrieval_query

    history = [{"role": "user", "content": "apa saja program studi fasilkom?"}]
    query = _build_retrieval_query(
        "Bagaimana cara reset password SIA?", history, "Informasi Fasilkom UMB", intent="login_help"
    )
    assert "fasilkom" not in query.lower()

    # Matching intent keeps the context (faculty question in a faculty chat).
    query_faculty = _build_retrieval_query(
        "siapa dekan fakultas ini?", history, "Informasi Fasilkom UMB", intent="faculty"
    )
    assert "fasilkom" in query_faculty.lower()


def test_extractive_fallback_becomes_refusal_for_sensitive_intent():
    """Spec #7/#8/#10/#13: an unverified extractive answer for login must become a
    safe refusal with NO candidate source cards."""
    from app.api.routes_chat import _apply_answer_policy

    payload = {
        "answer": "Saya belum dapat memverifikasi... Berikut kutipan [1].",
        "sources": [{"url": "https://sia.mercubuana.ac.id/x"}, {"url": "https://support.mercubuana.ac.id/y"}],
        "not_found": False,
        "metadata": {"fallback": "extractive"},
    }
    reason = _apply_answer_policy(payload, "login_help", "id")
    assert payload["sources"] == []
    assert "tidak akan menebak" in payload["answer"].lower()
    assert payload["not_found"] is True
    assert reason and "login_help" in reason


def test_verified_answer_is_untouched():
    from app.api.routes_chat import _apply_answer_policy

    payload = {
        "answer": "Dekan Fakultas Ilmu Komputer UMB adalah Dr. X [1].",
        "sources": [{"url": "https://mercubuana.ac.id/struktural-dan-dosen-fasilkom"}],
        "not_found": False,
        "metadata": {},
    }
    reason = _apply_answer_policy(payload, "faculty", "id")
    assert reason is None
    assert len(payload["sources"]) == 1
    assert payload["answer"].startswith("Dekan")


def test_general_intent_unverified_routes_to_whatsapp_fallback():
    """No more messy extractive dumps: a general unverified answer becomes the clean
    'no verified answer -> WhatsApp admin' fallback with zero source cards."""
    from app.api.routes_chat import _apply_answer_policy

    payload = {
        "answer": "Excerpts ...",
        "sources": [{"url": "https://mercubuana.ac.id/x"}],
        "not_found": False,
        "metadata": {"fallback": "extractive"},
    }
    reason = _apply_answer_policy(payload, "general", "id")
    assert reason == "no_verified_answer"
    assert payload["sources"] == []
    assert "whatsapp" in payload["answer"].lower() and "628119852020" in payload["answer"]


def test_no_intent_means_no_gating(db, monkeypatch):
    class _Indexed:
        def __init__(self, db, root_domain):
            pass

        def search(self, query, top_k, **kwargs):
            return [_repo_junk()]

    class _Live:
        def search(self, query, top_k):
            return []

    monkeypatch.setattr("app.agent.umb_agent.get_settings", lambda: _settings())
    monkeypatch.setattr("app.agent.umb_agent.UMBLiveWebRetriever", _Live)

    result = run_umb_agent(
        db=db,
        query="penelitian chatbot",
        retrieval_mode="indexed",
        top_k=5,
        root_domain="mercubuana.ac.id",
        indexed_retriever_cls=_Indexed,
    )

    assert len(result.contexts) == 1
