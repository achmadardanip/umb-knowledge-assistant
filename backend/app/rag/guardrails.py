from __future__ import annotations

import re


PRIVATE_DATA_PATTERNS = (
    r"\bpassword\b",
    r"\bkata\s*sandi\b",
    r"\botp\b",
    r"\btoken\b",
    r"\bambil\s+data\s+mahasiswa\b",
    r"\bdata\s+pribadi\s+mahasiswa\b",
    r"\bbypass\b",
    r"\bretas\b",
    r"\bhack\b",
    r"\bcredential\b",
    r"\bsk-[A-Za-z0-9]",
)


PRIVATE_DATA_RESPONSE = (
    "Saya tidak dapat mengakses atau menampilkan data pribadi mahasiswa. "
    "Silakan gunakan kanal resmi Universitas Mercu Buana."
)


def is_disallowed_request(question: str) -> bool:
    lowered = (question or "").lower()
    return any(re.search(pattern, lowered) for pattern in PRIVATE_DATA_PATTERNS)


def guardrail_response(question: str) -> str | None:
    if is_disallowed_request(question):
        return PRIVATE_DATA_RESPONSE
    return None

