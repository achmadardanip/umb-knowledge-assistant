"""Host authority prior for the Trust substrate (§4.1).

A cold-start structural seed: the registrar root and known official functional
subdomains rank high, unknown in-scope subdomains medium, and out-of-scope or
lookalike hosts zero (the anti-poisoning / subdomain-takeover lever, LLM04/08).
Refined later by an in-scope link-graph TrustRank/PageRank [Gyöngyi 2004; Page 1999]
and topical match. Consumed by TAHF (ranking) and C²GV ``support_score``.
"""

from __future__ import annotations

from app.discovery.scope_validator import is_allowed_host

# Tier 1 — official, answer-bearing functional subdomains: admission, tuition,
# academic, student affairs/services, faculty & program portals, contacts, login
# systems. Highest structural prior so they dominate general university questions.
HIGH_AUTHORITY_SUBDOMAINS = {
    "www",
    "pmb",
    "pendaftaran",
    "penerimaan",
    "sso",
    "sia",
    "akademik",
    "baa",
    "bak",
    "kemahasiswaan",
    "ditmawa",
    "karir",
    "international",
    "elearning",
    "support",
    "bti",
    # faculty & graduate portals (Tier 1 "Faculty / Programs")
    "fakultas",
    "feb",
    "ft",
    "fasilkom",
    "fikom",
    "fdsk",
    "psikologi",
    "pascasarjana",
    "pasca",
    "alumni",
}
TIER1_AUTHORITY = 0.85

# Tier 3 — library catalog / metadata hosts. Useful for library questions but a
# notch below the Tier-1 official portals for general queries.
LIBRARY_SUBDOMAINS = {"lib", "library", "perpustakaan"}
LIBRARY_AUTHORITY = 0.45

# Tier 4 — archive / research-output hosts (repository, journals, proceedings,
# digital thesis library). Evidence only; they must NEVER outrank Tier 1 official
# pages for general university questions, so they get the lowest structural prior.
# Topical relevance can still surface them for repository/journal queries.
ARCHIVE_SUBDOMAINS = {
    "repository",
    "publikasi",
    "publication",
    "proceeding",
    "proceedings",
    "journal",
    "jurnal",
    "digilib",
    "ejournal",
    "e-journal",
}
ARCHIVE_AUTHORITY = 0.25

# Tier 2 default — any other in-scope subdomain (news/announcements/events live on
# official hosts as paths and are demoted by topical scoring, not host authority).
DEFAULT_AUTHORITY = 0.5


def host_authority(hostname: str, root_domain: str = "mercubuana.ac.id") -> float:
    host = (hostname or "").lower().strip()
    if not host or not is_allowed_host(host, root_domain):
        return 0.0
    if host == root_domain or host == f"www.{root_domain}":
        return 0.9
    subdomain = host[: -(len(root_domain) + 1)]
    immediate_label = subdomain.split(".")[-1] if subdomain else ""
    if immediate_label in ARCHIVE_SUBDOMAINS:
        return ARCHIVE_AUTHORITY
    if immediate_label in LIBRARY_SUBDOMAINS:
        return LIBRARY_AUTHORITY
    if immediate_label in HIGH_AUTHORITY_SUBDOMAINS:
        return TIER1_AUTHORITY
    return DEFAULT_AUTHORITY
