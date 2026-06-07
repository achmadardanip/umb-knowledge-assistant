"""Host authority prior for the Trust substrate (§4.1).

A cold-start structural seed: the registrar root and known official functional
subdomains rank high, unknown in-scope subdomains medium, and out-of-scope or
lookalike hosts zero (the anti-poisoning / subdomain-takeover lever, LLM04/08).
Refined later by an in-scope link-graph TrustRank/PageRank [Gyöngyi 2004; Page 1999]
and topical match. Consumed by TAHF (ranking) and C²GV ``support_score``.
"""

from __future__ import annotations

from app.discovery.scope_validator import is_allowed_host

HIGH_AUTHORITY_SUBDOMAINS = {
    "www",
    "pmb",
    "pendaftaran",
    "penerimaan",
    "sso",
    "sia",
    "akademik",
    "baa",
    "lib",
    "digilib",
    "repository",
    "fakultas",
    "pascasarjana",
    "pasca",
    "kemahasiswaan",
    "karir",
    "international",
    "elearning",
}


def host_authority(hostname: str, root_domain: str = "mercubuana.ac.id") -> float:
    host = (hostname or "").lower().strip()
    if not host or not is_allowed_host(host, root_domain):
        return 0.0
    if host == root_domain or host == f"www.{root_domain}":
        return 0.9
    subdomain = host[: -(len(root_domain) + 1)]
    immediate_label = subdomain.split(".")[-1] if subdomain else ""
    if immediate_label in HIGH_AUTHORITY_SUBDOMAINS:
        return 0.8
    return 0.5
