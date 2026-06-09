from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod

import requests

from app.core.config import get_settings


logger = logging.getLogger(__name__)


class EmbeddingConfigurationError(RuntimeError):
    pass


class BaseEmbedder(ABC):
    provider_name = "unknown"
    model = "unknown"
    dimension: int | None = None
    profile: str | None = None
    version = "1"
    storage = "legacy"

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]


class OpenAIEmbedder(BaseEmbedder):
    provider_name = "openai"

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

    provider_name = "gemini"

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


# Process-level cache of loaded SentenceTransformer models, keyed by (model, device).
# A single inference lock avoids concurrent MPS execution while startup warm-up
# and request threads share the cached model.
_ENCODER_CACHE: dict = {}
_ENCODER_CACHE_LOCK = threading.Lock()
_ENCODER_INFERENCE_LOCK = threading.Lock()


class LocalE5Embedder(BaseEmbedder):
    """Lazy local multilingual E5 embedder for Apple Silicon and CPU runtimes."""

    provider_name = "local_e5"
    storage = "sidecar"

    def __init__(self, model: str | None = None):
        settings = get_settings()
        self.model = model or settings.local_embedding_model
        self.dimension = settings.local_embedding_dimension
        self.profile = settings.embedding_profile
        self.version = settings.embedding_version
        self.batch_size = max(1, settings.local_embedding_batch_size)
        self.device = None if settings.local_embedding_device == "auto" else settings.local_embedding_device
        self._encoder = None
        if self.dimension != 384:
            raise EmbeddingConfigurationError(
                "LOCAL_EMBEDDING_DIMENSION must be 384 for intfloat/multilingual-e5-small "
                "and the chunk_embeddings vector(384) schema."
            )

    def _load_encoder(self):
        if self._encoder is not None:
            return self._encoder
        key = (self.model, self.device)
        cached = _ENCODER_CACHE.get(key)
        if cached is not None:
            self._encoder = cached
            return cached
        with _ENCODER_CACHE_LOCK:
            cached = _ENCODER_CACHE.get(key)
            if cached is None:
                try:
                    from sentence_transformers import SentenceTransformer
                except ImportError as exc:
                    raise EmbeddingConfigurationError(
                        "Local E5 embeddings require the optional local dependencies. "
                        "Install backend/requirements-local.txt first."
                    ) from exc
                kwargs = {"device": self.device} if self.device else {}
                cached = SentenceTransformer(self.model, **kwargs)
                _ENCODER_CACHE[key] = cached
        self._encoder = cached
        return cached

    def _encode(self, texts: list[str], *, prefix: str) -> list[list[float]]:
        if not texts:
            return []
        encoder = self._load_encoder()
        with _ENCODER_INFERENCE_LOCK:
            vectors = encoder.encode(
                [f"{prefix}: {text}" for text in texts],
                batch_size=self.batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
        result = [vector.tolist() for vector in vectors]
        for vector in result:
            if len(vector) != self.dimension:
                raise RuntimeError(
                    f"Embedding dimension mismatch for {self.model}: expected {self.dimension}, got {len(vector)}."
                )
        return result

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts, prefix="passage")

    def embed_query(self, query: str) -> list[float]:
        return self._encode([query], prefix="query")[0]


def get_embedder() -> BaseEmbedder:
    settings = get_settings()
    if settings.embedding_provider == "openai":
        return OpenAIEmbedder()
    if settings.embedding_provider == "gemini":
        return GeminiEmbedder()
    if settings.embedding_provider in {"local", "local_e5", "e5"}:
        return LocalE5Embedder()
    raise EmbeddingConfigurationError(
        f"Unsupported EMBEDDING_PROVIDER={settings.embedding_provider}. Supported: openai, gemini, local_e5."
    )
