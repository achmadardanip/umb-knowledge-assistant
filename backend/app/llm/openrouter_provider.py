from __future__ import annotations

import requests

from app.core.config import get_settings
from app.llm.base import BaseLLMProvider, LLMResponse, ProviderConfigurationError


class OpenRouterProvider(BaseLLMProvider):
    provider_name = "openrouter"

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.openrouter_api_key
        self.base_url = settings.openrouter_base_url.rstrip("/")
        self.model = settings.openrouter_model

    def ensure_configured(self) -> None:
        if not self.api_key:
            raise ProviderConfigurationError("Provider selected but API key is not configured.")

    def chat(self, messages: list[dict], temperature: float = 0.1) -> LLMResponse:
        self.ensure_configured()
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost",
                "X-Title": "UMB Knowledge Assistant",
            },
            json={"model": self.model, "messages": messages, "temperature": temperature},
            timeout=90,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        return LLMResponse(content=content, provider_used=self.provider_name, model_used=self.model)

