"""Phase 20 P20.1 — per-session entity memory.

Tracks the entities a conversation has established (faculty / program / dean /
kaprodi / accreditation subject / academic-system service / topic) so elliptical
follow-ups ("beliau menjabat sejak kapan?", "akreditasinya bagaimana?") can be
resolved against the remembered subject instead of being forgotten.

Properties: scoped per session, auto-expiring (TTL), lightweight (in-process
TTL+LRU store — no DB round-trip, no retrieval-path coupling, so the retrieval
benchmark is unaffected). For multi-worker production the same interface can be
backed by the chat_memories table; the in-process store is the default.
"""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, field

_TTL_SECONDS = 30 * 60          # a session context expires after 30 min idle
_MAX_SESSIONS = 2000            # LRU cap

# Canonical faculty phrases -> (short, full). Longest first so full names win.
_FACULTY = [
    ("fakultas ekonomi dan bisnis", ("FEB", "Fakultas Ekonomi dan Bisnis")),
    ("fakultas ilmu komputer", ("FASILKOM", "Fakultas Ilmu Komputer")),
    ("fakultas ilmu komunikasi", ("FIKOM", "Fakultas Ilmu Komunikasi")),
    ("fakultas desain dan seni kreatif", ("FDSK", "Fakultas Desain dan Seni Kreatif")),
    ("fakultas psikologi", ("FPSI", "Fakultas Psikologi")),
    ("fakultas teknik", ("FT", "Fakultas Teknik")),
    ("pascasarjana", ("PASCA", "Pascasarjana")),
    ("fasilkom", ("FASILKOM", "Fakultas Ilmu Komputer")),
    ("fikom", ("FIKOM", "Fakultas Ilmu Komunikasi")),
    ("fdsk", ("FDSK", "Fakultas Desain dan Seni Kreatif")),
    ("fpsi", ("FPSI", "Fakultas Psikologi")),
    ("feb", ("FEB", "Fakultas Ekonomi dan Bisnis")),
]
_PROGRAMS = [
    "sistem informasi", "teknik informatika", "teknik elektro", "teknik mesin",
    "teknik sipil", "teknik industri", "desain komunikasi visual", "hubungan masyarakat",
    "ilmu komunikasi", "manajemen", "akuntansi", "arsitektur", "penyiaran", "periklanan", "psikologi",
]
_SERVICES = ["sia", "sso", "elearning", "e-learning", "krs", "repository"]


@dataclass
class SessionContext:
    faculty: str | None = None
    faculty_short: str | None = None
    program: str | None = None
    dean: str | None = None
    kaprodi: str | None = None
    accreditation_subject: str | None = None
    service: str | None = None
    topic: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def age_seconds(self) -> int:
        return int(time.time() - self.created_at)

    def to_public(self) -> dict:
        d = asdict(self)
        d["session_age_seconds"] = self.age_seconds()
        return d


def _match_faculty(text: str) -> tuple[str, str] | None:
    low = text.lower()
    for needle, (short, full) in _FACULTY:
        if re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", low):
            return short, full
    return None


def _match_program(text: str) -> str | None:
    low = f" {text.lower()} "
    for p in _PROGRAMS:
        if re.search(rf"(?<!\w){re.escape(p)}(?!\w)", low):
            return p.title()
    return None


def _match_service(text: str) -> str | None:
    low = f" {text.lower()} "
    for s in _SERVICES:
        if re.search(rf"(?<!\w){re.escape(s)}(?!\w)", low):
            return s.upper()
    return None


class SessionMemory:
    def __init__(self, ttl: int = _TTL_SECONDS, max_sessions: int = _MAX_SESSIONS) -> None:
        self._ttl = ttl
        self._max = max_sessions
        self._store: "OrderedDict[str, SessionContext]" = OrderedDict()
        self._lock = threading.Lock()

    def _evict(self) -> None:
        now = time.time()
        for sid in [s for s, c in self._store.items() if now - c.updated_at > self._ttl]:
            self._store.pop(sid, None)
        while len(self._store) > self._max:
            self._store.popitem(last=False)

    def recall(self, session_id: str | None) -> SessionContext | None:
        if not session_id:
            return None
        with self._lock:
            self._evict()
            ctx = self._store.get(session_id)
            if ctx is None:
                return None
            if time.time() - ctx.updated_at > self._ttl:
                self._store.pop(session_id, None)
                return None
            self._store.move_to_end(session_id)
            return ctx

    def remember(self, session_id: str | None, *, query: str = "", contexts: list[dict] | None = None,
                 intent: str | None = None) -> SessionContext | None:
        """Update the session context from the user query + resolved entity contexts.
        Only OVERWRITES a slot when the new turn provides that entity (so an
        elliptical follow-up keeps the established subject)."""
        if not session_id:
            return None
        with self._lock:
            self._evict()
            ctx = self._store.get(session_id) or SessionContext()

            # explicit mentions in the query
            fac = _match_faculty(query)
            prog = _match_program(query)
            svc = _match_service(query)
            # A turn that explicitly names a faculty but no program switches the
            # subject to faculty level -> drop the stale program from a prior thread.
            if fac and not prog:
                ctx.program = None
                ctx.accreditation_subject = None

            # entities from the resolved top contexts
            top = (contexts or [{}])[0] if contexts else {}
            ttl_title = str(top.get("title") or "")
            et = top.get("entity_type")
            if et == "faculty":
                fmatch = _match_faculty(ttl_title)
                if fmatch:
                    fac = fmatch
            elif et == "study_program":
                pmatch = _match_program(ttl_title)
                if pmatch:
                    prog = pmatch
                fmatch = _match_faculty(ttl_title)
                if fmatch:
                    fac = fac or fmatch
            chunk = str(top.get("chunk_text") or "")
            m = re.search(r"Dekan:\s*([^\.]+)", chunk)
            if m:
                ctx.dean = m.group(1).strip()
            m = re.search(r"Ketua Program Studi:\s*([^\.]+)", chunk)
            if m:
                ctx.kaprodi = m.group(1).strip()

            if fac:
                ctx.faculty_short, ctx.faculty = fac
            if prog:
                ctx.program = prog
                ctx.accreditation_subject = prog
            elif fac and "akreditasi" in query.lower():
                ctx.accreditation_subject = fac[1]
            if svc:
                ctx.service = svc
            if intent:
                ctx.topic = intent

            ctx.updated_at = time.time()
            self._store[session_id] = ctx
            self._store.move_to_end(session_id)
            return ctx

    def clear(self, session_id: str | None) -> None:
        if session_id:
            with self._lock:
                self._store.pop(session_id, None)


# process-wide singleton (per worker).
_MEMORY = SessionMemory()


def get_session_memory() -> SessionMemory:
    return _MEMORY
