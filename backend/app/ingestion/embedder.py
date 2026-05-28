from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import requests

from app.core.config import get_settings


logger = logging.getLogger(__name__)


class EmbeddingConfigurationError(RuntimeError):
    pass


class BaseEmbedder(ABC):
    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]


class OpenAIEmbedder(BaseEmbedder):
    def __init__(self, api_key: str | None = None, model: str | None = None):
        settings = get_settings()
        self.api_key = api_key or settings.openai_api_key
        self.model = model or settings.embedding_model or settings.openai_embedding_model
        if not self.api_key:
            raise EmbeddingConfigurationError(
                "Embedding provider selected but API key is not configured. Set OPENAI_API_KEY or choose another embedding provider."
            )

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        response = requests.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "input": texts},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        return [item["embedding"] for item in sorted(payload["data"], key=lambda item: item["index"])]


def get_embedder() -> BaseEmbedder:
    settings = get_settings()
    if settings.embedding_provider == "openai":
        return OpenAIEmbedder()
    raise EmbeddingConfigurationError(
        f"Unsupported EMBEDDING_PROVIDER={settings.embedding_provider}. The MVP currently supports openai-compatible embeddings."
    )

