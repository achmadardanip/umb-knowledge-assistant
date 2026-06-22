"""Phase 30 — Azure AI Foundry LLM provider (OpenAI-compatible chat completions).

Matches the BaseLLMProvider interface exactly (provider_name / model /
ensure_configured / chat) so it is a drop-in alongside Ollama/OpenAI/etc. Azure AI
Foundry exposes the Azure-OpenAI-style endpoint:

    POST {endpoint}/openai/deployments/{deployment}/chat/completions?api-version={ver}
    header: api-key: {key}

Errors are surfaced clearly (auth / rate-limit / timeout / unavailable model) so the
answer pipeline can fall back gracefully without ever fabricating an answer.

NB: placed at app/llm/azure_foundry_provider.py to match the existing flat provider
convention (the repo has no app/llm/providers/ subdir).
"""

from __future__ import annotations

import requests

from app.core.config import get_settings
from app.llm.base import BaseLLMProvider, LLMResponse, ProviderConfigurationError


class AzureFoundryError(RuntimeError):
    """Non-configuration runtime error from Azure (auth/rate-limit/timeout/model)."""


class AzureFoundryProvider(BaseLLMProvider):
    provider_name = "azure_foundry"

    def __init__(self) -> None:
        settings = get_settings()
        self.endpoint = (settings.azure_foundry_endpoint or "").rstrip("/")
        self.api_key = settings.azure_foundry_api_key
        self.model = settings.azure_foundry_deployment  # the deployment name is the "model"
        self.api_version = settings.azure_foundry_api_version
        self.timeout = 90

    # --- configuration ------------------------------------------------------
    def is_configured(self) -> bool:
        return bool(self.endpoint and self.api_key and self.model)

    def ensure_configured(self) -> None:
        if not self.endpoint:
            raise ProviderConfigurationError("AZURE_FOUNDRY_ENDPOINT is not set.")
        if not self.api_key:
            raise ProviderConfigurationError("AZURE_FOUNDRY_API_KEY is not set.")
        if not self.model:
            raise ProviderConfigurationError("AZURE_FOUNDRY_DEPLOYMENT is not set.")

    def _url(self) -> str:
        return (
            f"{self.endpoint}/openai/deployments/{self.model}/chat/completions"
            f"?api-version={self.api_version}"
        )

    # --- chat ---------------------------------------------------------------
    def chat(self, messages: list[dict], temperature: float = 0.1) -> LLMResponse:
        self.ensure_configured()
        try:
            response = requests.post(
                self._url(),
                headers={"api-key": self.api_key, "Content-Type": "application/json"},
                json={"messages": messages, "temperature": temperature},
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise AzureFoundryError(f"Azure Foundry request timed out after {self.timeout}s.") from exc
        except requests.RequestException as exc:
            raise AzureFoundryError(f"Azure Foundry connection error: {exc}") from exc

        if response.status_code in (401, 403):
            raise ProviderConfigurationError("Azure Foundry authentication failed (check AZURE_FOUNDRY_API_KEY).")
        if response.status_code == 404:
            raise AzureFoundryError(f"Azure Foundry deployment '{self.model}' not found (404).")
        if response.status_code == 429:
            raise AzureFoundryError("Azure Foundry rate limit exceeded (429); retry later.")
        response.raise_for_status()

        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AzureFoundryError(f"Unexpected Azure Foundry response shape: {str(payload)[:160]}") from exc
        return LLMResponse(content, self.provider_name, self.model)

    # --- streaming ----------------------------------------------------------
    def stream(self, messages: list[dict], temperature: float = 0.1):
        """Yield content deltas via SSE. The route layer drives step-level streaming;
        this enables token streaming when callers want it."""
        self.ensure_configured()
        import json as _json

        with requests.post(
            self._url(),
            headers={"api-key": self.api_key, "Content-Type": "application/json"},
            json={"messages": messages, "temperature": temperature, "stream": True},
            timeout=self.timeout,
            stream=True,
        ) as response:
            if response.status_code in (401, 403):
                raise ProviderConfigurationError("Azure Foundry authentication failed.")
            response.raise_for_status()
            for raw in response.iter_lines(decode_unicode=True):
                if not raw or not raw.startswith("data:"):
                    continue
                data = raw[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    delta = _json.loads(data)["choices"][0]["delta"].get("content")
                except (KeyError, IndexError, ValueError, TypeError):
                    continue
                if delta:
                    yield delta

    # --- health -------------------------------------------------------------
    def health(self) -> dict:
        """Lightweight status for /system/health (no token spend on a happy path)."""
        if not self.is_configured():
            missing = [k for k, v in (("endpoint", self.endpoint), ("api_key", self.api_key),
                                      ("deployment", self.model)) if not v]
            return {"status": "unconfigured", "missing": missing}
        try:
            r = requests.get(f"{self.endpoint}/openai/models?api-version={self.api_version}",
                             headers={"api-key": self.api_key}, timeout=8)
            if r.status_code in (401, 403):
                return {"status": "auth_error"}
            return {"status": "healthy" if r.status_code < 500 else "degraded", "http": r.status_code}
        except requests.RequestException as exc:
            return {"status": "unreachable", "error": str(exc)[:80]}
