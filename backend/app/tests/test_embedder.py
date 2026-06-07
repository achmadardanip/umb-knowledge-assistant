from app.ingestion import embedder as emb


class _Settings:
    embedding_provider = "openai"
    gemini_api_key = None
    openai_api_key = None
    embedding_model = "text-embedding-3-small"
    openai_embedding_model = "text-embedding-3-small"


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
