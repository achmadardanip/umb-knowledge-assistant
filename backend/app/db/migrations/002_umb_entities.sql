-- Phase 2: Structured Entity Knowledge Layer
-- Run once against Supabase / any PostgreSQL instance.
-- Safe to re-run (IF NOT EXISTS / ON CONFLICT DO NOTHING).

CREATE TABLE IF NOT EXISTS umb_faculties (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT UNIQUE NOT NULL,
  name_short TEXT,
  dean TEXT,
  website_url TEXT,
  contact_email TEXT,
  contact_phone TEXT,
  whatsapp TEXT,
  accreditation_grade TEXT,
  accreditation_body TEXT DEFAULT 'BAN-PT',
  campus TEXT,
  description TEXT,
  source_urls JSONB DEFAULT '[]'::jsonb,
  confidence FLOAT DEFAULT 0.5,
  extracted_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS umb_study_programs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  upsert_key TEXT UNIQUE NOT NULL,
  program_name TEXT NOT NULL,
  degree_level TEXT DEFAULT 'S1',
  faculty_id UUID REFERENCES umb_faculties(id) ON DELETE SET NULL,
  faculty_name TEXT,
  head_of_program TEXT,
  accreditation_grade TEXT,
  accreditation_body TEXT DEFAULT 'BAN-PT',
  website_url TEXT,
  description TEXT,
  campus TEXT,
  source_urls JSONB DEFAULT '[]'::jsonb,
  confidence FLOAT DEFAULT 0.5,
  extracted_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS umb_campuses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  campus_name TEXT UNIQUE NOT NULL,
  address TEXT,
  city TEXT,
  postal_code TEXT,
  phone TEXT,
  fax TEXT,
  website_url TEXT,
  latitude FLOAT,
  longitude FLOAT,
  facilities JSONB DEFAULT '[]'::jsonb,
  source_urls JSONB DEFAULT '[]'::jsonb,
  confidence FLOAT DEFAULT 0.5,
  extracted_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS umb_scholarships (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scholarship_name TEXT UNIQUE NOT NULL,
  provider TEXT,
  description TEXT,
  requirements TEXT,
  eligibility TEXT,
  amount TEXT,
  deadline TEXT,
  programs_eligible JSONB DEFAULT '[]'::jsonb,
  contact TEXT,
  source_urls JSONB DEFAULT '[]'::jsonb,
  confidence FLOAT DEFAULT 0.5,
  extracted_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS umb_contacts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  upsert_key TEXT UNIQUE NOT NULL,
  office_name TEXT NOT NULL,
  unit TEXT,
  email TEXT,
  phone TEXT,
  whatsapp TEXT,
  location TEXT,
  campus TEXT,
  service_hours TEXT,
  service_type TEXT,
  url TEXT,
  source_urls JSONB DEFAULT '[]'::jsonb,
  confidence FLOAT DEFAULT 0.5,
  extracted_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS umb_services (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  service_name TEXT UNIQUE NOT NULL,
  description TEXT,
  unit TEXT,
  contact_id UUID REFERENCES umb_contacts(id) ON DELETE SET NULL,
  url TEXT,
  category TEXT,
  source_urls JSONB DEFAULT '[]'::jsonb,
  confidence FLOAT DEFAULT 0.5,
  extracted_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS ix_umb_faculties_name_short ON umb_faculties(name_short);
CREATE INDEX IF NOT EXISTS ix_umb_study_programs_name ON umb_study_programs(program_name);
CREATE INDEX IF NOT EXISTS ix_umb_study_programs_faculty_name ON umb_study_programs(faculty_name);
CREATE INDEX IF NOT EXISTS ix_umb_contacts_office_name ON umb_contacts(office_name);
CREATE INDEX IF NOT EXISTS ix_umb_contacts_service_type ON umb_contacts(service_type);
CREATE INDEX IF NOT EXISTS ix_umb_services_category ON umb_services(category);

-- Trigger: auto-update updated_at on row change
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END; $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_umb_faculties_updated_at') THEN
    CREATE TRIGGER trg_umb_faculties_updated_at
      BEFORE UPDATE ON umb_faculties FOR EACH ROW EXECUTE FUNCTION set_updated_at();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_umb_study_programs_updated_at') THEN
    CREATE TRIGGER trg_umb_study_programs_updated_at
      BEFORE UPDATE ON umb_study_programs FOR EACH ROW EXECUTE FUNCTION set_updated_at();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_umb_campuses_updated_at') THEN
    CREATE TRIGGER trg_umb_campuses_updated_at
      BEFORE UPDATE ON umb_campuses FOR EACH ROW EXECUTE FUNCTION set_updated_at();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_umb_scholarships_updated_at') THEN
    CREATE TRIGGER trg_umb_scholarships_updated_at
      BEFORE UPDATE ON umb_scholarships FOR EACH ROW EXECUTE FUNCTION set_updated_at();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_umb_contacts_updated_at') THEN
    CREATE TRIGGER trg_umb_contacts_updated_at
      BEFORE UPDATE ON umb_contacts FOR EACH ROW EXECUTE FUNCTION set_updated_at();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_umb_services_updated_at') THEN
    CREATE TRIGGER trg_umb_services_updated_at
      BEFORE UPDATE ON umb_services FOR EACH ROW EXECUTE FUNCTION set_updated_at();
  END IF;
END $$;
