from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings


router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/providers")
def providers() -> dict:
    settings = get_settings()
    return {
        "default_provider": settings.ai_provider,
        "providers": [
            {"id": "openrouter", "label": "OpenRouter", "configured": bool(settings.openrouter_api_key), "model": settings.openrouter_model},
            {"id": "openai", "label": "OpenAI", "configured": bool(settings.openai_api_key), "model": settings.openai_model},
            {"id": "gemini", "label": "Gemini", "configured": bool(settings.gemini_api_key), "model": settings.gemini_model},
            {"id": "anthropic", "label": "Claude", "configured": bool(settings.anthropic_api_key), "model": settings.anthropic_model},
        ],
        "web_search": {
            "enabled": settings.web_search_enabled,
            "provider": settings.web_search_provider,
            "configured": bool(settings.tavily_api_key),
            "strict_domain": settings.web_search_strict_domain,
        },
    }
