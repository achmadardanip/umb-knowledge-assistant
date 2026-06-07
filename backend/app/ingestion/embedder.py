from __future__ import annotations

import logging
import time
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


class GeminiEmbedder(BaseEmbedder):
    """Google Gemini embeddings (configurable via EMBEDDING_MODEL, e.g. gemini-embedding-2).

    Uses the :embedContent endpoint per text because the gemini-embedding-* models
    do not expose the synchronous batch endpoint; transient rate limits are retried.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None):
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.gemini_api_key
        self.model = model or settings.embedding_model or "gemini-embedding-001"
        if not self.api_key:
            raise EmbeddingConfigurationError(
                "Gemini embedding selected but GEMINI_API_KEY is not configured."
            )

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        model_path = self.model if self.model.startswith("models/") else f"models/{self.model}"
        # Key goes in a header, not the URL, so it can't leak in error messages/logs.
        url = f"https://generativelanguage.googleapis.com/v1beta/{model_path}:embedContent"
        headers = {"x-goog-api-key": self.api_key}
        vectors: list[list[float]] = []
        for text in texts:
            body = {"model": model_path, "content": {"parts": [{"text": text}]}}
            for attempt in range(6):
                response = requests.post(url, json=body, headers=headers, timeout=60)
                if response.status_code == 429 and attempt < 5:
                    retry_after = response.headers.get("Retry-After")
                    time.sleep(float(retry_after) if retry_after else min(2.0 * (2**attempt), 45.0))
                    continue
                response.raise_for_status()
                vectors.append(response.json()["embedding"]["values"])
                break
            time.sleep(0.3)  # gentle pacing for free-tier rate limits
        return vectors


def get_embedder() -> BaseEmbedder:
    settings = get_settings()
    if settings.embedding_provider == "openai":
        return OpenAIEmbedder()
    if settings.embedding_provider == "gemini":
        return GeminiEmbedder()
    raise EmbeddingConfigurationError(
        f"Unsupported EMBEDDING_PROVIDER={settings.embedding_provider}. Supported: openai, gemini."
    )

