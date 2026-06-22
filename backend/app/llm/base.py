from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal


ProviderName = Literal[
    "local_ollama",
    "local_lmstudio",
    "openrouter",
    "openai",
    "gemini",
    "anthropic",
    "hermes",
    "groq",
    "huggingface",
    "azure_foundry",
]


class ProviderConfigurationError(RuntimeError):
    pass


@dataclass
class LLMResponse:
    content: str
    provider_used: ProviderName
    model_used: str


class BaseLLMProvider(ABC):
    provider_name: ProviderName
    model: str

    @abstractmethod
    def ensure_configured(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def chat(self, messages: list[dict], temperature: float = 0.1) -> LLMResponse:
        raise NotImplementedError
