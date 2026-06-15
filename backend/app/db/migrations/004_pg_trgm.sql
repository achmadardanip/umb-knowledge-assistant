-- v2 latency fix: trigram GIN index so the hybrid keyword path's
-- `ILIKE '%term%'` scans over chunks.chunk_text use an index instead of a
-- full sequential scan (~11s -> ~1s). Also index source title/url/path which
-- the keyword search probes. Safe to re-run.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS ix_chunks_chunk_text_trgm
  ON chunks USING gin (chunk_text gin_trgm_ops);

CREATE INDEX IF NOT EXISTS ix_sources_title_trgm
  ON sources USING gin (title gin_trgm_ops);

CREATE INDEX IF NOT EXISTS ix_sources_url_trgm
  ON sources USING gin (url gin_trgm_ops);

CREATE INDEX IF NOT EXISTS ix_sources_path_trgm
  ON sources USING gin (path gin_trgm_ops);
