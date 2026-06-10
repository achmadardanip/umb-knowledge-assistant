from app.discovery.scope_validator import is_allowed_host, validate_url_scope


def test_domain_filter_only_accepts_umb_scope():
    assert is_allowed_host("mercubuana.ac.id")
    assert is_allowed_host("fakultas.mercubuana.ac.id")
    assert not is_allowed_host("evilmercubuana.ac.id.com")
    assert not is_allowed_host("example.com")


def test_subdomain_url_with_path_is_allowed():
    decision = validate_url_scope("https://pmb.mercubuana.ac.id/pendaftaran")
    assert decision.is_allowed


def test_private_url_filter_rejects_login_admin_auth_pages():
    for url in [
        "https://mercubuana.ac.id/login",
        "https://sia.mercubuana.ac.id/admin",
        "https://mercubuana.ac.id/reset-password",
        "https://mercubuana.ac.id/.env",
    ]:
        decision = validate_url_scope(url)
        assert not decision.is_allowed
        assert decision.reason == "sensitive_or_private_path"


def test_search_and_generated_paths_are_not_knowledge_sources():
    for url in [
        "https://mercubuana.ac.id/search?q=pendaftaran",
        "https://mercubuana.ac.id/usage_events",
    ]:
        decision = validate_url_scope(url)
        assert not decision.is_allowed
        assert decision.reason == "sensitive_or_private_path"


def test_lookalike_subdomain_is_rejected():
    decision = validate_url_scope("https://mercubuana.ac.id.evil.com/pendaftaran")
    assert not decision.is_allowed
    assert decision.reason == "outside_allowed_domain"
