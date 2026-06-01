from __future__ import annotations

from app.core.config import ProviderName, get_settings
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import BaseLLMProvider, ProviderConfigurationError
from app.llm.gemini_provider import GeminiProvider
from app.llm.hermes_provider import HermesProvider
from app.llm.openai_provider import OpenAIProvider
from app.llm.openrouter_provider import OpenRouterProvider


PROVIDERS: dict[str, type[BaseLLMProvider]] = {
    "openrouter": OpenRouterProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "anthropic": AnthropicProvider,
    "hermes": HermesProvider,
}


def normalize_provider(provider: str | None) -> ProviderName:
    selected = (provider or get_settings().ai_provider).strip().lower()
    if selected == "claude":
        selected = "anthropic"
    if selected not in PROVIDERS:
        selected = "openrouter"
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
