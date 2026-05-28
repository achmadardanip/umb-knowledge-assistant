from app.discovery.scope_validator import is_allowed_host, validate_url_scope


def test_subdomain_validator_accepts_root_and_subdomains_only():
    assert is_allowed_host("mercubuana.ac.id", "mercubuana.ac.id")
    assert is_allowed_host("pmb.mercubuana.ac.id", "mercubuana.ac.id")
    assert not is_allowed_host("mercubuana.ac.id.evil.test", "mercubuana.ac.id")


def test_scope_validator_rejects_external_domains():
    assert not validate_url_scope("https://example.edu/berita").is_allowed


def test_scope_validator_rejects_sensitive_paths():
    assert not validate_url_scope("https://mercubuana.ac.id/phpmyadmin").is_allowed

