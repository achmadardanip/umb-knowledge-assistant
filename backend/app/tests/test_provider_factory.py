import pytest

from app.llm.base import ProviderConfigurationError
from app.llm.provider_factory import get_provider, normalize_provider


def test_provider_factory_chooses_local_ollama_by_default():
    from app.core.config import _provider

    assert _provider(None) == "local_ollama"
    assert _provider("") == "local_ollama"
    assert _provider("does-not-exist") == "local_ollama"


def test_provider_factory_returns_clear_error_if_api_key_missing():
    provider = get_provider("openrouter")
    provider.api_key = None
    with pytest.raises(ProviderConfigurationError, match="Provider selected but API key is not configured"):
        provider.ensure_configured()
