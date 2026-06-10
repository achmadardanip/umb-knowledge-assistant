from __future__ import annotations

import requests

from app.core.config import get_settings
from app.llm.base import BaseLLMProvider, LLMResponse, ProviderConfigurationError


class HuggingFaceProvider(BaseLLMProvider):
    """Hugging Face Inference Providers router — OpenAI-compatible chat completions.

    Free serverless tier (set HF_TOKEN from a free huggingface.co account). A
    server-side free fallback for when a browser LLM isn't available. Endpoint:
    https://router.huggingface.co/v1 ; model e.g. meta-llama/Llama-3.1-8B-Instruct.
    """

    provider_name = "huggingface"

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.huggingface_api_key
        self.base_url = settings.huggingface_base_url.rstrip("/")
        self.model = settings.huggingface_model

    def ensure_configured(self) -> None:
        if not self.api_key:
            raise ProviderConfigurationError("Provider selected but HF_TOKEN is not configured.")

    def chat(self, messages: list[dict], temperature: float = 0.1) -> LLMResponse:
        self.ensure_configured()
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "messages": messages, "temperature": temperature},
            timeout=90,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        return LLMResponse(content=content, provider_used=self.provider_name, model_used=self.model)
