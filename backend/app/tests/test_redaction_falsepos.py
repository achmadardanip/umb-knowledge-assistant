from app.core.redaction import redact_sensitive


def test_url_slug_not_redacted_as_api_key():
    s = "Artikel wisuda-umb-tegaskan-pendidikan-sebagai-fondasi-karakter dipublikasikan."
    assert "[REDACTED_API_KEY]" not in redact_sensitive(s)


def test_concatenated_title_not_redacted():
    s = "Webinar MasterNetworkingandTimeManagement diadakan daring."
    assert redact_sensitive(s) == s


def test_long_underscored_title_not_redacted():
    s = "Dokumen _ANALISA_MEKANISME_PENGHITUNGAN_PEMOTONGAN tersedia."
    assert "[REDACTED_API_KEY]" not in redact_sensitive(s)


def test_real_openrouter_key_still_redacted():
    s = "bocor sk-or-v1-abcdef0123456789abcdef0123456789 di log"
    assert "[REDACTED_API_KEY]" in redact_sensitive(s)


def test_high_entropy_token_still_redacted():
    s = "token A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0uVwXyZ"
    assert "[REDACTED_API_KEY]" in redact_sensitive(s)
