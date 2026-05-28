from __future__ import annotations

import re


API_KEY_RE = re.compile(r"\b(sk-or-v1-[A-Za-z0-9_\-]{10,}|sk-[A-Za-z0-9_\-]{10,}|[A-Za-z0-9_\-]{32,})\b")
BEARER_RE = re.compile(r"\bBearer\s+([A-Za-z0-9._\-]{10,})", re.IGNORECASE)
PASSWORD_RE = re.compile(
    r"(?i)\b("
    r"(?:password|passwd|pass|kata\s*sandi|sandi)\s*(?:[:=]\s*|(?:saya|aku)\s*(?:adalah|is)?\s*[:=]?\s*|(?:adalah|is)\s+)"
    r")([^\s,;]{3,})"
)
OTP_RE = re.compile(r"(?i)\b(otp|kode\s*otp|verification\s*code|kode\s*verifikasi)\s*[:=]?\s*(\d{4,8})\b")
POSTGRES_URL_RE = re.compile(
    r"(postgres(?:ql)?(?:\+psycopg)?://[^:\s/@]+:)([^@\s]+)(@[^/\s]+/[^\s]+)",
    re.IGNORECASE,
)
URL_PASSWORD_RE = re.compile(r"(?i)(password=)([^&\s]+)")


def redact_sensitive(text: str | None, *, redact_passwords: bool = True) -> str:
    if not text:
        return ""

    value = str(text)
    value = POSTGRES_URL_RE.sub(r"\1[REDACTED]\3", value)
    value = BEARER_RE.sub("Bearer [REDACTED_TOKEN]", value)
    value = API_KEY_RE.sub("[REDACTED_API_KEY]", value)
    if redact_passwords:
        value = PASSWORD_RE.sub(lambda m: f"{m.group(1)}[REDACTED]", value)
    value = OTP_RE.sub(lambda m: f"{m.group(1)} [REDACTED]", value)
    value = URL_PASSWORD_RE.sub(r"\1[REDACTED]", value)
    return value


def contains_sensitive(text: str | None) -> bool:
    if not text:
        return False
    return any(
        pattern.search(text)
        for pattern in (API_KEY_RE, BEARER_RE, PASSWORD_RE, OTP_RE, POSTGRES_URL_RE, URL_PASSWORD_RE)
    )
