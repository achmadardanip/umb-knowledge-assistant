from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    routes_chat,
    routes_discovery,
    routes_faq,
    routes_feedback,
    routes_health,
    routes_memory,
    routes_multimodal,
    routes_sessions,
    routes_settings,
    routes_sources,
    routes_stats,
)
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.ingestion.embedder import get_embedder
from app.retrieval.reranker import get_reranker


configure_logging()
logger = logging.getLogger(__name__)


def _prewarm_local_embedder() -> None:
    """Load the local E5 model in the background on boot so the first dense query
    doesn't pay the ~12s model-load cost. No-op unless local embeddings + dense are on."""
    settings = get_settings()
    if settings.embedding_provider not in {"local", "local_e5", "e5"} or not settings.dense_retrieval_enabled:
        return

    def _warm() -> None:
        try:
            get_embedder().embed_query("warmup")
            logger.info("Local embedding model pre-warm completed.")
        except Exception:
            logger.warning("Local embedding model pre-warm failed.", exc_info=True)

    threading.Thread(target=_warm, daemon=True, name="local-e5-prewarm").start()


def _prewarm_local_reranker() -> None:
    """Load the gated local cross-encoder without delaying application startup."""
    settings = get_settings()
    if not settings.reranker_enabled or not settings.reranker_prewarm_enabled:
        return

    def _warm() -> None:
        try:
            get_reranker().score("warmup", ["warmup"])
            logger.info("Local reranker pre-warm completed.")
        except Exception:
            logger.warning("Local reranker pre-warm failed.", exc_info=True)

    threading.Thread(target=_warm, daemon=True, name="local-bge-reranker-prewarm").start()


def _prewarm_local_answer_model() -> None:
    """Ask Ollama to load the configured model without blocking FastAPI startup."""

    settings = get_settings()
    if settings.ai_provider != "local_ollama":
        return

    def _warm() -> None:
        try:
            response = requests.post(
                f"{settings.local_llm_base_url}/api/generate",
                json={"model": settings.local_llm_model, "prompt": "", "stream": False, "keep_alive": "30m"},
                timeout=settings.local_llm_timeout_seconds,
            )
            response.raise_for_status()
            logger.info("Local Ollama answer model pre-warm completed.")
        except Exception:
            logger.warning("Local Ollama answer model pre-warm failed.", exc_info=True)

    threading.Thread(target=_warm, daemon=True, name="local-ollama-prewarm").start()


def _prewarm_canonical_urls() -> None:
    """Warm the canonical-URL cache (v3 P1) so per-answer citation validation never
    triggers a Supabase read."""

    def _warm() -> None:
        try:
            from app.rag.canonical_urls import canonical_url_set

            count = len(canonical_url_set())
            logger.info("Canonical URL cache warmed (%s URLs).", count)
        except Exception:
            logger.warning("Canonical URL pre-warm failed.", exc_info=True)

    threading.Thread(target=_warm, daemon=True, name="canonical-urls-prewarm").start()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _prewarm_local_embedder()
    _prewarm_local_reranker()
    _prewarm_local_answer_model()
    _prewarm_canonical_urls()
    yield


app = FastAPI(
    title="UMB Knowledge Assistant",
    description="Domain-governed multimodal RAG assistant for public Universitas Mercu Buana sources.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_health.router)
app.include_router(routes_stats.router)
app.include_router(routes_settings.router)
app.include_router(routes_sessions.router)
app.include_router(routes_memory.router)
app.include_router(routes_chat.router)
app.include_router(routes_sources.router)
app.include_router(routes_discovery.router)
app.include_router(routes_multimodal.router)
app.include_router(routes_feedback.router)
app.include_router(routes_faq.router)
