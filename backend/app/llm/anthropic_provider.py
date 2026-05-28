from __future__ import annotations

import requests

from app.core.config import get_settings
from app.llm.base import BaseLLMProvider, LLMResponse, ProviderConfigurationError


class AnthropicProvider(BaseLLMProvider):
    provider_name = "anthropic"

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.anthropic_api_key
        self.model = settings.anthropic_model

    def ensure_configured(self) -> None:
        if not self.api_key:
            raise ProviderConfigurationError("Provider selected but API key is not configured.")

    def chat(self, messages: list[dict], temperature: float = 0.1) -> LLMResponse:
        self.ensure_configured()
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        user_messages = [m for m in messages if m["role"] != "system"]
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 1200,
                "temperature": temperature,
                "system": "\n\n".join(system_parts),
                "messages": user_messages,
            },
            timeout=90,
        )
        response.raise_for_status()
        payload = response.json()
        content = "".join(part.get("text", "") for part in payload.get("content", []) if part.get("type") == "text")
        return LLMResponse(content, self.provider_name, self.model)

