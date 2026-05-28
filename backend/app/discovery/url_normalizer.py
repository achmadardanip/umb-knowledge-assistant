from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "gclid",
    "yclid",
    "mc_cid",
    "mc_eid",
}


def collapse_slashes(path: str) -> str:
    return re.sub(r"/{2,}", "/", path or "/")


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower() or "https"
    hostname = (parsed.hostname or "").lower().strip(".")
    netloc = hostname
    if parsed.port and not ((scheme == "http" and parsed.port == 80) or (scheme == "https" and parsed.port == 443)):
        netloc = f"{hostname}:{parsed.port}"
    path = collapse_slashes(parsed.path or "/")
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS
    ]
    query = urlencode(query_pairs, doseq=True)
    return urlunparse((scheme, netloc, path, "", query, ""))


def is_archive_url(url: str) -> bool:
    parsed = urlparse(url)
    return (parsed.hostname or "").lower() in {"web.archive.org", "archive.org"}


def archive_to_live_candidate(url: str) -> str:
    """Convert Wayback URLs into their current official URL candidate."""

    if not is_archive_url(url):
        return url
    match = re.search(r"/web/\d+[a-z_]*?/(https?://.+)$", url)
    if match:
        return normalize_url(match.group(1))
    return url
