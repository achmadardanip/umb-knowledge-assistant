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


_URL_RE = re.compile(r"https?://[^\s\)\]\}\"'<>]+")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)")


def _norm_url(url: str) -> str:
    try:
        return normalize_url((url or "").rstrip("/.,;:)]}"))
    except Exception:
        return (url or "").strip().rstrip("/.,;:)]}").lower()


def verified_url_set(contexts: list[dict], extra: set[str] | None = None) -> set[str]:
    """Normalized URLs that are traceable to the KB: each retrieved context's url
    plus any ``source_urls`` it carries (FAQ/scholarship), plus ``extra`` (e.g. the
    canonical_urls table)."""
    verified: set[str] = set(extra or set())
    for ctx in contexts or []:
        url = ctx.get("url")
        if url:
            verified.add(_norm_url(url))
        for su in ctx.get("source_urls") or []:
            if su:
                verified.add(_norm_url(su))
    return verified


def scrub_unverified_urls(answer: str, verified: set[str]) -> str:
    """Remove any inline URL in the answer text that is NOT traceable to the KB.
    Prevents URL fabrication (e.g. a slug-built faculty URL the model invented).
    Markdown links keep their anchor text; bare fabricated URLs are dropped."""
    if not answer:
        return answer
    verified = {_norm_url(u) for u in verified}  # normalize defensively

    def _md(m: re.Match) -> str:
        text, url = m.group(1), m.group(2)
        return m.group(0) if _norm_url(url) in verified else text

    scrubbed = _MD_LINK_RE.sub(_md, answer)

    def _bare(m: re.Match) -> str:
        url = m.group(0)
        return url if _norm_url(url) in verified else ""

    scrubbed = _URL_RE.sub(_bare, scrubbed)
    # tidy artifacts left by a removed URL: empty parens, "di .", double spaces.
    scrubbed = re.sub(r"\(\s*\)", "", scrubbed)
    scrubbed = re.sub(r"[ \t]{2,}", " ", scrubbed)
    scrubbed = re.sub(r"\s+([.,;:])", r"\1", scrubbed)
    return scrubbed.strip()


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

    # P1: strip any inline URL the model fabricated (not traceable to the KB).
    # ``peek`` reads the in-process cache only — no per-answer Supabase read (P5).
    try:
        from app.rag.canonical_urls import peek_canonical_url_set

        _canon = peek_canonical_url_set()
    except Exception:
        _canon = set()
    verified = verified_url_set(retrieved_contexts, extra=set(_canon))
    for source in deduped:
        if source.get("url"):
            verified.add(_norm_url(source["url"]))
    answer = scrub_unverified_urls(answer, verified)

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
