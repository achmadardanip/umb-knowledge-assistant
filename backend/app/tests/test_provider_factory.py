import pytest

from app.llm.base import ProviderConfigurationError
from app.llm.provider_factory import get_provider, normalize_provider


def test_provider_factory_chooses_openrouter_by_default():
    assert normalize_provider(None) == "openrouter"
    assert get_provider(None).provider_name == "openrouter"


def test_provider_factory_returns_clear_error_if_api_key_missing():
    provider = get_provider("openrouter")
    provider.api_key = None
    with pytest.raises(ProviderConfigurationError, match="Provider selected but API key is not configured"):
        provider.ensure_configured()
