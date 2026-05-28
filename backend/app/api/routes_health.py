from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings


router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "service": "UMB Knowledge Assistant",
        "default_provider": settings.ai_provider,
        "discovery_domain": settings.discovery_domain,
    }

