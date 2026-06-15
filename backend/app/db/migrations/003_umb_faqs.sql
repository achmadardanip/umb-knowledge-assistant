-- Phase 3: Canonical FAQ Layer
-- Run once against Supabase / any PostgreSQL instance. Safe to re-run.

CREATE TABLE IF NOT EXISTS umb_faqs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  canonical_question TEXT UNIQUE NOT NULL,
  normalized_question TEXT NOT NULL,
  answer TEXT NOT NULL,
  aliases JSONB DEFAULT '[]'::jsonb,
  category TEXT,
  intent TEXT,
  source_urls JSONB DEFAULT '[]'::jsonb,
  source_confidence FLOAT DEFAULT 0.8,
  is_active BOOLEAN DEFAULT true,
  extracted_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_umb_faqs_normalized_question ON umb_faqs(normalized_question);
CREATE INDEX IF NOT EXISTS ix_umb_faqs_category ON umb_faqs(category);
CREATE INDEX IF NOT EXISTS ix_umb_faqs_intent ON umb_faqs(intent);
CREATE INDEX IF NOT EXISTS ix_umb_faqs_is_active ON umb_faqs(is_active);

-- Reuse the set_updated_at() trigger function from 002_umb_entities.sql.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'set_updated_at') THEN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_umb_faqs_updated_at') THEN
      CREATE TRIGGER trg_umb_faqs_updated_at
        BEFORE UPDATE ON umb_faqs FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
  END IF;
END $$;
