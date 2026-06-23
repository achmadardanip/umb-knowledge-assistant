-- Phase 33 P33.1 — self-expanding KB. Stores Tavily-discovered answers to KB misses
-- as candidate documents for auto-ingestion / human review. Additive and idempotent
-- (CREATE ... IF NOT EXISTS); does not alter any existing table. Safe to re-run.

CREATE TABLE IF NOT EXISTS knowledge_candidates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  query TEXT NOT NULL,
  query_hash TEXT,
  answer TEXT,
  source_url TEXT,
  source_domain TEXT,
  trust_score REAL DEFAULT 0.0,
  source_class TEXT,
  relevance REAL,
  duplicate_score REAL,
  accepted BOOLEAN DEFAULT false,
  ingested BOOLEAN DEFAULT false,
  reason TEXT,                         -- why accepted/held (auto_ingest / review / rejected)
  retrieved_at TIMESTAMPTZ DEFAULT now(),
  decided_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_kc_query_hash ON knowledge_candidates(query_hash);
CREATE INDEX IF NOT EXISTS ix_kc_source_domain ON knowledge_candidates(source_domain);
CREATE INDEX IF NOT EXISTS ix_kc_accepted ON knowledge_candidates(accepted);
CREATE INDEX IF NOT EXISTS ix_kc_ingested ON knowledge_candidates(ingested);
CREATE INDEX IF NOT EXISTS ix_kc_trust_score ON knowledge_candidates(trust_score);
CREATE INDEX IF NOT EXISTS ix_kc_retrieved_at ON knowledge_candidates(retrieved_at);
