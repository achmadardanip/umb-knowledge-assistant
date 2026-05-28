from __future__ import annotations

from app.core.redaction import redact_sensitive


HIDDEN_REASONING_MARKERS = (
    "<think>",
    "</think>",
    "chain-of-thought",
    "hidden reasoning",
    "private reasoning",
)


def strip_hidden_reasoning(text: str | None) -> str:
    if not text:
        return ""
    value = str(text)
    lowered = value.lower()
    if "<think>" in lowered and "</think>" in lowered:
        start = lowered.find("<think>")
        end = lowered.find("</think>", start) + len("</think>")
        value = value[:start] + value[end:]
    for marker in HIDDEN_REASONING_MARKERS:
        value = value.replace(marker, "")
        value = value.replace(marker.title(), "")
    return value.strip()


def sanitize_user_visible_text(text: str | None, *, redact_passwords: bool = True) -> str:
    return redact_sensitive(strip_hidden_reasoning(text), redact_passwords=redact_passwords)
