from app.discovery.scope_validator import is_allowed_host, validate_url_scope


def test_subdomain_validator_accepts_root_and_subdomains_only():
    assert is_allowed_host("mercubuana.ac.id", "mercubuana.ac.id")
    assert is_allowed_host("pmb.mercubuana.ac.id", "mercubuana.ac.id")
    assert not is_allowed_host("mercubuana.ac.id.evil.test", "mercubuana.ac.id")


def test_scope_validator_rejects_external_domains():
    assert not validate_url_scope("https://example.edu/berita").is_allowed


def test_scope_validator_rejects_sensitive_paths():
    assert not validate_url_scope("https://mercubuana.ac.id/phpmyadmin").is_allowed


def test_scope_validator_rejects_stateful_actions_but_keeps_information_queries():
    rejected = validate_url_scope(
        "https://feb.mercubuana.ac.id/page/2?action=yith-woocompare-add-product&id=398&_wpnonce=abc123"
    )
    allowed = validate_url_scope("https://mercubuana.ac.id/berita?id=7")

    assert rejected.is_allowed is False
    assert rejected.reason == "stateful_or_transactional_url"
    assert allowed.is_allowed is True
