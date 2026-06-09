"""Trust-aware heuristic and optional local cross-encoder re-ranking."""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Sequence

from app.core.config import get_settings
from app.retrieval.fusion import tahf_score
from app.trust.authority import host_authority


logger = logging.getLogger(__name__)


class RerankerConfigurationError(RuntimeError):
    pass


_RERANKER_CACHE: dict[tuple[str, str, int], object] = {}
_RERANKER_CACHE_LOCK = threading.Lock()
_RERANKER_INFERENCE_LOCK = threading.Lock()


def _resolve_device(configured: str) -> str:
    if configured != "auto":
        return configured
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
    except (ImportError, AttributeError):
        pass
    return "cpu"


def _build_cross_encoder(model: str, *, device: str, max_length: int):
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as exc:
        raise RerankerConfigurationError(
            "Local BGE reranking requires backend/requirements-local.txt."
        ) from exc
    return CrossEncoder(model, device=device, max_length=max_length)


def _clear_reranker_cache() -> None:
    """Clear process-local model state. Intended for tests."""
    with _RERANKER_CACHE_LOCK:
        _RERANKER_CACHE.clear()


class LocalBGEReranker:
    """Lazy multilingual BGE cross-encoder with a shared process cache."""

    provider_name = "local_bge"

    def __init__(self, model: str | None = None):
        settings = get_settings()
        self.model = model or settings.reranker_model
        self.batch_size = max(1, settings.reranker_batch_size)
        self.max_length = max(32, settings.reranker_max_length)
        self.device = _resolve_device(settings.reranker_device)
        self._encoder = None

    def _load_encoder(self):
        if self._encoder is not None:
            return self._encoder
        key = (self.model, self.device, self.max_length)
        cached = _RERANKER_CACHE.get(key)
        if cached is not None:
            self._encoder = cached
            return cached
        with _RERANKER_CACHE_LOCK:
            cached = _RERANKER_CACHE.get(key)
            if cached is None:
                cached = _build_cross_encoder(
                    self.model,
                    device=self.device,
                    max_length=self.max_length,
                )
                _RERANKER_CACHE[key] = cached
        self._encoder = cached
        return cached

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []
        encoder = self._load_encoder()
        pairs = [(query, document) for document in documents]
        with _RERANKER_INFERENCE_LOCK:
            predictions = encoder.predict(
                pairs,
                batch_size=self.batch_size,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
        raw_scores = predictions.tolist() if hasattr(predictions, "tolist") else list(predictions)
        if isinstance(raw_scores, (int, float)):
            raw_scores = [raw_scores]
        scores = [
            _sigmoid(float(value[0] if isinstance(value, list) and len(value) == 1 else value))
            for value in raw_scores
        ]
        if len(scores) != len(documents):
            raise RuntimeError(
                f"Reranker returned {len(scores)} scores for {len(documents)} documents."
            )
        return scores


def get_reranker() -> LocalBGEReranker:
    settings = get_settings()
    if settings.reranker_provider in {"local", "local_bge", "bge"}:
        return LocalBGEReranker()
    raise RerankerConfigurationError(
        f"Unsupported RERANKER_PROVIDER={settings.reranker_provider}. Supported: local_bge."
    )


def _sigmoid(value: float) -> float:
    if value >= 0:
        factor = math.exp(-value)
        return 1.0 / (1.0 + factor)
    factor = math.exp(value)
    return factor / (1.0 + factor)


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    low, high = min(values), max(values)
    spread = high - low
    if spread <= 0:
        return [1.0 for _ in values]
    return [(value - low) / spread for value in values]


def confidence_boost(source_type: str | None, extraction_confidence: float | None) -> float:
    score = 0.0
    if source_type in {"html", "pdf"}:
        score += 0.15
    if source_type in {"image", "audio", "video"}:
        score -= 0.1
    if extraction_confidence is not None:
        score += max(min(extraction_confidence, 1.0), 0.0) * 0.2
        if extraction_confidence < 0.5:
            score -= 0.25
    return score


def _document_text(context: dict) -> str:
    title = (context.get("title") or "").strip()
    text = (context.get("chunk_text") or "").strip()
    return f"{title}\n{text}" if title else text


def rerank_contexts(contexts: list[dict], *, root_domain: str = "mercubuana.ac.id") -> list[dict]:
    """Apply the existing heuristic/TAHF ranking without a model."""
    settings = get_settings()
    alpha = settings.tahf_authority_weight
    beta = settings.tahf_freshness_weight
    for context in contexts:
        retrieval_score = float(context.get("retrieval_score", context.get("score", 0.0)))
        context["retrieval_score"] = retrieval_score
        relevance = retrieval_score + confidence_boost(
            context.get("source_type"), context.get("extraction_confidence")
        )
        authority = host_authority(context.get("hostname"), root_domain)
        context_freshness = context.get("freshness")
        context_freshness = 1.0 if context_freshness is None else float(context_freshness)
        context["authority"] = authority
        context["freshness"] = context_freshness
        context.setdefault("reranker_used", False)
        context["score"] = tahf_score(relevance, authority, context_freshness, alpha=alpha, beta=beta)
    return sorted(contexts, key=lambda item: item.get("score", 0.0), reverse=True)


def model_rerank_contexts(
    query: str,
    contexts: list[dict],
    *,
    root_domain: str = "mercubuana.ac.id",
    reranker: LocalBGEReranker | None = None,
) -> list[dict]:
    """Rerank the strongest candidates and preserve the input order on failure."""
    if not contexts:
        return []
    settings = get_settings()
    baseline = sorted(contexts, key=lambda item: float(item.get("score") or 0.0), reverse=True)
    candidate_count = min(len(baseline), max(1, settings.reranker_candidate_k))
    candidates = baseline[:candidate_count]
    remainder = baseline[candidate_count:]
    for context in remainder:
        context.setdefault("reranker_used", False)
    retrieval_scores = [
        float(context.get("retrieval_score", context.get("score", 0.0)))
        for context in candidates
    ]
    try:
        active_reranker = reranker or get_reranker()
        model_scores = active_reranker.score(
            query,
            [_document_text(context) for context in candidates],
        )
        if len(model_scores) != len(candidates):
            raise RuntimeError(
                f"Reranker returned {len(model_scores)} scores for {len(candidates)} candidates."
            )
        normalized_retrieval = _normalize(retrieval_scores)
        model_weight = min(max(settings.reranker_model_weight, 0.0), 1.0)
        alpha = settings.tahf_authority_weight
        beta = settings.tahf_freshness_weight
        updates: list[dict] = []
        for context, retrieval_score, normalized_score, raw_model_score in zip(
            candidates,
            retrieval_scores,
            normalized_retrieval,
            model_scores,
            strict=True,
        ):
            model_score = float(raw_model_score)
            relevance = (
                model_weight * model_score
                + (1.0 - model_weight) * normalized_score
                + confidence_boost(context.get("source_type"), context.get("extraction_confidence"))
            )
            authority = host_authority(context.get("hostname"), root_domain)
            freshness = context.get("freshness")
            freshness = 1.0 if freshness is None else float(freshness)
            updates.append(
                {
                    "retrieval_score": retrieval_score,
                    "reranker_score": model_score,
                    "reranker_model": active_reranker.model,
                    "reranker_used": True,
                    "relevance": relevance,
                    "authority": authority,
                    "freshness": freshness,
                    "score": tahf_score(
                        relevance,
                        authority,
                        freshness,
                        alpha=alpha,
                        beta=beta,
                    ),
                }
            )
    except Exception:
        logger.warning("Local model reranking failed; preserving baseline ranking.", exc_info=True)
        return baseline

    for context, update in zip(candidates, updates, strict=True):
        context.update(update)

    candidates.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    return candidates + remainder
