CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS sources (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  url TEXT UNIQUE NOT NULL,
  title TEXT,
  hostname TEXT,
  path TEXT,
  content_hash TEXT,
  fetched_at TIMESTAMPTZ DEFAULT now(),
  status TEXT,
  discovery_source TEXT,
  http_status INTEGER
);

CREATE TABLE IF NOT EXISTS discovered_urls (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  url TEXT UNIQUE NOT NULL,
  normalized_url TEXT,
  hostname TEXT,
  path TEXT,
  discovery_source TEXT,
  discovered_at TIMESTAMPTZ DEFAULT now(),
  is_allowed BOOLEAN DEFAULT false,
  rejection_reason TEXT,
  http_status INTEGER,
  crawled_at TIMESTAMPTZ,
  indexed BOOLEAN DEFAULT false,
  metadata JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS discovered_hosts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  hostname TEXT UNIQUE NOT NULL,
  root_domain TEXT,
  discovery_source TEXT,
  discovered_at TIMESTAMPTZ DEFAULT now(),
  is_allowed BOOLEAN DEFAULT false,
  rejection_reason TEXT,
  metadata JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS source_assets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id UUID REFERENCES sources(id) ON DELETE CASCADE,
  discovered_url_id UUID REFERENCES discovered_urls(id) ON DELETE SET NULL,
  url TEXT UNIQUE NOT NULL,
  normalized_url TEXT,
  hostname TEXT,
  path TEXT,
  source_type TEXT,
  mime_type TEXT,
  file_extension TEXT,
  file_size_bytes BIGINT,
  sha256 TEXT,
  local_path TEXT,
  download_status TEXT,
  extraction_status TEXT,
  extraction_method TEXT,
  extraction_confidence FLOAT,
  created_at TIMESTAMPTZ DEFAULT now(),
  downloaded_at TIMESTAMPTZ,
  extracted_at TIMESTAMPTZ,
  metadata JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS extracted_segments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  asset_id UUID NOT NULL REFERENCES source_assets(id) ON DELETE CASCADE,
  source_id UUID REFERENCES sources(id) ON DELETE CASCADE,
  segment_type TEXT,
  content TEXT NOT NULL,
  page_number INTEGER,
  slide_number INTEGER,
  sheet_name TEXT,
  row_range TEXT,
  timestamp_start FLOAT,
  timestamp_end FLOAT,
  language TEXT,
  extraction_confidence FLOAT,
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  raw_text TEXT,
  cleaned_text TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
  source_id UUID REFERENCES sources(id) ON DELETE CASCADE,
  asset_id UUID REFERENCES source_assets(id) ON DELETE CASCADE,
  segment_id UUID REFERENCES extracted_segments(id) ON DELETE CASCADE,
  chunk_text TEXT NOT NULL,
  chunk_index INTEGER,
  token_count INTEGER,
  embedding vector,
  metadata JSONB DEFAULT '{}'::jsonb,
  source_type TEXT,
  page_number INTEGER,
  slide_number INTEGER,
  sheet_name TEXT,
  row_range TEXT,
  timestamp_start FLOAT,
  timestamp_end FLOAT,
  extraction_method TEXT,
  extraction_confidence FLOAT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunk_embeddings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  chunk_id UUID NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
  profile VARCHAR(100) NOT NULL,
  provider VARCHAR(50) NOT NULL,
  model VARCHAR(255) NOT NULL,
  dimension INTEGER NOT NULL CHECK (dimension = 384),
  version VARCHAR(50) NOT NULL DEFAULT '1',
  embedding vector(384) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_chunk_embeddings_chunk_profile UNIQUE (chunk_id, profile)
);

CREATE TABLE IF NOT EXISTS chat_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT,
  anonymous_session_id TEXT,
  title TEXT DEFAULT 'New Chat',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  last_message_at TIMESTAMPTZ DEFAULT now(),
  is_archived BOOLEAN DEFAULT false,
  memory_enabled BOOLEAN DEFAULT true,
  metadata JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS chat_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
  content TEXT NOT NULL,
  sources JSONB,
  confidence_score TEXT,
  provider_used TEXT,
  model_used TEXT,
  not_found BOOLEAN DEFAULT false,
  visible_steps JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  metadata JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS chat_memories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID REFERENCES chat_sessions(id) ON DELETE CASCADE,
  user_id TEXT,
  anonymous_session_id TEXT,
  memory_type TEXT NOT NULL CHECK (memory_type IN ('session_summary', 'user_preference', 'recurring_context', 'project_context')),
  content TEXT NOT NULL,
  importance_score FLOAT DEFAULT 0.5,
  source_message_id UUID REFERENCES chat_messages(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  expires_at TIMESTAMPTZ,
  is_active BOOLEAN DEFAULT true,
  metadata JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS feedback (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  message_id UUID NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
  rating TEXT NOT NULL CHECK (rating IN ('helpful', 'not_helpful')),
  comment TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID,
  message_id UUID,
  question TEXT,
  answer TEXT,
  cited_sources JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  confidence_score TEXT,
  provider_used TEXT,
  model_used TEXT
);

CREATE TABLE IF NOT EXISTS rag_answer_cache (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  cache_key TEXT UNIQUE NOT NULL,
  question_hash TEXT NOT NULL,
  intent TEXT,
  provider_used TEXT,
  model_used TEXT,
  answer_payload JSONB NOT NULL,
  source_urls JSONB DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ DEFAULT now(),
  expires_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_sources_url ON sources(url);
CREATE INDEX IF NOT EXISTS ix_sources_content_hash ON sources(content_hash);
CREATE INDEX IF NOT EXISTS ix_sources_hostname ON sources(hostname);
CREATE UNIQUE INDEX IF NOT EXISTS ix_discovered_hosts_hostname ON discovered_hosts(hostname);
CREATE INDEX IF NOT EXISTS ix_discovered_hosts_root_domain ON discovered_hosts(root_domain);
CREATE INDEX IF NOT EXISTS ix_discovered_hosts_discovery_source ON discovered_hosts(discovery_source);
CREATE INDEX IF NOT EXISTS ix_discovered_hosts_is_allowed ON discovered_hosts(is_allowed);
CREATE UNIQUE INDEX IF NOT EXISTS ix_discovered_urls_url ON discovered_urls(url);
CREATE INDEX IF NOT EXISTS ix_discovered_urls_normalized_url ON discovered_urls(normalized_url);
CREATE INDEX IF NOT EXISTS ix_discovered_urls_hostname ON discovered_urls(hostname);
CREATE INDEX IF NOT EXISTS ix_discovered_urls_discovery_source ON discovered_urls(discovery_source);
CREATE INDEX IF NOT EXISTS ix_discovered_urls_is_allowed ON discovered_urls(is_allowed);
CREATE INDEX IF NOT EXISTS ix_discovered_urls_indexed ON discovered_urls(indexed);
CREATE UNIQUE INDEX IF NOT EXISTS ix_source_assets_url ON source_assets(url);
CREATE INDEX IF NOT EXISTS ix_source_assets_source_type ON source_assets(source_type);
CREATE INDEX IF NOT EXISTS ix_source_assets_sha256 ON source_assets(sha256);
CREATE INDEX IF NOT EXISTS ix_source_assets_download_status ON source_assets(download_status);
CREATE INDEX IF NOT EXISTS ix_source_assets_extraction_status ON source_assets(extraction_status);
CREATE INDEX IF NOT EXISTS ix_extracted_segments_asset_id ON extracted_segments(asset_id);
CREATE INDEX IF NOT EXISTS ix_extracted_segments_segment_type ON extracted_segments(segment_type);
CREATE INDEX IF NOT EXISTS ix_chunks_fts ON chunks USING GIN (to_tsvector('simple', coalesce(chunk_text, '')));
CREATE INDEX IF NOT EXISTS ix_chunks_source_type ON chunks(source_type);
CREATE INDEX IF NOT EXISTS ix_chunks_asset_id ON chunks(asset_id);
CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_chunk_id ON chunk_embeddings(chunk_id);
CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_profile ON chunk_embeddings(profile);
CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_profile_chunk ON chunk_embeddings(profile, chunk_id);
CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_embedding_hnsw
  ON chunk_embeddings USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS ix_chat_sessions_anonymous_session_id ON chat_sessions(anonymous_session_id);
CREATE INDEX IF NOT EXISTS ix_chat_sessions_last_message_at ON chat_sessions(last_message_at);
CREATE INDEX IF NOT EXISTS ix_chat_messages_session_id ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS ix_chat_memories_session_id ON chat_memories(session_id);
CREATE INDEX IF NOT EXISTS ix_chat_memories_anonymous_session_id ON chat_memories(anonymous_session_id);
CREATE INDEX IF NOT EXISTS ix_chat_memories_is_active ON chat_memories(is_active);
CREATE UNIQUE INDEX IF NOT EXISTS ix_rag_answer_cache_cache_key ON rag_answer_cache(cache_key);
CREATE INDEX IF NOT EXISTS ix_rag_answer_cache_question_hash ON rag_answer_cache(question_hash);
CREATE INDEX IF NOT EXISTS ix_rag_answer_cache_intent ON rag_answer_cache(intent);
CREATE INDEX IF NOT EXISTS ix_rag_answer_cache_expires_at ON rag_answer_cache(expires_at);

-- Legacy cloud vectors remain in chunks.embedding. New local E5 vectors use
-- chunk_embeddings.embedding vector(384), which has its own HNSW index above.
