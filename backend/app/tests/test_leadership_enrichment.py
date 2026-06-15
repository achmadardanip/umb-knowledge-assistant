"""Tests for Batch 5 — leadership (dean) enrichment extractor + update logic."""

from __future__ import annotations

from app.db.models import UMBFaculty
from app.ingestion.leadership_enrichment import enrich_faculty_deans, extract_dean


def test_extract_dean_with_degrees():
    text = "Struktur Organisasi. Dekan: Prof. Dr. Andi Wijaya, M.Kom. Wakil Dekan: ..."
    assert extract_dean(text) == "Prof. Dr. Andi Wijaya, M.Kom"


def test_extract_dean_plain():
    assert extract_dean("Dekan Fakultas Teknik adalah Budi Santoso yang memimpin") == "Budi Santoso"


def test_extract_dean_none_when_absent():
    assert extract_dean("Halaman ini berisi berita dan pengumuman fakultas.") is None
    assert extract_dean("") is None


def test_enrich_updates_faculty_dean(db):
    db.add(UMBFaculty(name="Fakultas Uji", website_url="https://uji.mercubuana.ac.id/"))
    db.commit()

    def fake_fetcher(url):
        if url.endswith("struktur-organisasi"):
            return "Dekan: Dr. Sri Lestari, M.T. Wakil Dekan I: ..."
        return ""

    report = enrich_faculty_deans(db, fetcher=fake_fetcher)
    updated = {(u["faculty"], u["dean"]) for u in report["updated"]}
    assert ("Fakultas Uji", "Dr. Sri Lestari, M.T.") in updated
    row = db.query(UMBFaculty).filter(UMBFaculty.name == "Fakultas Uji").first()
    assert row.dean == "Dr. Sri Lestari, M.T."


def test_enrich_dry_run_does_not_write(db):
    db.add(UMBFaculty(name="Fakultas Dry", website_url="https://dry.mercubuana.ac.id/"))
    db.commit()
    report = enrich_faculty_deans(db, fetcher=lambda url: "Dekan: Dr. Test Name, M.Sc.", dry_run=True)
    assert report["updated"]
    row = db.query(UMBFaculty).filter(UMBFaculty.name == "Fakultas Dry").first()
    assert row.dean is None  # dry-run did not persist


def test_enrich_skips_already_known_dean(db):
    db.add(UMBFaculty(name="Fakultas Known", website_url="https://k.mercubuana.ac.id/", dean="Existing Dean"))
    db.commit()
    calls = []
    enrich_faculty_deans(db, fetcher=lambda url: calls.append(url) or "")
    assert not any("k.mercubuana.ac.id" in u for u in calls)  # not re-fetched
