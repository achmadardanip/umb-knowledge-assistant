from __future__ import annotations


def confidence_boost(source_type: str | None, extraction_confidence: float | None) -> float:
    score = 0.0
    if source_type in {"html", "pdf"}:
        score += 0.15
    if source_type in {"image", "audio", "video"}:
        score -= 0.1
    if extraction_confidence is not None:
        score += max(min(extraction_confidence, 1.0), 0.0) * 0.2
        if extraction_confidence < 0.5:
            score -= 0.25
    return score


def rerank_contexts(contexts: list[dict]) -> list[dict]:
    for context in contexts:
        context["score"] = float(context.get("score", 0.0)) + confidence_boost(
            context.get("source_type"), context.get("extraction_confidence")
        )
    return sorted(contexts, key=lambda item: item.get("score", 0.0), reverse=True)

