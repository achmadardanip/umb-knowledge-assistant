"""
Phase 31 STEP 2 — fuzzy entity alias loader.

Loads ``entity_aliases.json`` and exposes flat token/phrase -> canonical maps that
``entity_retriever`` merges *additively* into its built-in lookups. Loading is
defensive: a missing/invalid file yields empty maps (the retriever then behaves
exactly as before). Multi-word aliases (e.g. "fak psikologi", "public relations")
are returned separately so the retriever can phrase-match them against the query.

The alias dictionary widens RECOGNITION only — it never changes the
Program > Faculty > Person > Service tie-break, which lives in entity_retriever.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_ALIASES_PATH = Path(__file__).with_name("entity_aliases.json")


def _flatten(section: dict[str, list[str]]) -> tuple[dict[str, str], dict[str, str]]:
    """Return (single_token_map, phrase_map) for one section.

    single_token_map: one-word alias -> canonical name
    phrase_map:       multi-word alias -> canonical name (matched as a substring)
    """
    singles: dict[str, str] = {}
    phrases: dict[str, str] = {}
    for canonical, aliases in (section or {}).items():
        for alias in aliases or []:
            key = " ".join(str(alias).lower().split())
            if not key:
                continue
            if " " in key:
                phrases[key] = canonical
            else:
                singles[key] = canonical
    return singles, phrases


@lru_cache(maxsize=1)
def _load() -> dict:
    try:
        raw = json.loads(_ALIASES_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.debug("entity_aliases.json not found at %s; alias expansion disabled.", _ALIASES_PATH)
        return {}
    except Exception as exc:  # malformed JSON must never break entity retrieval
        logger.warning("Failed to parse entity_aliases.json: %s", exc)
        return {}

    out: dict[str, dict] = {}
    for section in ("faculties", "programs", "services"):
        singles, phrases = _flatten(raw.get(section, {}))
        out[section] = {"singles": singles, "phrases": phrases}
    return out


def faculty_alias_map() -> dict[str, str]:
    """Single-token faculty aliases -> canonical faculty name."""
    return dict(_load().get("faculties", {}).get("singles", {}))


def faculty_alias_phrases() -> dict[str, str]:
    return dict(_load().get("faculties", {}).get("phrases", {}))


def program_alias_map() -> dict[str, str]:
    """Single-token program aliases -> canonical program name."""
    return dict(_load().get("programs", {}).get("singles", {}))


def program_alias_phrases() -> dict[str, str]:
    return dict(_load().get("programs", {}).get("phrases", {}))


def service_alias_map() -> dict[str, str]:
    return dict(_load().get("services", {}).get("singles", {}))


def resolve_phrases(query_lc: str, kind: str) -> set[str]:
    """Return canonical names whose multi-word alias appears in ``query_lc``."""
    section = _load().get(
        {"faculty": "faculties", "program": "programs", "service": "services"}.get(kind, ""), {}
    )
    hits: set[str] = set()
    for phrase, canonical in section.get("phrases", {}).items():
        if phrase in query_lc:
            hits.add(canonical)
    return hits
