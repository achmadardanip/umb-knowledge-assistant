from __future__ import annotations

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
)
from app.core.logging import configure_logging


configure_logging()

app = FastAPI(
    title="UMB Knowledge Assistant",
    description="Domain-governed multimodal RAG assistant for public Universitas Mercu Buana sources.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_health.router)
app.include_router(routes_settings.router)
app.include_router(routes_sessions.router)
app.include_router(routes_memory.router)
app.include_router(routes_chat.router)
app.include_router(routes_sources.router)
app.include_router(routes_discovery.router)
app.include_router(routes_multimodal.router)
app.include_router(routes_feedback.router)
app.include_router(routes_faq.router)

