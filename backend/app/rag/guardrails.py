from __future__ import annotations

import re

PRIVATE_DATA_RESPONSE = (
    "Saya tidak dapat mengakses atau menampilkan data pribadi mahasiswa. "
    "Silakan gunakan kanal resmi Universitas Mercu Buana."
)

# Always blocked: intent to attack, extract bulk private data, or a leaked secret.
_MALICIOUS_PATTERNS = (
    r"\bbypass\b",
    r"\bretas\b",
    r"\bhack(ing|ed)?\b",
    r"\bbobol\b",
    r"\bcuri\b",
    r"\bnyolong\b",
    r"\bambil\s+data\s+mahasiswa\b",
    r"\bdata\s+pribadi\s+mahasiswa\b",
    r"\bsk-[A-Za-z0-9]",
)

# Legitimate how-to / reset / recovery — these override the credential check below
# so "lupa password" and "cara reset password" are answered, not blocked.
_HELP_INTENT = (
    r"\blupa\b",
    r"\breset\b",
    r"\bganti\b",
    r"\bubah\b",
    r"\bcara\b",
    r"\bbagaimana\b",
    r"\bgimana\b",
    r"\bhow\s+to\b",
    r"\bforgot\b",
    r"\brecover\b",
    r"\bpulihkan\b",
    r"\bpanduan\b",
    r"\blangkah\b",
    r"\btidak\s+bisa\b",
    r"\bg(a|ak)\s+bisa\b",
)

# Explicit requests to DISCLOSE a credential (blocked when no help-intent is present).
_CREDENTIAL_REVEAL_PATTERNS = (
    r"\b(password|kata\s*sandi|otp|token|pin|credential)\s+(saya|ku|admin|akun|mahasiswa|dosen)\b",
    r"\b(password|kata\s*sandi)ku\b",
    r"\b(berikan|kasih|kasi|tampilkan|sebutkan|minta|bocorkan|spill|tuliskan)\b[\w\s]{0,25}\b(password|kata\s*sandi|otp|token|pin|credential)\b",
    r"\bapa\s+(password|kata\s*sandi|otp|pin)\s+(saya|ku|admin|akun)\b",
    r"\b(password|kata\s*sandi)\s+saya\s+apa\b",
    r"\bmy\s+[\w\s]{0,15}(password|otp|pin|credential)\b",
)


def is_disallowed_request(question: str) -> bool:
    lowered = (question or "").lower()
    if any(re.search(pattern, lowered) for pattern in _MALICIOUS_PATTERNS):
        return True
    if any(re.search(pattern, lowered) for pattern in _HELP_INTENT):
        return False
    return any(re.search(pattern, lowered) for pattern in _CREDENTIAL_REVEAL_PATTERNS)


def guardrail_response(question: str) -> str | None:
    if is_disallowed_request(question):
        return PRIVATE_DATA_RESPONSE
    return None
