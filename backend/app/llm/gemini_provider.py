from __future__ import annotations

import requests

from app.core.config import get_settings
from app.llm.base import BaseLLMProvider, LLMResponse, ProviderConfigurationError


class GeminiProvider(BaseLLMProvider):
    provider_name = "gemini"

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.gemini_api_key
        self.model = settings.gemini_model

    def ensure_configured(self) -> None:
        if not self.api_key:
            raise ProviderConfigurationError("Provider selected but API key is not configured.")

    def chat(self, messages: list[dict], temperature: float = 0.1) -> LLMResponse:
        self.ensure_configured()
        prompt = "\n\n".join(f"{message['role'].upper()}: {message['content']}" for message in messages)
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}",
            json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": temperature},
            },
            timeout=90,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["candidates"][0]["content"]["parts"][0]["text"]
        return LLMResponse(content, self.provider_name, self.model)

