from __future__ import annotations

from app.core.config import ProviderName, get_settings
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.azure_foundry_provider import AzureFoundryProvider
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
    "azure_foundry": AzureFoundryProvider,
}


def normalize_provider(provider: str | None) -> ProviderName:
    selected = (provider or get_settings().ai_provider).strip().lower()
    selected = {"ollama": "local_ollama", "lmstudio": "local_lmstudio", "lm_studio": "local_lmstudio",
                "azure": "azure_foundry", "foundry": "azure_foundry", "azure_ai_foundry": "azure_foundry"}.get(
        selected,
        selected,
    )
    if selected == "claude":
        selected = "anthropic"
    if selected not in PROVIDERS:
        selected = "local_ollama"
    return selected  # type: ignore[return-value]


def get_provider(provider_override: str | None = None,
                 model_override: str | None = None) -> BaseLLMProvider:
    provider_name = normalize_provider(provider_override)
    provider = PROVIDERS[provider_name]()
    # Per-request model override (used by the multi-model "brain comparison" audit).
    # Applied only when explicitly requested; harmless for providers exposing `.model`.
    if model_override and hasattr(provider, "model"):
        provider.model = model_override
    return provider


def ensure_provider_ready(provider_override: str | None = None) -> BaseLLMProvider:
    provider = get_provider(provider_override)
    try:
        provider.ensure_configured()
    except ProviderConfigurationError:
        raise
    return provider
