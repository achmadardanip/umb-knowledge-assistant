from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import Chunk, Source
from app.discovery.scope_validator import is_allowed_host
from app.retrieval.reranker import rerank_contexts


KEYWORD_BOOST_TERMS = {
    "biaya",
    "daftar",
    "pendaftaran",
    "pmb",
    "admission",
    "sso",
    "sia",
    "kontak",
    "akademik",
    "beasiswa",
    "perpustakaan",
    "repository",
    "fakultas",
}

STOPWORDS = {
    "apa",
    "saja",
    "yang",
    "dan",
    "atau",
    "untuk",
    "dengan",
    "bagaimana",
    "cara",
    "jika",
    "tidak",
    "bisa",
    "dimana",
    "mana",
    "itu",
    "umb",
    "universitas",
    "mercu",
    "buana",
}

QUERY_EXPANSIONS = {
    "daftar": ["pendaftaran", "pmb", "registrasi"],
    "pendaftaran": ["daftar", "pmb", "registrasi"],
    "pmb": ["pendaftaran", "daftar", "penerimaan mahasiswa baru", "calon mahasiswa"],
    "baru": ["penerimaan", "calon mahasiswa"],
    "program": ["program studi", "prodi", "fakultas"],
    "akademik": ["perkuliahan", "program akademik"],
    "perpus": ["perpustakaan", "library", "lib", "digilib", "repository"],
    "perpustakaan": ["perpus", "library", "lib", "digilib", "repository"],
    "library": ["perpustakaan", "perpus", "lib", "digilib", "repository"],
    "lib": ["perpustakaan", "library", "digilib", "repository"],
    "repository": ["digilib", "perpustakaan", "library", "lib"],
    "digilib": ["repository", "perpustakaan", "library", "lib"],
    "login": ["sso", "sia", "sistem informasi akademik", "lupa password", "reset password"],
    "masuk": ["login", "sso", "sia", "sistem informasi akademik"],
    "sia": ["sso", "login", "sistem informasi akademik"],
    "sso": ["sia", "login", "single sign on"],
    "beasiswa": ["scholarship"],
}

LOGIN_RELATED_TERMS = {
    "login",
    "sso",
    "sia",
    "sistem informasi akademik",
    "single sign on",
    "lupa password",
    "reset password",
}

LOGIN_REQUIRED_ANCHORS = (
    "login",
    "sso",
    "sia",
    "sistem informasi akademik",
    "single sign on",
    "lupa password",
    "reset password",
)

SIA_REQUIRED_ANCHORS = (
    "sso",
    "sia",
    "sistem informasi akademik",
    "single sign on",
)


@dataclass
class RetrievedContext:
    chunk_id: str | None
    source_id: str | None
    asset_id: str | None
    segment_id: str | None
    chunk_text: str
    url: str
    title: str | None
    score: float
    hostname: str | None
    discovery_source: str | None
    source_type: str | None
    page_number: int | None = None
    slide_number: int | None = None
    sheet_name: str | None = None
    row_range: str | None = None
    timestamp_start: float | None = None
    timestamp_end: float | None = None
    extraction_method: str | None = None
    extraction_confidence: float | None = None

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _terms(query: str) -> list[str]:
    raw_terms = [term.lower() for term in re.findall(r"[\w\-]+", query or "") if len(term) > 2]
    meaningful_terms = [term for term in raw_terms if term not in STOPWORDS] or raw_terms
    expanded: list[str] = []
    seen = set()
    for term in meaningful_terms:
        for candidate in [term, *QUERY_EXPANSIONS.get(term, [])]:
            normalized = candidate.strip().lower()
            if normalized and normalized not in seen:
                seen.add(normalized)
                expanded.append(normalized)
    return expanded


def _score_text(text: str, terms: list[str]) -> float:
    lowered = text.lower()
    score = 0.0
    for term in terms:
        count = _term_count(lowered, term)
        if count:
            score += min(count, 5)
            if term in KEYWORD_BOOST_TERMS:
                score += min(count, 3) * 1.5
    return score


def _score_metadata(text: str, terms: list[str]) -> float:
    lowered = text.lower()
    score = 0.0
    for term in terms:
        if _term_count(lowered, term):
            score += 3.0
            if term in KEYWORD_BOOST_TERMS:
                score += 2.0
    return score


def _is_login_related_query(terms: list[str]) -> bool:
    return any(term in LOGIN_RELATED_TERMS for term in terms)


def _has_required_anchor(text: str, anchors: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(_term_count(lowered, anchor) > 0 for anchor in anchors)


def _required_anchors_for_query(terms: list[str]) -> tuple[str, ...]:
    if any(term in SIA_REQUIRED_ANCHORS for term in terms):
        return SIA_REQUIRED_ANCHORS
    if _is_login_related_query(terms):
        return LOGIN_REQUIRED_ANCHORS
    return ()


def _min_relevance_score(terms: list[str]) -> float:
    if _is_login_related_query(terms):
        return 3.0
    return 0.1


def _term_count(text: str, term: str) -> int:
    normalized = (term or "").strip().lower()
    if not normalized:
        return 0
    escaped = re.escape(normalized).replace(r"\ ", r"\s+")
    return len(re.findall(rf"(?<!\w){escaped}(?!\w)", text, flags=re.IGNORECASE))


class HybridRetriever:
    def __init__(self, db: Session, root_domain: str = "mercubuana.ac.id"):
        self.db = db
        self.root_domain = root_domain

    def search(self, query: str, top_k: int = 5, source_types: list[str] | None = None) -> list[dict]:
        terms = _terms(query)
        if not terms:
            return []

        filters = [Chunk.chunk_text.ilike(f"%{term}%") for term in terms[:8]]
        required_anchors = _required_anchors_for_query(terms)
        min_score = _min_relevance_score(terms)
        db_query = self.db.query(Chunk, Source).outerjoin(Source, Chunk.source_id == Source.id)
        if source_types:
            db_query = db_query.filter(Chunk.source_type.in_(source_types))
        rows = db_query.filter(or_(*filters)).limit(max(top_k * 20, 100)).all()

        contexts: list[dict] = []
        for chunk, source in rows:
            meta = chunk.meta or {}
            url = meta.get("url") or (source.url if source else None)
            hostname = meta.get("hostname") or (source.hostname if source else None)
            if not url or not is_allowed_host(hostname, self.root_domain):
                continue
            metadata_text = " ".join(
                str(value)
                for value in [
                    meta.get("title"),
                    source.title if source else None,
                    url,
                    hostname,
                    meta.get("path"),
                    meta.get("source_type"),
                ]
                if value
            )
            combined_text = f"{chunk.chunk_text}\n{metadata_text}"
            if required_anchors and not _has_required_anchor(combined_text, required_anchors):
                continue
            score = _score_text(chunk.chunk_text, terms) + _score_metadata(metadata_text, terms)
            if score < min_score:
                continue
            contexts.append(
                RetrievedContext(
                    chunk_id=chunk.id,
                    source_id=chunk.source_id,
                    asset_id=chunk.asset_id,
                    segment_id=chunk.segment_id,
                    chunk_text=chunk.chunk_text,
                    url=url,
                    title=meta.get("title") or (source.title if source else None),
                    score=score,
                    hostname=hostname,
                    discovery_source=meta.get("discovery_source") or (source.discovery_source if source else None),
                    source_type=chunk.source_type or meta.get("source_type"),
                    page_number=chunk.page_number or meta.get("page_number"),
                    slide_number=chunk.slide_number or meta.get("slide_number"),
                    sheet_name=chunk.sheet_name or meta.get("sheet_name"),
                    row_range=chunk.row_range or meta.get("row_range"),
                    timestamp_start=chunk.timestamp_start or meta.get("timestamp_start"),
                    timestamp_end=chunk.timestamp_end or meta.get("timestamp_end"),
                    extraction_method=chunk.extraction_method or meta.get("extraction_method"),
                    extraction_confidence=chunk.extraction_confidence if chunk.extraction_confidence is not None else meta.get("extraction_confidence"),
                ).as_dict()
            )
        return rerank_contexts(contexts)[:top_k]
