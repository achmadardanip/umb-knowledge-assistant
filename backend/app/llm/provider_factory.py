from __future__ import annotations

from app.core.config import ProviderName, get_settings
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import BaseLLMProvider, ProviderConfigurationError
from app.llm.gemini_provider import GeminiProvider
from app.llm.groq_provider import GroqProvider
from app.llm.hermes_provider import HermesProvider
from app.llm.huggingface_provider import HuggingFaceProvider
from app.llm.local_lmstudio_provider import LocalLMStudioProvider
from app.llm.local_ollama_provider import LocalOllamaProvider
from app.llm.openai_provider import OpenAIProvider
from app.llm.openrouter_provider import OpenRouterProvider


PROVIDERS: dict[str, type[BaseLLMProvider]] = {
    "local_ollama": LocalOllamaProvider,
    "local_lmstudio": LocalLMStudioProvider,
    "openrouter": OpenRouterProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "anthropic": AnthropicProvider,
    "hermes": HermesProvider,
    "groq": GroqProvider,
    "huggingface": HuggingFaceProvider,
}


def normalize_provider(provider: str | None) -> ProviderName:
    selected = (provider or get_settings().ai_provider).strip().lower()
    selected = {"ollama": "local_ollama", "lmstudio": "local_lmstudio", "lm_studio": "local_lmstudio"}.get(
        selected,
        selected,
    )
    if selected == "claude":
        selected = "anthropic"
    if selected not in PROVIDERS:
        selected = "local_ollama"
    return selected  # type: ignore[return-value]


def get_provider(provider_override: str | None = None) -> BaseLLMProvider:
    provider_name = normalize_provider(provider_override)
    provider = PROVIDERS[provider_name]()
    return provider


def ensure_provider_ready(provider_override: str | None = None) -> BaseLLMProvider:
    provider = get_provider(provider_override)
    try:
        provider.ensure_configured()
    except ProviderConfigurationError:
        raise
    return provider
