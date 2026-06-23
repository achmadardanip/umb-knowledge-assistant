"""Phase 27.3 — typo / slang / abbreviation normalization for informal Indonesian.

Real users type "dekan feb siapa ya", "brp biaya kuliah ti", "akreditsi sistem
informasi", "gmn cara login sia". This layer normalizes such queries BEFORE
retrieval:

  1. slang / abbreviation expansion   (gmn->bagaimana, brp->berapa, ti->teknik informatika)
  2. fuzzy spell-correction of campus vocabulary tokens (akreditsi->akreditasi)
  3. light cleanup (punctuation, filler particles: ya/dong/sih/nih)

Dependency-light: uses stdlib ``difflib`` for fuzzy matching, with an optional
``rapidfuzz`` fast-path if installed. Applied only to the live chat query — the
retrieval/entity benchmarks call the retriever directly with clean queries, so
they are unaffected (no regression).
"""

from __future__ import annotations

import difflib
import re

try:  # optional fast path
    from rapidfuzz import fuzz as _rf_fuzz  # type: ignore
    _HAS_RAPIDFUZZ = True
except Exception:  # pragma: no cover
    _HAS_RAPIDFUZZ = False

# --- slang / abbreviation expansion (whole-token) ---------------------------
_SLANG = {
    # question words / fillers
    "gmn": "bagaimana", "gimana": "bagaimana", "brp": "berapa", "brapa": "berapa",
    "kpn": "kapan", "dmn": "dimana", "knp": "kenapa", "sapa": "siapa", "spa": "siapa",
    "yg": "yang", "dgn": "dengan", "utk": "untuk", "tdk": "tidak", "ga": "tidak",
    "gak": "tidak", "ngga": "tidak", "nggak": "tidak", "gk": "tidak", "ada": "ada",
    "skrg": "sekarang", "skg": "sekarang", "sekrang": "sekarang", "dibka": "dibuka",
    "dibuk": "dibuka", "gw": "saya", "gue": "saya", "aku": "saya", "lupa": "lupa",
    "info": "informasi", "infonya": "informasi", "thn": "tahun", "smt": "semester",
    "jdwl": "jadwal", "jdl": "jadwal", "bs": "bisa", "klo": "kalau", "kl": "kalau",
    "dkn": "dekan", "kaprodi": "kaprodi", "akreditas": "akreditasi",
    "akre": "akreditasi", "akred": "akreditasi", "aja": "saja", "apaaja": "apa saja",
    "kuliahnya": "kuliah", "biayanya": "biaya", "daftarnya": "pendaftaran",
    # campus abbreviations -> canonical entity terms
    "ti": "teknik informatika", "si": "sistem informasi", "tk": "teknik",
    "mnj": "manajemen", "akun": "akuntansi", "dkv": "desain komunikasi visual",
    "humas": "hubungan masyarakat", "psiko": "psikologi", "kom": "komunikasi",
    "maba": "mahasiswa baru", "kating": "kakak tingkat",
    "sisfo": "sistem informasi", "deskomvis": "desain komunikasi visual",
    "hubmas": "hubungan masyarakat",
    # Phase 31 STEP 5 — mixed-language (English -> Indonesian KB vocabulary). Clean
    # Indonesian queries never contain these tokens, so expansion is regression-free.
    "dean": "dekan", "tuition": "biaya kuliah", "fee": "biaya", "fees": "biaya",
    "cost": "biaya", "scholarship": "beasiswa", "scholarships": "beasiswa",
    "schedule": "jadwal", "calendar": "kalender", "requirements": "persyaratan",
    "requirement": "persyaratan", "campus": "kampus", "library": "perpustakaan",
    "faculty": "fakultas", "lecturer": "dosen", "lecturers": "dosen",
    "accreditation": "akreditasi", "registration": "pendaftaran", "broadcasting": "penyiaran",
    "graduation": "wisuda", "counseling": "konseling", "services": "layanan",
    "service": "layanan", "address": "alamat", "location": "lokasi",
}
# These campus acronyms are already understood downstream; keep them as-is.
_KEEP = {"feb", "ft", "fasilkom", "fikom", "fdsk", "fpsi", "pmb", "sia", "sso",
         "krs", "khs", "ukm", "umb", "lms", "s1", "s2", "ipk"}
# Campus acronyms used as the fuzzy-correction targets for typo'd acronyms
# ("ftt"->ft, "fikoom"->fikom, "ffpi"->fpsi). Distinct pass because these are
# short and would otherwise be skipped by the min-length gate.
_ACRONYMS = ["feb", "ft", "fasilkom", "fikom", "fdsk", "fpsi", "pmb", "sia", "sso", "krs", "khs", "umb"]
# Filler particles to drop.
_FILLERS = {"ya", "dong", "sih", "nih", "deh", "kok", "yaa", "ya?", "tuh"}

# --- campus vocabulary for fuzzy correction ---------------------------------
_VOCAB = sorted({
    "dekan", "wakil", "kaprodi", "ketua", "program", "studi", "prodi", "jurusan",
    "akreditasi", "fakultas", "biaya", "kuliah", "uang", "kelas", "karyawan",
    "beasiswa", "pendaftaran", "mahasiswa", "baru", "jadwal", "kalender", "akademik",
    "login", "password", "kampus", "lokasi", "alamat", "perpustakaan", "laboratorium",
    "wisuda", "transkrip", "nilai", "cuti", "registrasi", "kurikulum", "dosen",
    "ekonomi", "bisnis", "teknik", "informatika", "informasi", "sistem", "komputer",
    "komunikasi", "desain", "psikologi", "manajemen", "akuntansi", "elektro", "mesin",
    "sipil", "industri", "arsitektur", "penyiaran", "periklanan", "hubungan",
    "masyarakat", "visual", "pascasarjana", "meruya", "menteng", "bekasi",
    "siapa", "berapa", "kapan", "dimana", "bagaimana", "apa", "saja", "sekarang",
})
_VOCAB_SET = set(_VOCAB)
_FUZZY_THRESHOLD = 0.72
_MIN_FUZZY_LEN = 4


def _close(token: str) -> str | None:
    """Nearest campus-vocabulary term for a likely-misspelled token, or None.
    Length-gated: only accept a correction whose length is within 40% of the token
    so short noise doesn't snap onto an unrelated long word."""
    best, score = None, 0.0
    if _HAS_RAPIDFUZZ:
        for w in _VOCAB:
            s = _rf_fuzz.ratio(token, w) / 100.0
            if s > score:
                best, score = w, s
    else:
        m = difflib.get_close_matches(token, _VOCAB, n=1, cutoff=_FUZZY_THRESHOLD)
        if m:
            best = m[0]
            score = difflib.SequenceMatcher(None, token, best).ratio()
    if best and score >= _FUZZY_THRESHOLD and abs(len(best) - len(token)) <= max(2, int(0.4 * len(best))):
        return best
    return None


def _close_acronym(token: str) -> str | None:
    """Correct a typo'd campus acronym ("ftt"->ft, "fikoom"->fikom). Length-gated so
    only similarly-short tokens map onto an acronym."""
    if len(token) < 2 or len(token) > 10:
        return None
    cands = [a for a in _ACRONYMS if abs(len(a) - len(token)) <= 2]
    m = difflib.get_close_matches(token, cands, n=1, cutoff=0.74)
    return m[0] if m else None


# Canonical entity phrases for phrase-level recovery under heavy noise.
_ENTITY_PHRASES = sorted({
    "fakultas ekonomi dan bisnis", "fakultas teknik", "fakultas ilmu komputer",
    "fakultas ilmu komunikasi", "fakultas desain dan seni kreatif", "fakultas psikologi",
    "teknik informatika", "sistem informasi", "teknik elektro", "teknik mesin",
    "teknik sipil", "teknik industri", "desain komunikasi visual", "hubungan masyarakat",
    "ilmu komunikasi", "manajemen", "akuntansi", "arsitektur", "penyiaran", "periklanan", "psikologi",
}, key=lambda p: -len(p))
_PHRASE_THRESHOLD = 0.74


def _recover_phrase(tokens: list[str]) -> str | None:
    """Return the SINGLE best-matching canonical entity phrase for the query (or
    None). Conservative: only fires when no entity phrase is already present and
    the best fuzzy window is strong, so clean queries are never altered and only
    one (best) phrase is recovered under heavy noise."""
    joined = " ".join(tokens)
    if any(p in joined for p in _ENTITY_PHRASES):
        return None  # an entity is already cleanly present — don't touch
    best, best_score = None, 0.0
    for phrase in _ENTITY_PHRASES:
        plen = len(phrase.split())
        for i in range(0, max(0, len(tokens) - plen + 1)):
            window = " ".join(tokens[i:i + plen])
            score = difflib.SequenceMatcher(None, phrase, window).ratio()
            if score > best_score:
                best, best_score = phrase, score
    return best if best_score >= _PHRASE_THRESHOLD else None


def normalize_query(query: str) -> str:
    """Return a normalized query (slang expanded, typos corrected). Idempotent on
    already-clean queries, so clean inputs pass through unchanged."""
    if not query or not query.strip():
        return query
    raw = query.strip()
    tokens = re.findall(r"[A-Za-z0-9]+|\S", raw.lower())
    out: list[str] = []
    for tok in tokens:
        if not tok.isalnum():
            continue  # drop stray punctuation
        if tok in _FILLERS:
            continue
        if tok in _SLANG:
            out.append(_SLANG[tok])
            continue
        if tok in _KEEP or tok in _VOCAB_SET or tok.isdigit():
            out.append(tok)
            continue
        # Real-word vocabulary correction FIRST (so "sipa"->"siapa", not the "sia"
        # acronym), then acronym correction for short tokens ("ftt"->"ft").
        corrected = _close(tok) if len(tok) >= _MIN_FUZZY_LEN else None
        if corrected:
            out.append(corrected)
            continue
        ac = _close_acronym(tok)
        out.append(ac if ac else tok)
    normalized = " ".join(out).strip()
    # heavy-noise safety net: recover the single best entity phrase when none is
    # cleanly present (never alters clean queries — they already contain the entity).
    phrase = _recover_phrase(normalized.split())
    if phrase:
        normalized = f"{normalized} {phrase}".strip()
    return normalized or raw


def explain(query: str) -> dict:
    """Diagnostic: original vs normalized (for the typo benchmark / debugging)."""
    norm = normalize_query(query)
    return {"original": query, "normalized": norm, "changed": norm.lower() != (query or "").strip().lower(),
            "rapidfuzz": _HAS_RAPIDFUZZ}
