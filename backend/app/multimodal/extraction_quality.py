from __future__ import annotations


def confidence_label(score: float | None) -> str:
    if score is None:
        return "medium"
    if score >= 0.75:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def should_index(content: str, min_chars: int = 100, confidence: float | None = None) -> bool:
    if not content or len(content.strip()) < min_chars:
        return False
    if confidence is not None and confidence <= 0:
        return False
    return True

