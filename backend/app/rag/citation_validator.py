from __future__ import annotations

import re
from urllib.parse import urlparse

from app.discovery.scope_validator import is_allowed_host, validate_url_scope
from app.discovery.url_normalizer import is_archive_url, normalize_url


FALLBACK_ANSWER = "Saya belum menemukan informasi resmi terkait pertanyaan tersebut pada sumber publik Universitas Mercu Buana yang tersedia."


def _normalize_confidence(value) -> str:
    if isinstance(value, (int, float)):
        if value >= 0.75:
            return "high"
        if value >= 0.4:
            return "medium"
        return "low"
    normalized = str(value or "medium").strip().lower()
    if normalized in {"high", "medium", "low"}:
        return normalized
    return "medium"


def _source_key(source: dict) -> tuple:
    return (
        source.get("url"),
        source.get("page_number"),
        source.get("slide_number"),
        source.get("sheet_name"),
        source.get("row_range"),
        source.get("timestamp_start"),
        source.get("timestamp_end"),
    )


def _extract_citation_markers(answer: str) -> set[int]:
    return {int(match) for match in re.findall(r"\[(\d+)\]", answer or "")}


def validate_citations(
    payload: dict,
    retrieved_contexts: list[dict],
    root_domain: str = "mercubuana.ac.id",
    *,
    require_citation_markers: bool = False,
) -> dict:
    raw_answer = payload.get("answer")
    if isinstance(raw_answer, list):
        answer = "\n".join(str(item) for item in raw_answer).strip()
    elif isinstance(raw_answer, str):
        answer = raw_answer.strip()
    else:
        answer = str(raw_answer or "").strip()
    payload = {**payload, "answer": answer}
    retrieved_by_url = {context.get("url"): context for context in retrieved_contexts if context.get("url")}
    retrieved_by_normalized_url = {
        normalize_url(context.get("url")): context for context in retrieved_contexts if context.get("url")
    }
    valid_sources = []
    for source in payload.get("sources") or []:
        if isinstance(source, str):
            source = {"url": source}
        if not isinstance(source, dict):
            continue
        url = source.get("url")
        context = retrieved_by_url.get(url) or (retrieved_by_normalized_url.get(normalize_url(url)) if url else None)
        if not url or not context:
            continue
        if is_archive_url(url):
            continue
        url_decision = validate_url_scope(url, root_domain)
        if not url_decision.is_allowed:
            continue
        parsed_hostname = (urlparse(url).hostname or "").lower()
        if not is_allowed_host(parsed_hostname, root_domain):
            continue
        context_url = context.get("url")
        if not context_url or not validate_url_scope(context_url, root_domain).is_allowed:
            continue
        if source.get("source_type") == "pdf" and source.get("page_number") and context.get("page_number"):
            if int(source["page_number"]) != int(context["page_number"]):
                continue
        valid = dict(context)
        valid.update({k: v for k, v in source.items() if v is not None and k != "url"})
        valid["hostname"] = valid.get("hostname") or parsed_hostname
        valid_sources.append(valid)

    if not answer or payload.get("not_found") is True or not retrieved_contexts:
        return {
            **payload,
            "answer": FALLBACK_ANSWER,
            "sources": [],
            "confidence": "low",
            "not_found": True,
        }

    if not valid_sources:
        return {
            **payload,
            "answer": FALLBACK_ANSWER,
            "sources": [],
            "confidence": "low",
            "not_found": True,
        }

    low_confidence_sources = [
        source
        for source in valid_sources
        if source.get("source_type") in {"image", "audio", "video"} and (source.get("extraction_confidence") or 0) < 0.5
    ]
    confidence = _normalize_confidence(payload.get("confidence") or "medium")
    if low_confidence_sources and confidence == "high":
        confidence = "medium"

    seen = set()
    deduped = []
    for source in valid_sources:
        key = _source_key(source)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)

    for index, source in enumerate(deduped, start=1):
        source["citation_id"] = int(source.get("citation_id") or index)

    if require_citation_markers:
        markers = _extract_citation_markers(answer)
        valid_ids = {int(source["citation_id"]) for source in deduped}
        if not markers or not markers.issubset(valid_ids):
            return {
                **payload,
                "answer": FALLBACK_ANSWER,
                "sources": [],
                "confidence": "low",
                "not_found": True,
            }

    return {**payload, "answer": answer, "sources": deduped, "confidence": confidence, "not_found": False}
