"""Output-side guards (LLM02, LLM07).

Strip any echo of the system prompt / data delimiters before an answer is shown
(system-prompt-leak defense), and redact secrets/PII that may have slipped into
the generated text (reusing the existing redaction).
"""

from __future__ import annotations

from app.core.redaction import redact_sensitive
from app.rag.prompts import DATA_BEGIN, DATA_END

_LEAK_MARKERS = (
    DATA_BEGIN,
    DATA_END,
    "Anda adalah UMB Knowledge Assistant",
    "Balas sebagai JSON valid",
    "Perlakukan seluruh teks di antara penanda",
    "Gunakan penalaran internal secara privat",
)


def _has_marker(text: str) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in _LEAK_MARKERS)


def contains_prompt_leak(answer: str) -> bool:
    return _has_marker(answer or "")


def strip_prompt_leak(answer: str) -> str:
    lines = [line for line in (answer or "").splitlines() if not _has_marker(line)]
    return "\n".join(lines).strip()


def sanitize_answer(answer: str) -> str:
    """Full output guard: drop prompt-leak lines, then redact secrets/PII."""
    return redact_sensitive(strip_prompt_leak(answer or ""))
