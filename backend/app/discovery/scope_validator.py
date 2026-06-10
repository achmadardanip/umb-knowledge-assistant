from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, unquote, urlparse


SENSITIVE_PATH_KEYWORDS = (
    "login",
    "auth",
    "logout",
    "dashboard",
    "admin",
    "administrator",
    "wp-admin",
    "account",
    "token",
    "password",
    "private",
    "config",
    "backup",
    "database",
    ".env",
    ".git",
    "secret",
    "api/private",
    "reset-password",
    "change-password",
    "upload/private",
    "cpanel",
    "phpmyadmin",
    "webmail",
    "usagestats",
    "usage_events",
    "/rt/",
    "cdn-cgi",
    "challenge-platform",
    "/search",
    "/user/",
    "/user",
    "viewcaptcha",
    "setlocale",
    "subscribemaillist",
    "registeruser",
    "/cart",
    "/checkout",
    "/wp-login",
)

NON_KNOWLEDGE_EXTENSIONS = (
    ".css",
    ".js",
    ".mjs",
    ".map",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".otf",
    ".log",
)

SENSITIVE_QUERY_KEYS = {
    "_wpnonce",
    "add-to-cart",
    "remove_item",
    "wc-ajax",
    "yith-woocompare-add-product",
}
SENSITIVE_QUERY_VALUE_MARKERS = (
    "add-product",
    "add-to-cart",
    "checkout",
    "remove-item",
    "woocompare",
)


@dataclass(frozen=True)
class ScopeDecision:
    is_allowed: bool
    reason: str | None = None


def normalize_hostname(hostname: str | None) -> str:
    return (hostname or "").strip().lower().strip(".")


def is_allowed_host(hostname: str | None, root_domain: str = "mercubuana.ac.id") -> bool:
    host = normalize_hostname(hostname)
    root = normalize_hostname(root_domain)
    return host == root or host.endswith(f".{root}")


def is_sensitive_path(path: str | None) -> bool:
    decoded = unquote(path or "").lower()
    return any(keyword in decoded for keyword in SENSITIVE_PATH_KEYWORDS)


def is_non_knowledge_asset(path: str | None) -> bool:
    decoded_path = unquote((path or "").split("?", 1)[0]).lower()
    return any(decoded_path.endswith(extension) for extension in NON_KNOWLEDGE_EXTENSIONS)


def validate_url_scope(url: str, root_domain: str = "mercubuana.ac.id") -> ScopeDecision:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return ScopeDecision(False, "unsupported_scheme")
    if not parsed.hostname or not is_allowed_host(parsed.hostname, root_domain):
        return ScopeDecision(False, "outside_allowed_domain")
    candidate_path = parsed.path or "/"
    if parsed.query:
        candidate_path = f"{candidate_path}?{parsed.query}"
    if is_sensitive_path(candidate_path):
        return ScopeDecision(False, "sensitive_or_private_path")
    query_pairs = [(key.lower(), value.lower()) for key, value in parse_qsl(parsed.query, keep_blank_values=True)]
    if any(key in SENSITIVE_QUERY_KEYS for key, _ in query_pairs) or any(
        marker in value for _, value in query_pairs for marker in SENSITIVE_QUERY_VALUE_MARKERS
    ):
        return ScopeDecision(False, "stateful_or_transactional_url")
    if is_non_knowledge_asset(candidate_path):
        return ScopeDecision(False, "non_knowledge_asset")
    return ScopeDecision(True, None)
