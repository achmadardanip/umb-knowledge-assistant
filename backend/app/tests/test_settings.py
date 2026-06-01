from types import SimpleNamespace

from app.api.routes_settings import providers


def test_hermes_provider_is_off_by_default(monkeypatch):
    settings = SimpleNamespace(
        ai_provider="openrouter",
        openrouter_api_key="key",
        openrouter_model="openai/gpt-oss-20b:free",
        openai_api_key=None,
        openai_model="gpt-4o-mini",
        gemini_api_key=None,
        gemini_model="gemini-1.5-flash",
        anthropic_api_key=None,
        anthropic_model="claude-3-5-haiku-latest",
        hermes_enabled=False,
        hermes_api_key=None,
        hermes_base_url="http://127.0.0.1:8642/v1",
        hermes_model="hermes-agent",
        web_search_enabled=True,
        web_search_provider="tavily",
        tavily_api_key="key",
        web_search_strict_domain="mercubuana.ac.id",
    )
    monkeypatch.setattr("app.api.routes_settings.get_settings", lambda: settings)

    payload = providers()
    hermes = next(provider for provider in payload["providers"] if provider["id"] == "hermes")

    assert hermes["configured"] is False
