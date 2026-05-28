from __future__ import annotations

from app.core.redaction import redact_sensitive


def compact_context(lines: list[str], max_chars: int = 1500) -> str:
    return redact_sensitive("\n".join(lines))[:max_chars]

