from app.core.redaction import redact_sensitive


def test_redact_sensitive_values_before_saving_messages():
    assert redact_sensitive("password saya 123456") == "password saya [REDACTED]"
    assert redact_sensitive("sk-or-v1-abcdefghijklmnop") == "[REDACTED_API_KEY]"
    assert redact_sensitive("Bearer abcdefghijklmnop") == "Bearer [REDACTED_TOKEN]"
    assert "secret" not in redact_sensitive("postgresql://postgres:secret@host/db")


def test_redaction_does_not_hide_password_reset_guidance():
    assert "password reset" in redact_sensitive("ikuti panduan password reset SIA")
    assert "reset password" in redact_sensitive("gunakan menu reset password")
