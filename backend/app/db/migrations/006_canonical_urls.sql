-- v3 P1: authoritative entity -> verified KB URL map. Citations and entity/graph
-- contexts use these URLs; URLs are NEVER reconstructed from names/slugs. Re-runnable.

CREATE TABLE IF NOT EXISTS canonical_urls (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_type TEXT,
  entity_name TEXT,
  canonical_url TEXT NOT NULL,
  source_id UUID,
  last_verified_at TIMESTAMPTZ DEFAULT now(),
  CONSTRAINT uq_canonical_url UNIQUE (entity_type, entity_name, canonical_url)
);

CREATE INDEX IF NOT EXISTS ix_canonical_urls_entity_type ON canonical_urls(entity_type);
CREATE INDEX IF NOT EXISTS ix_canonical_urls_entity_name ON canonical_urls(entity_name);

-- Populate from the entity tables + curated FAQ source URLs:
--   PYTHONPATH=. .venv/Scripts/python.exe -m app.rag.canonical_urls
