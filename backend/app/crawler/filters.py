from __future__ import annotations

from app.discovery.scope_validator import validate_url_scope


def should_crawl_url(url: str, root_domain: str = "mercubuana.ac.id") -> tuple[bool, str | None]:
    decision = validate_url_scope(url, root_domain)
    return decision.is_allowed, decision.reason

