-- Non-destructive local embedding sidecar.
-- Existing Gemini/OpenAI vectors in chunks.embedding are intentionally untouched.

CREATE EXTENSION IF NOT EXISTS vector;

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

CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_chunk_id
  ON chunk_embeddings(chunk_id);

CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_profile
  ON chunk_embeddings(profile);

CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_profile_chunk
  ON chunk_embeddings(profile, chunk_id);

CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_embedding_hnsw
  ON chunk_embeddings USING hnsw (embedding vector_cosine_ops);
