from app.db.database import normalize_database_url


def test_postgresql_url_uses_psycopg_v3_driver():
    url = "postgresql://postgres:secret@db.example.supabase.co:5432/postgres"
    assert normalize_database_url(url).startswith("postgresql+psycopg://")


def test_postgresql_psycopg_url_is_left_unchanged():
    url = "postgresql+psycopg://postgres:secret@db.example.supabase.co:5432/postgres"
    assert normalize_database_url(url) == url

