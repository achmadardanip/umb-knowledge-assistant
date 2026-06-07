from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Chunk, Source
from app.discovery.scope_validator import is_allowed_host, validate_url_scope
from app.ingestion.embedder import get_embedder
from app.retrieval.dense import dense_search
from app.retrieval.fusion import reciprocal_rank_fusion, tahf_score
from app.retrieval.reranker import rerank_contexts
from app.trust.authority import host_authority
from app.trust.freshness import freshness_from_age
from app.trust.volatility import query_volatility


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
    fetched_at: datetime | None = None

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
    def __init__(self, db: Session, root_domain: str = "mercubuana.ac.id", embedder=None, dense_enabled: bool | None = None):
        self.db = db
        self.root_domain = root_domain
        self._embedder = embedder
        self._dense_enabled = get_settings().dense_retrieval_enabled if dense_enabled is None else dense_enabled

    def search(self, query: str, top_k: int = 5, source_types: list[str] | None = None) -> list[dict]:
        volatility = query_volatility(query)
        keyword_contexts = self._apply_freshness(
            self._keyword_search(query, top_k=top_k, source_types=source_types), volatility
        )
        if not self._dense_enabled:
            return rerank_contexts(keyword_contexts, root_domain=self.root_domain)[:top_k]
        dense_contexts = self._apply_freshness(
            self._dense_search(query, top_k=top_k, source_types=source_types), volatility
        )
        if not dense_contexts:
            return rerank_contexts(keyword_contexts, root_domain=self.root_domain)[:top_k]
        return self._fuse_and_rank(keyword_contexts, dense_contexts, top_k)

    def _apply_freshness(self, contexts: list[dict], volatility: float) -> list[dict]:
        now = datetime.now(timezone.utc)
        for context in contexts:
            fetched_at = context.get("fetched_at")
            context["freshness"] = freshness_from_age(fetched_at, volatility, now=now)
            if fetched_at is not None and hasattr(fetched_at, "date"):
                context["last_verified"] = fetched_at.date().isoformat()
        return contexts

    def _dense_search(self, query: str, *, top_k: int, source_types: list[str] | None) -> list[dict]:
        try:
            embedder = self._embedder or get_embedder()
            query_embedding = embedder.embed_query(query)
        except Exception:
            return []  # dense is best-effort; the keyword path still answers
        return dense_search(
            self.db,
            query_embedding,
            top_k=max(top_k * 4, 20),
            root_domain=self.root_domain,
            source_types=source_types,
        )

    def _fuse_and_rank(self, keyword_contexts: list[dict], dense_contexts: list[dict], top_k: int) -> list[dict]:
        by_id: dict[str, dict] = {}
        for context in keyword_contexts + dense_contexts:
            chunk_id = context.get("chunk_id")
            if chunk_id and chunk_id not in by_id:
                by_id[chunk_id] = context
        keyword_ranked = [context.get("chunk_id") for context in keyword_contexts if context.get("chunk_id")]
        dense_ranked = [context.get("chunk_id") for context in dense_contexts if context.get("chunk_id")]
        fused = reciprocal_rank_fusion([keyword_ranked, dense_ranked])
        if not fused:
            return []
        scores = [score for _, score in fused]
        low, high = min(scores), max(scores)
        spread = high - low
        settings = get_settings()
        alpha = settings.tahf_authority_weight
        beta = settings.tahf_freshness_weight
        ranked: list[dict] = []
        for chunk_id, rrf in fused:
            context = by_id.get(chunk_id)
            if not context:
                continue
            relevance = (rrf - low) / spread if spread > 0 else 1.0
            authority = host_authority(context.get("hostname"), self.root_domain)
            context_freshness = context.get("freshness")
            context_freshness = 1.0 if context_freshness is None else float(context_freshness)
            context["relevance"] = relevance
            context["authority"] = authority
            context["freshness"] = context_freshness
            context["score"] = tahf_score(relevance, authority, context_freshness, alpha=alpha, beta=beta)
            ranked.append(context)
        ranked.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        return ranked[:top_k]

    def _keyword_search(self, query: str, top_k: int = 5, source_types: list[str] | None = None) -> list[dict]:
        terms = _terms(query)
        if not terms:
            return []

        filters = [Chunk.chunk_text.ilike(f"%{term}%") for term in terms[:8]]
        required_anchors = _required_anchors_for_query(terms)
        min_score = _min_relevance_score(terms)
        db_query = self.db.query(Chunk, Source).join(Source, Chunk.source_id == Source.id).filter(Source.status == "indexed")
        if source_types:
            db_query = db_query.filter(Chunk.source_type.in_(source_types))
        rows = db_query.filter(or_(*filters)).limit(max(top_k * 20, 100)).all()

        contexts: list[dict] = []
        for chunk, source in rows:
            meta = chunk.meta or {}
            url = meta.get("url") or (source.url if source else None)
            hostname = meta.get("hostname") or (source.hostname if source else None)
            if not url or not is_allowed_host(hostname, self.root_domain) or not validate_url_scope(url, self.root_domain).is_allowed:
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
                    fetched_at=getattr(source, "fetched_at", None),
                ).as_dict()
            )
        return contexts
