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

    documents = relationship("Document", back_populates="source", cascade="all, delete-orphan")
    chunks = relationship("Chunk", back_populates="source")


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
Index("ix_chat_messages_session_created", ChatMessage.session_id, ChatMessage.created_at)
Index("ix_chat_memories_scope", ChatMemory.session_id, ChatMemory.anonymous_session_id, ChatMemory.is_active)
Index("ix_rag_answer_cache_key_expires", RAGAnswerCache.cache_key, RAGAnswerCache.expires_at)
