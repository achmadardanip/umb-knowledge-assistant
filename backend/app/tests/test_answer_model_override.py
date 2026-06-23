from app.llm.local_ollama_provider import LocalOllamaProvider
from app.llm.provider_factory import get_provider


def test_provider_uses_model_override():
    assert LocalOllamaProvider(model_override="gemma2:9b").model == "gemma2:9b"


def test_provider_defaults_to_settings_model():
    p = LocalOllamaProvider()
    assert p.model  # non-empty, from settings.local_llm_model


def test_get_provider_applies_model_override():
    p = get_provider("local_ollama", model_override="mistral:7b")
    assert p.model == "mistral:7b"


def test_get_provider_without_override_uses_settings_default():
    p = get_provider("local_ollama")
    assert p.model and p.model != "mistral:7b"
