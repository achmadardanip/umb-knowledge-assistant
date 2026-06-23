from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    cast,
)
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.types import TypeDecorator


Base = declarative_base()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def uuid_str() -> str:
    return str(uuid.uuid4())


class VectorType(TypeDecorator):
    """Portable pgvector-ish type.

    PostgreSQL migrations create a real vector column. SQLite tests store the
    embedding as JSON text so service logic can run without a local pgvector DB.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, list):
            return value
        try:
            return json.loads(value)
        except Exception:
            return value

    def bind_expression(self, bindvalue):
        return cast(bindvalue, self)


@compiles(VectorType, "postgresql")
def compile_vector_type(_type, compiler, **kw):  # noqa: D401
    return "vector"


class Vector384Type(VectorType):
    """Portable vector type pinned to the local E5 embedding dimension."""


@compiles(Vector384Type, "postgresql")
def compile_vector_384_type(_type, compiler, **kw):  # noqa: D401
    return "vector(384)"


class GUID(TypeDecorator):
    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return uuid.UUID(str(value))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return str(value)


class Source(Base):
    __tablename__ = "sources"

    id = Column(GUID, primary_key=True, default=uuid_str)
    url = Column(Text, unique=True, nullable=False)
    title = Column(Text)
    hostname = Column(Text, index=True)
    path = Column(Text)
    content_hash = Column(Text, index=True)
    fetched_at = Column(DateTime(timezone=True), default=utcnow)
    status = Column(Text, default="pending")
    discovery_source = Column(Text)
    http_status = Column(Integer)
    # Phase 16 — content-freshness metadata (all nullable / backward compatible;
    # fetched_at remains the canonical crawl_date). Backfilled for the existing
    # 11k sources from fetched_at so no provenance is lost.
    extraction_date = Column(DateTime(timezone=True))
    source_last_modified = Column(DateTime(timezone=True))
    pdf_modified_date = Column(DateTime(timezone=True))
    first_seen_date = Column(DateTime(timezone=True))
    last_verified_date = Column(DateTime(timezone=True))

    documents = relationship("Document", back_populates="source", cascade="all, delete-orphan")
    chunks = relationship("Chunk", back_populates="source")


class CrawlRegistry(Base):
    """Phase 17 — incremental-crawl ledger. One row per crawlable URL tracking the
    last crawl, the last observed change, the content hash and the crawl status so
    ``detect_changed_content`` can skip unchanged pages (no full re-crawls)."""

    __tablename__ = "crawl_registry"

    id = Column(GUID, primary_key=True, default=uuid_str)
    url = Column(Text, unique=True, nullable=False)
    hostname = Column(Text, index=True)
    content_hash = Column(Text)
    content_type = Column(Text)           # html | pdf | …
    last_crawl = Column(DateTime(timezone=True))
    last_modified = Column(DateTime(timezone=True))   # server Last-Modified / pdf mtime
    last_changed = Column(DateTime(timezone=True))     # when our hash last changed
    crawl_status = Column(Text, default="pending", index=True)  # crawled|skipped|failed|pending
    http_status = Column(Integer)
    crawl_frequency = Column(Text, default="weekly")   # daily|weekly|manual
    failure_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class KnowledgeCandidate(Base):
    """Phase 33 P33.1 — self-expanding KB. A Tavily-discovered answer to a KB miss,
    held for auto-ingestion (trust ≥ threshold, official domain, low duplicate, high
    relevance) or human review. Additive; never replaces KB provenance."""

    __tablename__ = "knowledge_candidates"

    id = Column(GUID, primary_key=True, default=uuid_str)
    query = Column(Text, nullable=False)
    query_hash = Column(Text, index=True)
    answer = Column(Text)
    source_url = Column(Text)
    source_domain = Column(Text, index=True)
    trust_score = Column(Float, default=0.0, index=True)
    source_class = Column(Text)
    relevance = Column(Float)
    duplicate_score = Column(Float)
    accepted = Column(Boolean, default=False, index=True)
    ingested = Column(Boolean, default=False, index=True)
    reason = Column(Text)
    retrieved_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    decided_at = Column(DateTime(timezone=True))


class DiscoveredURL(Base):
    __tablename__ = "discovered_urls"

    id = Column(GUID, primary_key=True, default=uuid_str)
    url = Column(Text, unique=True, nullable=False)
    normalized_url = Column(Text, index=True)
    hostname = Column(Text, index=True)
    path = Column(Text)
    discovery_source = Column(Text, index=True)
    discovered_at = Column(DateTime(timezone=True), default=utcnow)
    is_allowed = Column(Boolean, default=False, index=True)
    rejection_reason = Column(Text)
    http_status = Column(Integer)
    crawled_at = Column(DateTime(timezone=True))
    indexed = Column(Boolean, default=False, index=True)
    meta = Column("metadata", JSON, default=dict)


class DiscoveredHost(Base):
    __tablename__ = "discovered_hosts"

    id = Column(GUID, primary_key=True, default=uuid_str)
    hostname = Column(Text, unique=True, nullable=False)
    root_domain = Column(Text, index=True)
    discovery_source = Column(Text, index=True)
    discovered_at = Column(DateTime(timezone=True), default=utcnow)
    is_allowed = Column(Boolean, default=False, index=True)
    rejection_reason = Column(Text)
    meta = Column("metadata", JSON, default=dict)


class SourceAsset(Base):
    __tablename__ = "source_assets"

    id = Column(GUID, primary_key=True, default=uuid_str)
    source_id = Column(GUID, ForeignKey("sources.id", ondelete="CASCADE"), nullable=True)
    discovered_url_id = Column(GUID, ForeignKey("discovered_urls.id", ondelete="SET NULL"), nullable=True)
    url = Column(Text, unique=True, nullable=False)
    normalized_url = Column(Text)
    hostname = Column(Text)
    path = Column(Text)
    source_type = Column(Text, index=True)
    mime_type = Column(Text)
    file_extension = Column(Text)
    file_size_bytes = Column(Integer)
    sha256 = Column(Text, index=True)
    local_path = Column(Text)
    download_status = Column(Text, index=True, default="pending")
    extraction_status = Column(Text, index=True, default="pending")
    extraction_method = Column(Text)
    extraction_confidence = Column(Float)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    downloaded_at = Column(DateTime(timezone=True))
    extracted_at = Column(DateTime(timezone=True))
    meta = Column("metadata", JSON, default=dict)

    segments = relationship("ExtractedSegment", back_populates="asset", cascade="all, delete-orphan")


class ExtractedSegment(Base):
    __tablename__ = "extracted_segments"

    id = Column(GUID, primary_key=True, default=uuid_str)
    asset_id = Column(GUID, ForeignKey("source_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id = Column(GUID, ForeignKey("sources.id", ondelete="CASCADE"), nullable=True)
    segment_type = Column(Text, index=True)
    content = Column(Text, nullable=False)
    page_number = Column(Integer)
    slide_number = Column(Integer)
    sheet_name = Column(Text)
    row_range = Column(Text)
    timestamp_start = Column(Float)
    timestamp_end = Column(Float)
    language = Column(Text)
    extraction_confidence = Column(Float)
    meta = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    asset = relationship("SourceAsset", back_populates="segments")


class Document(Base):
    __tablename__ = "documents"

    id = Column(GUID, primary_key=True, default=uuid_str)
    source_id = Column(GUID, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True)
    raw_text = Column(Text)
    cleaned_text = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    source = relationship("Source", back_populates="documents")
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(GUID, primary_key=True, default=uuid_str)
    document_id = Column(GUID, ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True)
    source_id = Column(GUID, ForeignKey("sources.id", ondelete="CASCADE"), nullable=True, index=True)
    asset_id = Column(GUID, ForeignKey("source_assets.id", ondelete="CASCADE"), nullable=True, index=True)
    segment_id = Column(GUID, ForeignKey("extracted_segments.id", ondelete="CASCADE"), nullable=True)
    chunk_text = Column(Text, nullable=False)
    chunk_index = Column(Integer, default=0)
    token_count = Column(Integer, default=0)
    embedding = Column(VectorType)
    meta = Column("metadata", JSON, default=dict)
    source_type = Column(Text, index=True)
    page_number = Column(Integer)
    slide_number = Column(Integer)
    sheet_name = Column(Text)
    row_range = Column(Text)
    timestamp_start = Column(Float)
    timestamp_end = Column(Float)
    extraction_method = Column(Text)
    extraction_confidence = Column(Float)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    document = relationship("Document", back_populates="chunks")
    source = relationship("Source", back_populates="chunks")
    embeddings = relationship("ChunkEmbedding", back_populates="chunk", cascade="all, delete-orphan")


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"

    id = Column(GUID, primary_key=True, default=uuid_str)
    chunk_id = Column(GUID, ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False, index=True)
    profile = Column(String(100), nullable=False, index=True)
    provider = Column(String(50), nullable=False)
    model = Column(String(255), nullable=False)
    dimension = Column(Integer, nullable=False)
    version = Column(String(50), nullable=False, default="1")
    embedding = Column(Vector384Type, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    chunk = relationship("Chunk", back_populates="embeddings")
    __table_args__ = (
        CheckConstraint("dimension = 384", name="ck_chunk_embedding_dimension_384"),
        UniqueConstraint("chunk_id", "profile", name="uq_chunk_embeddings_chunk_profile"),
    )


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(GUID, primary_key=True, default=uuid_str)
    user_id = Column(String(128))
    anonymous_session_id = Column(String(128), index=True)
    title = Column(String(200), default="New Chat")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    last_message_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    is_archived = Column(Boolean, default=False)
    memory_enabled = Column(Boolean, default=True)
    meta = Column("metadata", JSON, default=dict)

    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")
    memories = relationship("ChatMemory", back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(GUID, primary_key=True, default=uuid_str)
    session_id = Column(GUID, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    sources = Column(JSON)
    confidence_score = Column(String(20))
    provider_used = Column(String(50))
    model_used = Column(String(200))
    not_found = Column(Boolean, default=False)
    visible_steps = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    meta = Column("metadata", JSON, default=dict)

    session = relationship("ChatSession", back_populates="messages")
    __table_args__ = (CheckConstraint("role IN ('user', 'assistant', 'system')", name="ck_chat_message_role"),)


class ChatMemory(Base):
    __tablename__ = "chat_memories"

    id = Column(GUID, primary_key=True, default=uuid_str)
    session_id = Column(GUID, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(String(128))
    anonymous_session_id = Column(String(128), index=True)
    memory_type = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    importance_score = Column(Float, default=0.5)
    source_message_id = Column(GUID, ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    expires_at = Column(DateTime(timezone=True))
    is_active = Column(Boolean, default=True, index=True)
    meta = Column("metadata", JSON, default=dict)

    session = relationship("ChatSession", back_populates="memories")
    __table_args__ = (
        CheckConstraint(
            "memory_type IN ('session_summary', 'user_preference', 'recurring_context', 'project_context')",
            name="ck_chat_memory_type",
        ),
    )


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(GUID, primary_key=True, default=uuid_str)
    message_id = Column(GUID, ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False)
    rating = Column(String(20), nullable=False)
    comment = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (CheckConstraint("rating IN ('helpful', 'not_helpful')", name="ck_feedback_rating"),)


class RagEvalRun(Base):
    __tablename__ = "rag_eval_runs"

    id = Column(GUID, primary_key=True, default=uuid_str)
    status = Column(String(20), nullable=False, default="running")
    started_at = Column(DateTime(timezone=True), default=utcnow)
    finished_at = Column(DateTime(timezone=True))
    dataset_version = Column(String(50))
    grader_model = Column(String(200))
    n_total = Column(Integer, default=0)
    n_done = Column(Integer, default=0)
    agg_faithfulness = Column(Float)
    agg_relevance = Column(Float)
    n_not_found = Column(Integer, default=0)
    n_grader_error = Column(Integer, default=0)
    error = Column(Text)

    results = relationship("RagEvalResult", back_populates="run", cascade="all, delete-orphan")
    __table_args__ = (
        CheckConstraint("status IN ('running','completed','failed')", name="ck_rag_eval_run_status"),
    )


class RagEvalResult(Base):
    __tablename__ = "rag_eval_results"

    id = Column(GUID, primary_key=True, default=uuid_str)
    run_id = Column(GUID, ForeignKey("rag_eval_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = Column(String(128))
    question = Column(Text, nullable=False)
    intent = Column(String(64))
    answer = Column(Text)
    context = Column(Text)
    faithfulness_score = Column(Float)
    faithfulness_pass = Column(Boolean)
    faithfulness_reason = Column(Text)
    relevance_score = Column(Float)
    relevance_pass = Column(Boolean)
    relevance_reason = Column(Text)
    not_found = Column(Boolean, default=False)
    grader_error = Column(Boolean, default=False)
    latency_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    run = relationship("RagEvalRun", back_populates="results")


class ChatLog(Base):
    __tablename__ = "chat_logs"

    id = Column(GUID, primary_key=True, default=uuid_str)
    session_id = Column(GUID)
    message_id = Column(GUID)
    question = Column(Text)
    answer = Column(Text)
    cited_sources = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    confidence_score = Column(String(20))
    provider_used = Column(String(50))
    model_used = Column(String(200))


class RAGAnswerCache(Base):
    __tablename__ = "rag_answer_cache"

    id = Column(GUID, primary_key=True, default=uuid_str)
    cache_key = Column(Text, unique=True, nullable=False)
    question_hash = Column(Text, index=True, nullable=False)
    intent = Column(String(50), index=True)
    provider_used = Column(String(50))
    model_used = Column(String(200))
    answer_payload = Column(JSON, nullable=False)
    source_urls = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    expires_at = Column(DateTime(timezone=True), index=True)


Index("ix_discovered_urls_host_allowed", DiscoveredURL.hostname, DiscoveredURL.is_allowed)
Index("ix_chunks_source_type_confidence", Chunk.source_type, Chunk.extraction_confidence)
Index("ix_chunk_embeddings_profile_chunk", ChunkEmbedding.profile, ChunkEmbedding.chunk_id)
Index("ix_chat_messages_session_created", ChatMessage.session_id, ChatMessage.created_at)
Index("ix_chat_memories_scope", ChatMemory.session_id, ChatMemory.anonymous_session_id, ChatMemory.is_active)
Index("ix_rag_answer_cache_key_expires", RAGAnswerCache.cache_key, RAGAnswerCache.expires_at)


# ---------------------------------------------------------------------------
# Phase 2 — Structured Entity Knowledge Layer
# ---------------------------------------------------------------------------


class UMBFaculty(Base):
    """Deterministic lookup table for UMB faculties."""

    __tablename__ = "umb_faculties"

    id = Column(GUID, primary_key=True, default=uuid_str)
    name = Column(Text, unique=True, nullable=False)
    name_short = Column(Text, index=True)
    dean = Column(Text)
    website_url = Column(Text)
    contact_email = Column(Text)
    contact_phone = Column(Text)
    whatsapp = Column(Text)
    accreditation_grade = Column(Text)
    accreditation_body = Column(Text, default="BAN-PT")
    campus = Column(Text)
    description = Column(Text)
    source_urls = Column(JSON, default=list)
    confidence = Column(Float, default=0.5)
    extracted_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    programs = relationship("UMBStudyProgram", back_populates="faculty")


class UMBStudyProgram(Base):
    """Deterministic lookup table for UMB study programs."""

    __tablename__ = "umb_study_programs"

    id = Column(GUID, primary_key=True, default=uuid_str)
    upsert_key = Column(Text, unique=True, nullable=False, index=True)
    program_name = Column(Text, nullable=False, index=True)
    degree_level = Column(Text, default="S1")
    faculty_id = Column(GUID, ForeignKey("umb_faculties.id", ondelete="SET NULL"), nullable=True)
    faculty_name = Column(Text, index=True)
    head_of_program = Column(Text)
    accreditation_grade = Column(Text)
    accreditation_body = Column(Text, default="BAN-PT")
    website_url = Column(Text)
    description = Column(Text)
    campus = Column(Text)
    source_urls = Column(JSON, default=list)
    confidence = Column(Float, default=0.5)
    extracted_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    faculty = relationship("UMBFaculty", back_populates="programs")


class UMBCampus(Base):
    """Deterministic lookup table for UMB campuses."""

    __tablename__ = "umb_campuses"

    id = Column(GUID, primary_key=True, default=uuid_str)
    campus_name = Column(Text, unique=True, nullable=False)
    address = Column(Text)
    city = Column(Text)
    postal_code = Column(Text)
    phone = Column(Text)
    fax = Column(Text)
    website_url = Column(Text)
    latitude = Column(Float)
    longitude = Column(Float)
    facilities = Column(JSON, default=list)
    source_urls = Column(JSON, default=list)
    confidence = Column(Float, default=0.5)
    extracted_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class UMBScholarship(Base):
    """Deterministic lookup table for UMB scholarships."""

    __tablename__ = "umb_scholarships"

    id = Column(GUID, primary_key=True, default=uuid_str)
    scholarship_name = Column(Text, unique=True, nullable=False)
    provider = Column(Text)
    description = Column(Text)
    requirements = Column(Text)
    eligibility = Column(Text)
    amount = Column(Text)
    deadline = Column(Text)
    programs_eligible = Column(JSON, default=list)
    contact = Column(Text)
    source_urls = Column(JSON, default=list)
    confidence = Column(Float, default=0.5)
    extracted_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class UMBContact(Base):
    """Deterministic lookup table for UMB contact offices."""

    __tablename__ = "umb_contacts"

    id = Column(GUID, primary_key=True, default=uuid_str)
    upsert_key = Column(Text, unique=True, nullable=False, index=True)
    office_name = Column(Text, nullable=False, index=True)
    unit = Column(Text)
    email = Column(Text)
    phone = Column(Text)
    whatsapp = Column(Text)
    location = Column(Text)
    campus = Column(Text)
    service_hours = Column(Text)
    service_type = Column(Text, index=True)
    url = Column(Text)
    source_urls = Column(JSON, default=list)
    confidence = Column(Float, default=0.5)
    extracted_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    services = relationship("UMBService", back_populates="contact")


class UMBService(Base):
    """Deterministic lookup table for UMB student/academic services."""

    __tablename__ = "umb_services"

    id = Column(GUID, primary_key=True, default=uuid_str)
    service_name = Column(Text, unique=True, nullable=False)
    description = Column(Text)
    unit = Column(Text)
    contact_id = Column(GUID, ForeignKey("umb_contacts.id", ondelete="SET NULL"), nullable=True)
    url = Column(Text)
    category = Column(Text, index=True)
    source_urls = Column(JSON, default=list)
    confidence = Column(Float, default=0.5)
    extracted_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    contact = relationship("UMBContact", back_populates="services")


class CanonicalURL(Base):
    """Authoritative entity → verified KB URL map (v3 P1). Citations and entity/
    graph contexts use these URLs; URLs are NEVER reconstructed from names/slugs."""

    __tablename__ = "canonical_urls"

    id = Column(GUID, primary_key=True, default=uuid_str)
    entity_type = Column(Text, index=True)
    entity_name = Column(Text, index=True)
    canonical_url = Column(Text, nullable=False)
    source_id = Column(GUID, nullable=True)
    last_verified_at = Column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("entity_type", "entity_name", "canonical_url", name="uq_canonical_url"),)


class KnowledgeDiscoveryCache(Base):
    """Records questions resolved via the live Tavily fallback and the official UMB
    URLs that answered them (Batch 4). Lets a later similar question skip the billed
    Tavily round-trip once the content has been acquired into the KB."""

    __tablename__ = "knowledge_discovery_cache"

    id = Column(GUID, primary_key=True, default=uuid_str)
    question_hash = Column(Text, index=True, nullable=False)
    query = Column(Text)
    normalized_url = Column(Text, index=True)
    source_domain = Column(Text, index=True)
    indexed = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)


class UMBFAQ(Base):
    """Canonical FAQ store — Phase 3 answer-retrieval layer.

    Each row is a verified question/answer pair with paraphrase ``aliases`` for
    matching and ``source_urls`` for citation.  Distinct from
    ``chat.faq_service`` (a home-page popular-questions widget)."""

    __tablename__ = "umb_faqs"

    id = Column(GUID, primary_key=True, default=uuid_str)
    canonical_question = Column(Text, unique=True, nullable=False)
    normalized_question = Column(Text, index=True, nullable=False)
    answer = Column(Text, nullable=False)
    aliases = Column(JSON, default=list)
    category = Column(Text, index=True)
    intent = Column(Text, index=True)
    source_urls = Column(JSON, default=list)
    source_confidence = Column(Float, default=0.8)
    is_active = Column(Boolean, default=True, index=True)
    extracted_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
