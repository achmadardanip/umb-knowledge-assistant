from app.llm.base import LLMResponse
from app.rag.answer_generator import generate_answer


class _FakeProvider:
    provider_name = "openrouter"
    model = "test-model"


_CONTEXTS = [
    {
        "title": "Biaya PMB",
        "url": "https://pmb.mercubuana.ac.id/biaya",
        "hostname": "pmb.mercubuana.ac.id",
        "source_type": "html",
        "score": 0.9,
        "chunk_text": "Biaya pendaftaran program sarjana adalah Rp500.000.",
        "discovery_source": "katana",
    }
]

# Model answer mixes a supported fact with a fabricated one, both cited [1].
_MIXED_ANSWER = (
    '{"answer":"Biaya pendaftaran adalah Rp500.000 [1]. '
    'Kampus memiliki kolam renang olimpiade [1].",'
    '"sources":[{"url":"https://pmb.mercubuana.ac.id/biaya","title":"Biaya PMB",'
    '"hostname":"pmb.mercubuana.ac.id","source_type":"html"}],'
    '"confidence":"high","not_found":false}'
)


class _StubChecker:
    def entails(self, *, premise: str, hypothesis: str) -> float:
        return 1.0 if "Rp500.000" in hypothesis else 0.0


def _patch_cgcv(monkeypatch, answer_json: str):
    def fake_chat_with_failover(messages, provider_override, max_retries):
        return (
            _FakeProvider(),
            LLMResponse(content=answer_json, provider_used="openrouter", model_used="test-model"),
            None,
        )

    monkeypatch.setattr("app.rag.answer_generator._chat_with_failover", fake_chat_with_failover)
    monkeypatch.setattr("app.rag.answer_generator._cgcv_enabled", lambda: True)
    monkeypatch.setattr(
        "app.rag.answer_generator.build_default_entailment_checker", lambda provider_override: _StubChecker()
    )


def test_generate_answer_drops_unsupported_claim_when_cgcv_enabled(monkeypatch):
    _patch_cgcv(monkeypatch, _MIXED_ANSWER)

    result = generate_answer(
        question="Berapa biaya pendaftaran?",
        contexts=_CONTEXTS,
        recent_messages=[],
        memories=[],
        provider_override="openrouter",
        language="id",
    )

    assert result["not_found"] is False
    assert "Rp500.000" in result["answer"]
    assert "kolam renang" not in result["answer"]


def test_generate_answer_does_not_assert_fully_unsupported_answer(monkeypatch):
    pool_only = (
        '{"answer":"Kampus memiliki kolam renang olimpiade [1].",'
        '"sources":[{"url":"https://pmb.mercubuana.ac.id/biaya","title":"Biaya PMB",'
        '"hostname":"pmb.mercubuana.ac.id","source_type":"html"}],'
        '"confidence":"high","not_found":false}'
    )
    _patch_cgcv(monkeypatch, pool_only)

    result = generate_answer(
        question="Apakah ada kolam renang?",
        contexts=_CONTEXTS,
        recent_messages=[],
        memories=[],
        provider_override="openrouter",
        language="id",
    )

    assert "kolam renang olimpiade" not in result["answer"]
