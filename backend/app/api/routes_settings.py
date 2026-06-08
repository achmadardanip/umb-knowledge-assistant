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
            {
                "id": "hermes",
                "label": "Hermes",
                "configured": bool(settings.hermes_enabled and settings.hermes_api_key and settings.hermes_base_url),
                "model": settings.hermes_model,
            },
            {"id": "groq", "label": "Groq", "configured": bool(settings.groq_api_key), "model": settings.groq_model},
            {"id": "puter", "label": "Puter (gratis, tanpa API key)", "configured": True, "model": "browser"},
            {"id": "huggingface", "label": "Hugging Face (gratis)", "configured": bool(settings.huggingface_api_key), "model": settings.huggingface_model},
        ],
        "web_search": {
            "enabled": settings.web_search_enabled,
            "provider": settings.web_search_provider,
            "configured": bool(settings.tavily_api_key),
            "strict_domain": settings.web_search_strict_domain,
        },
    }
