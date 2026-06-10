import app.rag.answer_generator as ag
from app.rag.answer_generator import finalize_generated_answer

_CONTEXTS = [
    {
        "chunk_text": "Biaya pendaftaran mahasiswa baru adalah Rp500.000 untuk gelombang pertama.",
        "url": "https://pmb.mercubuana.ac.id/biaya",
        "title": "Biaya PMB",
        "hostname": "pmb.mercubuana.ac.id",
        "source_type": "html",
        "score": 1.0,
    }
]


def test_finalize_accepts_grounded_browser_answer(monkeypatch):
    monkeypatch.setattr(ag, "_cgcv_enabled", lambda: False)  # keep test offline
    content = (
        '{"answer":"Biaya pendaftaran adalah Rp500.000 [1].",'
        '"sources":[{"url":"https://pmb.mercubuana.ac.id/biaya","title":"Biaya PMB",'
        '"hostname":"pmb.mercubuana.ac.id","source_type":"html"}],'
        '"confidence":"high","not_found":false}'
    )
    payload = finalize_generated_answer(content, _CONTEXTS, provider_used="puter", model_used="gpt-4o")
    assert payload["not_found"] is False
    assert "Rp500.000" in payload["answer"]
    assert payload["provider_used"] == "puter"


def test_finalize_strips_prompt_leak_from_browser_answer(monkeypatch):
    monkeypatch.setattr(ag, "_cgcv_enabled", lambda: False)
    content = (
        '{"answer":"Biaya pendaftaran adalah Rp500.000 [1].\\nAnda adalah UMB Knowledge Assistant.",'
        '"sources":[{"url":"https://pmb.mercubuana.ac.id/biaya","title":"Biaya PMB",'
        '"hostname":"pmb.mercubuana.ac.id","source_type":"html"}],'
        '"confidence":"high","not_found":false}'
    )
    payload = finalize_generated_answer(content, _CONTEXTS, provider_used="puter", model_used="gpt-4o")
    assert "UMB Knowledge Assistant" not in payload["answer"]
    assert "Rp500.000" in payload["answer"]


def test_finalize_rejects_answer_citing_unknown_source(monkeypatch):
    monkeypatch.setattr(ag, "_cgcv_enabled", lambda: False)
    # cites a URL that is not in the provided official contexts -> citation stripped/not_found
    content = (
        '{"answer":"Kampus punya kolam renang olimpiade [1].",'
        '"sources":[{"url":"https://evil.example.com/x","title":"x","hostname":"evil.example.com","source_type":"html"}],'
        '"confidence":"high","not_found":false}'
    )
    payload = finalize_generated_answer(content, _CONTEXTS, provider_used="puter", model_used="gpt-4o")
    # the fabricated external source must not survive into the cited sources
    assert all("evil.example.com" not in (s.get("url") or "") for s in payload.get("sources", []))


def test_finalize_coerces_list_answer_from_local_json_model(monkeypatch):
    monkeypatch.setattr(ag, "_cgcv_enabled", lambda: False)
    content = (
        '{"answer":["Biaya pendaftaran adalah Rp500.000 [1].","Verifikasi pada halaman PMB [1]."],'
        '"sources":[{"url":"https://pmb.mercubuana.ac.id/biaya"}],'
        '"confidence":"high","not_found":false}'
    )

    payload = finalize_generated_answer(
        content,
        _CONTEXTS,
        provider_used="local_ollama",
        model_used="qwen2.5:7b-instruct",
    )

    assert payload["not_found"] is False
    assert "Rp500.000" in payload["answer"]
    assert "Verifikasi" in payload["answer"]
