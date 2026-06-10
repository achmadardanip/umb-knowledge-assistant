"""SimHash near-duplicate detection for the corroboration gate (LLM04/08).

Charikar SimHash over word tokens, using a deterministic hash (blake2b) so
fingerprints are stable across processes. Two near-duplicate pages (a mirror, a
re-host, a lightly edited copy) collapse to within a small Hamming distance, so
one source cannot masquerade as independent corroboration.
"""

from __future__ import annotations

import hashlib
import re

_BITS = 64


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", (text or "").lower())


def _hash_token(token: str) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=_BITS // 8).digest()
    return int.from_bytes(digest, "big")


def simhash(text: str) -> int:
    tokens = _tokens(text)
    if not tokens:
        return 0
    sums = [0] * _BITS
    for token in tokens:
        token_hash = _hash_token(token)
        for bit in range(_BITS):
            sums[bit] += 1 if (token_hash >> bit) & 1 else -1
    fingerprint = 0
    for bit in range(_BITS):
        if sums[bit] > 0:
            fingerprint |= 1 << bit
    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def is_near_duplicate(a: str, b: str, *, threshold: int = 14) -> bool:
    # Erring toward merging is the safe direction here: a missed near-duplicate
    # would let mirrored content inflate corroboration. Tunable on real chunks.
    return hamming_distance(simhash(a), simhash(b)) <= threshold
