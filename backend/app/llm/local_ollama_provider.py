from __future__ import annotations

import requests

from app.core.config import get_settings
from app.llm.base import BaseLLMProvider, LLMResponse, ProviderConfigurationError


class LocalOllamaProvider(BaseLLMProvider):
    provider_name = "local_ollama"

    def __init__(self):
        settings = get_settings()
        self.base_url = settings.local_llm_base_url.rstrip("/")
        self.model = settings.local_llm_model
        self.max_tokens = settings.local_llm_max_tokens
        self.timeout = settings.local_llm_timeout_seconds
        self.default_temperature = settings.local_llm_temperature

    def ensure_configured(self) -> None:
        if not self.base_url:
            raise ProviderConfigurationError("LOCAL_LLM_BASE_URL is not configured.")
        if not self.model:
            raise ProviderConfigurationError("LOCAL_LLM_MODEL is not configured.")

    def chat(self, messages: list[dict], temperature: float | None = None) -> LLMResponse:
        self.ensure_configured()
        response = requests.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": self.default_temperature if temperature is None else temperature,
                    "num_predict": self.max_tokens,
                },
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        content = str((payload.get("message") or {}).get("content") or payload.get("response") or "")
        if not content.strip():
            raise RuntimeError("Ollama returned an empty response.")
        return LLMResponse(content=content, provider_used=self.provider_name, model_used=self.model)
