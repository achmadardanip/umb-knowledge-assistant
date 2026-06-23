"""
Phase 32 P32.5 — source trust scoring.

Assigns a trust score in [0,1] to an external result by domain class, and decides
whether an external answer may be shown. KB/official sources are always trusted;
anything below ``external_min_trust_score`` (default 0.7) is rejected so external
answers are never built on low-trust sources.

    Source class            score
    Official Mercu Buana     1.00   (*.mercubuana.ac.id)
    Government (.go.id)      0.95
    BAN-PT                   0.95   (banpt.or.id / *.ban-pt.*)
    Academic repository      0.90   (doi.org, *.ac.id, garuda, sinta, scholar)
    News                     0.70
    Blog / other             0.40
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

OFFICIAL = "mercubuana.ac.id"

_BAN_PT_HOSTS = ("banpt.or.id", "ban-pt.kemdikbud.go.id", "ban-pt.or.id")
_NEWS_HOSTS = (
    "kompas.com", "detik.com", "tribunnews.com", "antaranews.com", "republika.co.id",
    "tempo.co", "cnnindonesia.com", "liputan6.com", "kumparan.com", "okezone.com",
)
_REPO_HINTS = ("doi.org", "garuda.kemdikbud.go.id", "sinta.kemdikbud.go.id",
               "scholar.google", "researchgate.net", "neliti.com")
_BLOG_HINTS = ("blogspot.", "wordpress.", "medium.com", "blog.", ".my.id")


@dataclass(frozen=True)
class TrustVerdict:
    score: float
    source_class: str
    accept: bool


def _host(url: str) -> str:
    try:
        h = (urlparse(url).hostname or "").lower()
    except Exception:
        h = ""
    return h


def classify_source(url: str) -> tuple[float, str]:
    """Return (trust_score, source_class) for a URL."""
    h = _host(url)
    if not h:
        return 0.0, "unknown"
    if h == OFFICIAL or h.endswith("." + OFFICIAL):
        return 1.0, "official_mercubuana"
    if any(h == b or h.endswith("." + b) for b in _BAN_PT_HOSTS):
        return 0.95, "ban_pt"
    if h.endswith(".go.id") or h == "go.id":
        return 0.95, "government"
    if any(hint in h for hint in _REPO_HINTS) or h.endswith(".ac.id"):
        return 0.90, "academic_repository"
    if any(h == n or h.endswith("." + n) for n in _NEWS_HOSTS):
        return 0.70, "news"
    if any(hint in h for hint in _BLOG_HINTS):
        return 0.40, "blog"
    return 0.40, "other"


def trust_for(url: str, *, min_trust: float | None = None) -> TrustVerdict:
    if min_trust is None:
        try:
            from app.core.config import get_settings

            min_trust = get_settings().external_min_trust_score
        except Exception:
            min_trust = 0.7
    score, klass = classify_source(url)
    return TrustVerdict(score=score, source_class=klass, accept=score >= min_trust)


def filter_trusted(contexts: list[dict], *, min_trust: float | None = None) -> list[dict]:
    """Drop external contexts whose source trust is below the floor, annotating the
    survivors with ``trust_score`` / ``source_class``. Contexts already sourced from the
    KB (``source_type == 'entity'`` or no url) are passed through untouched."""
    out: list[dict] = []
    for c in contexts:
        url = c.get("url") or ""
        if not url or c.get("source_type") == "entity":
            out.append(c)
            continue
        v = trust_for(url, min_trust=min_trust)
        if not v.accept:
            continue
        c = dict(c)
        c["trust_score"] = v.score
        c["source_class"] = v.source_class
        out.append(c)
    return out
