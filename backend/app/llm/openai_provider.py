from __future__ import annotations

import requests

from app.core.config import get_settings
from app.llm.base import BaseLLMProvider, LLMResponse, ProviderConfigurationError


class OpenAIProvider(BaseLLMProvider):
    provider_name = "openai"

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.openai_api_key
        self.model = settings.openai_model

    def ensure_configured(self) -> None:
        if not self.api_key:
            raise ProviderConfigurationError("Provider selected but API key is not configured.")

    def chat(self, messages: list[dict], temperature: float = 0.1) -> LLMResponse:
        self.ensure_configured()
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "messages": messages, "temperature": temperature},
            timeout=90,
        )
        response.raise_for_status()
        payload = response.json()
        return LLMResponse(payload["choices"][0]["message"]["content"], self.provider_name, self.model)

