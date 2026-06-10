"""Fact-volatility model for VA-JIT (§4.2).

``query_volatility`` predicts how time-sensitive a query's answer is (fees,
deadlines, schedules, contacts = high; vision/mission, history, accreditation =
low). It sets the freshness half-life and is the first term of the VA-JIT
trigger. A keyword taxonomy (ID+EN) is the cold-start seed; feedback signals can
refine it later. Token-set matching avoids substring false positives
(e.g. "jaminan" must not match "jam").
"""

from __future__ import annotations

import re

HIGH_VOLATILITY_TERMS = {
    "biaya", "ukt", "spp", "tuition", "fee", "fees", "bayar", "pembayaran", "payment",
    "deadline", "batas", "tenggat", "jadwal", "schedule", "tanggal", "date", "dates",
    "kuota", "quota", "gelombang", "periode", "period", "pendaftaran", "registration",
    "kontak", "contact", "telepon", "phone", "libur",
}

LOW_VOLATILITY_TERMS = {
    "visi", "misi", "vision", "mission", "sejarah", "history", "akreditasi",
    "accreditation", "profil", "profile", "tentang", "about", "statuta", "filosofi", "lambang",
}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", (text or "").lower()))


def query_volatility(query: str) -> float:
    tokens = _tokens(query)
    high = bool(tokens & HIGH_VOLATILITY_TERMS)
    low = bool(tokens & LOW_VOLATILITY_TERMS)
    if high and not low:
        return 0.9
    if low and not high:
        return 0.1
    if high and low:
        return 0.6
    return 0.5


def half_life_for_volatility(volatility: float, *, min_days: float = 1.0, max_days: float = 180.0) -> float:
    """Map volatility in [0, 1] to a freshness half-life (seconds): volatile facts
    decay fast (short half-life), stable facts slowly."""
    volatility = max(0.0, min(1.0, volatility))
    days = min_days + (max_days - min_days) * (1.0 - volatility)
    return days * 86400.0
