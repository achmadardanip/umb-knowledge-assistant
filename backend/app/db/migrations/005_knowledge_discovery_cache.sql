-- Batch 4: discovery cache so similar questions skip repeated Tavily searches
-- once the official UMB content has been acquired into the KB. Safe to re-run.

CREATE TABLE IF NOT EXISTS knowledge_discovery_cache (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  question_hash TEXT NOT NULL,
  query TEXT,
  normalized_url TEXT,
  source_domain TEXT,
  indexed BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_kdc_question_hash ON knowledge_discovery_cache(question_hash);
CREATE INDEX IF NOT EXISTS ix_kdc_normalized_url ON knowledge_discovery_cache(normalized_url);
CREATE INDEX IF NOT EXISTS ix_kdc_source_domain ON knowledge_discovery_cache(source_domain);
CREATE INDEX IF NOT EXISTS ix_kdc_indexed ON knowledge_discovery_cache(indexed);
CREATE INDEX IF NOT EXISTS ix_kdc_created_at ON knowledge_discovery_cache(created_at);
