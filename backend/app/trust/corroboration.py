"""Corroboration with near-duplicate collapse (LLM04/08/09).

Counts how many *distinct authoritative* hosts independently assert a fact.
Near-duplicate chunks are collapsed via SimHash first, so a page mirrored across
several hosts cannot fake agreement — a single defaced/mirrored source can never
out-vote genuine independent corroboration. Feeds the C²GV high-stakes gate and
VA-JIT's trigger.
"""

from __future__ import annotations

from app.trust.simhash import hamming_distance, simhash


def corroboration_count(contexts: list[dict], *, min_authority: float = 0.5, simhash_threshold: int = 14) -> int:
    distinct_hosts: set[str] = set()
    fingerprints: list[int] = []
    for context in contexts:
        if (context.get("authority") or 0.0) < min_authority:
            continue
        fingerprint = simhash(context.get("chunk_text") or "")
        if any(hamming_distance(fingerprint, seen) <= simhash_threshold for seen in fingerprints):
            continue  # near-duplicate of content already counted — not independent
        fingerprints.append(fingerprint)
        hostname = context.get("hostname")
        if hostname:
            distinct_hosts.add(hostname)
    return len(distinct_hosts)
