from __future__ import annotations

import requests

from app.core.config import get_settings
from app.llm.base import BaseLLMProvider, LLMResponse, ProviderConfigurationError


class LocalLMStudioProvider(BaseLLMProvider):
    provider_name = "local_lmstudio"

    def __init__(self):
        settings = get_settings()
        self.base_url = settings.lmstudio_base_url.rstrip("/")
        self.model = settings.lmstudio_model
        self.api_key = settings.lmstudio_api_key
        self.max_tokens = settings.local_llm_max_tokens
        self.timeout = settings.local_llm_timeout_seconds
        self.default_temperature = settings.local_llm_temperature

    def ensure_configured(self) -> None:
        if not self.base_url:
            raise ProviderConfigurationError("LMSTUDIO_BASE_URL is not configured.")
        if not self.model:
            raise ProviderConfigurationError("LMSTUDIO_MODEL is not configured.")

    def chat(self, messages: list[dict], temperature: float | None = None) -> LLMResponse:
        self.ensure_configured()
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "messages": messages,
                "temperature": self.default_temperature if temperature is None else temperature,
                "max_tokens": self.max_tokens,
                "stream": False,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        content = str(payload["choices"][0]["message"]["content"])
        return LLMResponse(content=content, provider_used=self.provider_name, model_used=self.model)
