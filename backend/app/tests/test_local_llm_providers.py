from __future__ import annotations

from types import SimpleNamespace

from app.llm.local_lmstudio_provider import LocalLMStudioProvider
from app.llm.local_ollama_provider import LocalOllamaProvider
from app.llm.provider_factory import get_provider, normalize_provider


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def _settings():
    return SimpleNamespace(
        local_llm_base_url="http://localhost:11434",
        local_llm_model="qwen2.5:7b-instruct",
        local_llm_max_tokens=800,
        local_llm_timeout_seconds=180,
        local_llm_temperature=0.2,
        lmstudio_base_url="http://localhost:1234/v1",
        lmstudio_model="local-model",
        lmstudio_api_key="lm-studio",
        ai_provider="local_ollama",
    )


def test_ollama_provider_calls_local_chat_endpoint(monkeypatch):
    calls = []
    monkeypatch.setattr("app.llm.local_ollama_provider.get_settings", _settings)
    monkeypatch.setattr(
        "app.llm.local_ollama_provider.requests.post",
        lambda url, **kwargs: calls.append((url, kwargs)) or _Response({"message": {"content": "jawaban"}}),
    )
    response = LocalOllamaProvider().chat([{"role": "user", "content": "halo"}])
    assert calls[0][0] == "http://localhost:11434/api/chat"
    assert calls[0][1]["json"]["model"] == "qwen2.5:7b-instruct"
    assert calls[0][1]["json"]["options"]["temperature"] == 0.2
    assert response.content == "jawaban"
    assert response.provider_used == "local_ollama"


def test_lmstudio_provider_uses_openai_compatible_endpoint(monkeypatch):
    calls = []
    monkeypatch.setattr("app.llm.local_lmstudio_provider.get_settings", _settings)
    monkeypatch.setattr(
        "app.llm.local_lmstudio_provider.requests.post",
        lambda url, **kwargs: calls.append((url, kwargs))
        or _Response({"choices": [{"message": {"content": "answer"}}]}),
    )
    response = LocalLMStudioProvider().chat([{"role": "user", "content": "hello"}])
    assert calls[0][0] == "http://localhost:1234/v1/chat/completions"
    assert calls[0][1]["json"]["temperature"] == 0.2
    assert response.provider_used == "local_lmstudio"


def test_provider_factory_supports_local_aliases(monkeypatch):
    monkeypatch.setattr("app.llm.provider_factory.get_settings", _settings)
    assert normalize_provider("ollama") == "local_ollama"
    assert normalize_provider("lmstudio") == "local_lmstudio"
    assert get_provider("local_ollama").provider_name == "local_ollama"
