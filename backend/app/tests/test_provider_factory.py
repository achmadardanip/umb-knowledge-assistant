import pytest

from app.llm.base import ProviderConfigurationError
from app.llm.provider_factory import get_provider, normalize_provider


def test_provider_factory_chooses_openrouter_by_default():
    # openrouter is the built-in fallback default, independent of the operator's
    # AI_PROVIDER setting (which a deployment may override, e.g. to gemini).
    from app.core.config import _provider

    assert _provider(None) == "openrouter"
    assert _provider("") == "openrouter"
    assert _provider("does-not-exist") == "openrouter"


def test_provider_factory_returns_clear_error_if_api_key_missing():
    provider = get_provider("openrouter")
    provider.api_key = None
    with pytest.raises(ProviderConfigurationError, match="Provider selected but API key is not configured"):
        provider.ensure_configured()
