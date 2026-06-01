from __future__ import annotations

import requests

from app.core.config import get_settings
from app.llm.base import BaseLLMProvider, LLMResponse, ProviderConfigurationError


class HermesProvider(BaseLLMProvider):
    provider_name = "hermes"

    def __init__(self):
        settings = get_settings()
        self.enabled = settings.hermes_enabled
        self.api_key = settings.hermes_api_key
        self.base_url = settings.hermes_base_url.rstrip("/")
        self.model = settings.hermes_model

    def ensure_configured(self) -> None:
        if not self.enabled:
            raise ProviderConfigurationError("Hermes provider selected but HERMES_ENABLED is false.")
        if not self.api_key:
            raise ProviderConfigurationError("Hermes provider selected but HERMES_API_KEY is not configured.")
        if not self.base_url:
            raise ProviderConfigurationError("Hermes provider selected but HERMES_BASE_URL is not configured.")

    def chat(self, messages: list[dict], temperature: float = 0.1) -> LLMResponse:
        self.ensure_configured()
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self.model, "messages": messages, "temperature": temperature, "stream": False},
            timeout=120,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        return LLMResponse(content=content, provider_used=self.provider_name, model_used=self.model)
