import sys
from types import SimpleNamespace

from app.ingestion import embedder as emb


class _Settings:
    embedding_provider = "openai"
    gemini_api_key = None
    openai_api_key = None
    embedding_model = "text-embedding-3-small"
    openai_embedding_model = "text-embedding-3-small"
    embedding_profile = "local-e5-small-v1"
    embedding_version = "1"
    local_embedding_model = "intfloat/multilingual-e5-small"
    local_embedding_dimension = 384
    local_embedding_batch_size = 8
    local_embedding_device = "auto"


def test_get_embedder_selects_gemini(monkeypatch):
    settings = _Settings()
    settings.embedding_provider = "gemini"
    settings.gemini_api_key = "test-key"
    monkeypatch.setattr(emb, "get_settings", lambda: settings)
    assert emb.get_embedder().__class__.__name__ == "GeminiEmbedder"


def test_get_embedder_selects_openai(monkeypatch):
    settings = _Settings()
    settings.embedding_provider = "openai"
    settings.openai_api_key = "test-key"
    monkeypatch.setattr(emb, "get_settings", lambda: settings)
    assert emb.get_embedder().__class__.__name__ == "OpenAIEmbedder"


def test_gemini_embedder_requires_key(monkeypatch):
    import pytest

    settings = _Settings()
    settings.gemini_api_key = None
    monkeypatch.setattr(emb, "get_settings", lambda: settings)
    with pytest.raises(emb.EmbeddingConfigurationError):
        emb.GeminiEmbedder()


def test_local_e5_is_lazy_and_uses_required_prefixes(monkeypatch):
    calls = []
    monkeypatch.setattr(emb, "_ENCODER_CACHE", {})

    class _Vector(list):
        def tolist(self):
            return list(self)

    class _Encoder:
        def __init__(self, model, **kwargs):
            calls.append(("init", model, kwargs))

        def encode(self, texts, **kwargs):
            calls.append(("encode", texts, kwargs))
            return [_Vector([1.0] + [0.0] * 383) for _ in texts]

    settings = _Settings()
    settings.embedding_provider = "local_e5"
    monkeypatch.setattr(emb, "get_settings", lambda: settings)
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=_Encoder),
    )

    embedder = emb.get_embedder()
    assert calls == []
    assert len(embedder.embed_texts(["dokumen"])) == 1
    assert len(embedder.embed_query("pertanyaan")) == 384
    assert calls[1][1] == ["passage: dokumen"]
    assert calls[2][1] == ["query: pertanyaan"]
