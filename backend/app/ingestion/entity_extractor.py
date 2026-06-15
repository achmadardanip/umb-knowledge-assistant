"""
UMB Structured Entity Extractor — Phase 2 knowledge layer.

Two passes:
  --seed   Insert curated seed entities (confidence=0.85), skipping if already present.
  --mine   Scan indexed chunks to enrich seeds with dean names, accreditation grades,
           phone numbers, emails, and campus addresses (confidence=0.65).

Usage (from backend/):
  PYTHONPATH=. .venv/Scripts/python.exe -m app.ingestion.entity_extractor \
      --seed --mine --out ../data/reports/entity_extract.json
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Seed data — curated known-correct UMB facts
# ---------------------------------------------------------------------------

FACULTY_SEEDS: list[dict] = [
    {
        "name": "Fakultas Ekonomi dan Bisnis",
        "name_short": "FEB",
        "campus": "Meruya",
        "website_url": "https://www.mercubuana.ac.id/fakultas-ekonomi-dan-bisnis/",
        "accreditation_grade": "A",
    },
    {
        "name": "Fakultas Teknik",
        "name_short": "FT",
        "campus": "Meruya",
        "website_url": "https://ft.mercubuana.ac.id/",
    },
    {
        "name": "Fakultas Ilmu Komputer",
        "name_short": "FASILKOM",
        "campus": "Meruya",
        "website_url": "https://fasilkom.mercubuana.ac.id/",
    },
    {
        "name": "Fakultas Ilmu Komunikasi",
        "name_short": "FIKOM",
        "campus": "Meruya",
        "website_url": "https://fikom.mercubuana.ac.id/",
    },
    {
        "name": "Fakultas Desain dan Seni Kreatif",
        "name_short": "FDSK",
        "campus": "Meruya",
        "website_url": "https://fdsk.mercubuana.ac.id/",
    },
    {
        "name": "Fakultas Psikologi",
        "name_short": "FPSI",
        "campus": "Meruya",
        "website_url": "https://www.mercubuana.ac.id/psikologi/",
    },
    {
        "name": "Pascasarjana",
        "name_short": "PASCA",
        "campus": "Meruya",
        "website_url": "https://pasca.mercubuana.ac.id/",
    },
]

PROGRAM_SEEDS: list[dict] = [
    # FEB
    {"program_name": "Manajemen", "degree_level": "S1", "faculty_name": "Fakultas Ekonomi dan Bisnis"},
    {"program_name": "Manajemen", "degree_level": "S2", "faculty_name": "Fakultas Ekonomi dan Bisnis"},
    {"program_name": "Akuntansi", "degree_level": "S1", "faculty_name": "Fakultas Ekonomi dan Bisnis"},
    {"program_name": "Akuntansi", "degree_level": "S2", "faculty_name": "Fakultas Ekonomi dan Bisnis"},
    # FT
    {"program_name": "Teknik Elektro", "degree_level": "S1", "faculty_name": "Fakultas Teknik"},
    {"program_name": "Teknik Mesin", "degree_level": "S1", "faculty_name": "Fakultas Teknik"},
    {"program_name": "Teknik Sipil", "degree_level": "S1", "faculty_name": "Fakultas Teknik"},
    {"program_name": "Teknik Industri", "degree_level": "S1", "faculty_name": "Fakultas Teknik"},
    {"program_name": "Arsitektur", "degree_level": "S1", "faculty_name": "Fakultas Teknik"},
    # FASILKOM
    {"program_name": "Teknik Informatika", "degree_level": "S1", "faculty_name": "Fakultas Ilmu Komputer"},
    {"program_name": "Teknik Informatika", "degree_level": "S2", "faculty_name": "Fakultas Ilmu Komputer"},
    {"program_name": "Sistem Informasi", "degree_level": "S1", "faculty_name": "Fakultas Ilmu Komputer"},
    # FIKOM
    {"program_name": "Ilmu Komunikasi", "degree_level": "S1", "faculty_name": "Fakultas Ilmu Komunikasi"},
    {"program_name": "Ilmu Komunikasi", "degree_level": "S2", "faculty_name": "Fakultas Ilmu Komunikasi"},
    {"program_name": "Penyiaran", "degree_level": "S1", "faculty_name": "Fakultas Ilmu Komunikasi"},
    {"program_name": "Periklanan", "degree_level": "S1", "faculty_name": "Fakultas Ilmu Komunikasi"},
    {"program_name": "Hubungan Masyarakat", "degree_level": "S1", "faculty_name": "Fakultas Ilmu Komunikasi"},
    # FDSK
    {"program_name": "Desain Komunikasi Visual", "degree_level": "S1", "faculty_name": "Fakultas Desain dan Seni Kreatif"},
    # FPSI
    {"program_name": "Psikologi", "degree_level": "S1", "faculty_name": "Fakultas Psikologi"},
    {"program_name": "Psikologi", "degree_level": "S2", "faculty_name": "Fakultas Psikologi"},
]

CAMPUS_SEEDS: list[dict] = [
    {
        "campus_name": "Meruya",
        "address": "Jl. Meruya Selatan No.1, RT.11/RW.4, Meruya Selatan, Kembangan, Jakarta Barat 11650",
        "city": "Jakarta Barat",
        "postal_code": "11650",
        "phone": "(021) 5840816",
        "website_url": "https://www.mercubuana.ac.id/",
        "latitude": -6.1940,
        "longitude": 106.7360,
    },
    {
        "campus_name": "Menteng",
        "address": "Jl. Menteng Raya No.29, Menteng, Jakarta Pusat 10340",
        "city": "Jakarta Pusat",
        "postal_code": "10340",
        "phone": "(021) 3190 2972",
        "website_url": "https://www.mercubuana.ac.id/",
        "latitude": -6.1960,
        "longitude": 106.8360,
    },
    {
        "campus_name": "Warung Buncit",
        "address": "Jl. Warung Buncit Raya No.17, Mampang Prapatan, Jakarta Selatan 12510",
        "city": "Jakarta Selatan",
        "postal_code": "12510",
        "website_url": "https://www.mercubuana.ac.id/",
        "latitude": -6.2570,
        "longitude": 106.8260,
    },
    {
        "campus_name": "Bekasi",
        "address": "Jl. Raya Kaliabang No.8, Perwira, Bekasi Utara, Kota Bekasi 17124",
        "city": "Bekasi",
        "postal_code": "17124",
        "website_url": "https://www.mercubuana.ac.id/",
        "latitude": -6.1960,
        "longitude": 106.9990,
    },
]

SCHOLARSHIP_SEEDS: list[dict] = [
    {
        "scholarship_name": "Beasiswa KIP Kuliah",
        "provider": "Kemdikbudristek",
        "description": "Beasiswa Kartu Indonesia Pintar Kuliah untuk mahasiswa tidak mampu berprestasi",
        "eligibility": "Lulusan SMA/SMK/sederajat, tidak mampu secara ekonomi, berprestasi",
        "contact": "PMB UMB / Kemendikbud",
        "source_urls": ["https://pendaftaran.mercubuana.ac.id/"],
    },
    {
        "scholarship_name": "Beasiswa UMB Prestasi",
        "provider": "Universitas Mercu Buana",
        "description": "Beasiswa prestasi akademik untuk mahasiswa berprestasi di UMB",
        "eligibility": "IPK minimal 3.5, aktif di organisasi kemahasiswaan",
        "source_urls": ["https://kemahasiswaan.mercubuana.ac.id/"],
    },
    {
        "scholarship_name": "Beasiswa PPA (Peningkatan Prestasi Akademik)",
        "provider": "Kemdikbudristek",
        "description": "Beasiswa Peningkatan Prestasi Akademik dari pemerintah",
        "eligibility": "Mahasiswa aktif dengan IPK minimal 3.0",
        "source_urls": ["https://kemahasiswaan.mercubuana.ac.id/"],
    },
    {
        "scholarship_name": "Beasiswa Yayasan Menara Bhakti",
        "provider": "Yayasan Menara Bhakti",
        "description": "Beasiswa dari Yayasan Menara Bhakti pengelola Universitas Mercu Buana",
        "source_urls": ["https://www.mercubuana.ac.id/"],
    },
]

CONTACT_SEEDS: list[dict] = [
    {
        "office_name": "Penerimaan Mahasiswa Baru (PMB)",
        "unit": "PMB",
        "service_type": "admission",
        "campus": "Meruya",
        "url": "https://pendaftaran.mercubuana.ac.id/",
        "phone": "(021) 5840816",
        "whatsapp": "08111776666",
        "email": "pmb@mercubuana.ac.id",
    },
    {
        "office_name": "Biro Administrasi Akademik (BAA)",
        "unit": "BAA",
        "service_type": "academic",
        "campus": "Meruya",
        "url": "https://baa.mercubuana.ac.id/",
        "email": "baa@mercubuana.ac.id",
    },
    {
        "office_name": "Student Support Center (BTI)",
        "unit": "BTI",
        "service_type": "technical_support",
        "campus": "Meruya",
        "url": "https://support.mercubuana.ac.id/",
    },
    {
        "office_name": "Kemahasiswaan / Ditmawa",
        "unit": "Ditmawa",
        "service_type": "student_affairs",
        "campus": "Meruya",
        "url": "https://kemahasiswaan.mercubuana.ac.id/",
    },
    {
        "office_name": "Perpustakaan UMB",
        "unit": "Library",
        "service_type": "library",
        "campus": "Meruya",
        "url": "https://lib.mercubuana.ac.id/",
        "email": "perpustakaan@mercubuana.ac.id",
    },
    {
        "office_name": "SSO (Single Sign-On) UMB",
        "unit": "BTI",
        "service_type": "sso",
        "campus": "Meruya",
        "url": "https://sso.mercubuana.ac.id/",
    },
    {
        "office_name": "SIA (Sistem Informasi Akademik) UMB",
        "unit": "BTI",
        "service_type": "sia",
        "campus": "Meruya",
        "url": "https://sia.mercubuana.ac.id/",
    },
]

SERVICE_SEEDS: list[dict] = [
    {
        "service_name": "Pendaftaran Mahasiswa Baru (PMB) Online",
        "description": "Pendaftaran calon mahasiswa baru secara online melalui portal pendaftaran UMB",
        "unit": "PMB",
        "url": "https://pendaftaran.mercubuana.ac.id/",
        "category": "admission",
    },
    {
        "service_name": "Sistem Informasi Akademik (SIA)",
        "description": "Portal akademik mahasiswa untuk KRS, nilai, dan jadwal kuliah",
        "unit": "BTI",
        "url": "https://sia.mercubuana.ac.id/",
        "category": "academic",
    },
    {
        "service_name": "Single Sign-On (SSO)",
        "description": "Sistem autentikasi terpusat untuk semua layanan digital UMB",
        "unit": "BTI",
        "url": "https://sso.mercubuana.ac.id/",
        "category": "authentication",
    },
    {
        "service_name": "E-Learning UMB",
        "description": "Platform pembelajaran online Universitas Mercu Buana",
        "unit": "BTI",
        "url": "https://elearning.mercubuana.ac.id/",
        "category": "academic",
    },
    {
        "service_name": "Repository Institusi UMB",
        "description": "Repositori karya ilmiah mahasiswa dan dosen UMB (skripsi, tesis, jurnal)",
        "unit": "Library",
        "url": "https://repository.mercubuana.ac.id/",
        "category": "library",
    },
    {
        "service_name": "Perpustakaan Digital UMB",
        "description": "Layanan perpustakaan digital dan akses koleksi buku elektronik",
        "unit": "Library",
        "url": "https://lib.mercubuana.ac.id/",
        "category": "library",
    },
]

# ---------------------------------------------------------------------------
# Extraction patterns
# ---------------------------------------------------------------------------

# "Dekan: Prof. Dr. Name" / "Dekan Fakultas X adalah Dr. Name"
_RE_DEAN = re.compile(
    r"[Dd]ekan\s*(?:[Ff]akultas[\w\s]+)?(?:adalah|:|-|–)\s*"
    r"((?:Prof\.|Dr\.|Ir\.|M\.Sc\.|S\.T\.|S\.Kom\.|M\.T\.)?\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,5})",
    re.MULTILINE,
)

# "Kaprodi: Dr. Name" / "Ketua Program Studi: ..."
_RE_KAPRODI = re.compile(
    r"(?:[Kk]aprodi|[Kk]etua\s+[Pp]rogram\s+[Ss]tudi)\s*(?:adalah|:|-|–)\s*"
    r"((?:Prof\.|Dr\.|Ir\.|M\.T\.|S\.T\.)?\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,4})",
    re.MULTILINE,
)

# "Akreditasi A" / "Terakreditasi Unggul" / "Akreditasi: Unggul"
_RE_AKREDITASI = re.compile(
    r"(?:[Tt]erakreditasi|[Aa]kreditasi)[\s\w]*?[:\s]+(A\b|B\b|C\b|Unggul|Sangat Baik|Baik Sekali|Baik)",
    re.MULTILINE,
)

# Jakarta addresses
_RE_ADDRESS = re.compile(
    r"(?:Jl\.|Jalan)\s+[A-Z][A-Za-z\s]+(?:No\.|Nomor|No)\.?\s*[\d]+[^,\n]{0,80}",
    re.MULTILINE,
)

# Indonesian phone numbers
_RE_PHONE = re.compile(
    r"(?:Telp\.?|Telepon|Phone|Fax|Faks\.?|WA|WhatsApp)?[:\s]*(\+?(?:62|0)[\s\-]?(?:21|811|812|813|878|877|852|853)?[\s\-]?[\d][\d\s\-]{6,13})",
    re.IGNORECASE | re.MULTILINE,
)

# UMB email addresses
_RE_EMAIL = re.compile(
    r"[\w\.\+\-]+@(?:mercubuana\.ac\.id|student\.mercubuana\.ac\.id)",
    re.IGNORECASE,
)


def _first_match(pattern: re.Pattern, text: str) -> str | None:
    m = pattern.search(text)
    return m.group(1).strip() if m else None


_RE_VALID_PHONE = re.compile(r"^(?:\+62|62|0)[1-9][\d]{6,13}$")


def _normalize_phone(raw: str) -> str:
    return re.sub(r"[\s\-\(\)]", "", raw)


def _is_valid_indonesian_phone(normalized: str) -> bool:
    return bool(_RE_VALID_PHONE.match(normalized)) and 8 <= len(normalized) <= 16


# ---------------------------------------------------------------------------
# Seed pass
# ---------------------------------------------------------------------------


def seed_entities(db: Session, confidence: float = 0.85) -> dict:
    from app.db.models import (
        UMBCampus,
        UMBContact,
        UMBFaculty,
        UMBScholarship,
        UMBService,
        UMBStudyProgram,
    )

    counts: dict[str, int] = {
        "faculties": 0,
        "programs": 0,
        "campuses": 0,
        "scholarships": 0,
        "contacts": 0,
        "services": 0,
    }

    # Faculties
    for seed in FACULTY_SEEDS:
        existing = db.query(UMBFaculty).filter(UMBFaculty.name == seed["name"]).first()
        if existing is None:
            db.add(UMBFaculty(**seed, confidence=confidence, source_urls=[]))
            counts["faculties"] += 1
    db.flush()

    # Programs (resolve faculty FK)
    fac_map: dict[str, str] = {
        f.name: str(f.id) for f in db.query(UMBFaculty).all()
    }
    for seed in PROGRAM_SEEDS:
        key = f"{seed['program_name']}|{seed['degree_level']}|{seed['faculty_name']}"
        existing = db.query(UMBStudyProgram).filter(UMBStudyProgram.upsert_key == key).first()
        if existing is None:
            fac_id = fac_map.get(seed["faculty_name"])
            db.add(
                UMBStudyProgram(
                    upsert_key=key,
                    program_name=seed["program_name"],
                    degree_level=seed["degree_level"],
                    faculty_name=seed["faculty_name"],
                    faculty_id=fac_id,
                    confidence=confidence,
                    source_urls=[],
                )
            )
            counts["programs"] += 1
    db.flush()

    # Campuses
    for seed in CAMPUS_SEEDS:
        existing = db.query(UMBCampus).filter(UMBCampus.campus_name == seed["campus_name"]).first()
        if existing is None:
            db.add(UMBCampus(**seed, confidence=confidence, source_urls=[]))
            counts["campuses"] += 1
    db.flush()

    # Scholarships
    for seed in SCHOLARSHIP_SEEDS:
        existing = (
            db.query(UMBScholarship)
            .filter(UMBScholarship.scholarship_name == seed["scholarship_name"])
            .first()
        )
        if existing is None:
            db.add(
                UMBScholarship(
                    **{k: v for k, v in seed.items() if k != "source_urls"},
                    source_urls=seed.get("source_urls", []),
                    confidence=confidence,
                )
            )
            counts["scholarships"] += 1
    db.flush()

    # Contacts
    contact_ids: dict[str, str] = {}
    for seed in CONTACT_SEEDS:
        key = f"{seed['office_name']}|{seed.get('campus', '')}"
        existing = db.query(UMBContact).filter(UMBContact.upsert_key == key).first()
        if existing is None:
            row = UMBContact(
                upsert_key=key,
                **{k: v for k, v in seed.items() if k != "source_urls"},
                source_urls=seed.get("source_urls", []),
                confidence=confidence,
            )
            db.add(row)
            db.flush()
            contact_ids[seed["office_name"]] = str(row.id)
            counts["contacts"] += 1
        else:
            contact_ids[seed["office_name"]] = str(existing.id)
    db.flush()

    # Services
    for seed in SERVICE_SEEDS:
        existing = db.query(UMBService).filter(UMBService.service_name == seed["service_name"]).first()
        if existing is None:
            db.add(
                UMBService(
                    **{k: v for k, v in seed.items() if k != "source_urls"},
                    source_urls=seed.get("source_urls", []),
                    confidence=confidence,
                )
            )
            counts["services"] += 1
    db.flush()

    db.commit()
    return counts


# ---------------------------------------------------------------------------
# Mine pass — scan indexed chunks
# ---------------------------------------------------------------------------


def mine_entities(db: Session, confidence: float = 0.65) -> dict:
    from app.db.models import Chunk, Source, UMBCampus, UMBFaculty, UMBStudyProgram

    updates: dict[str, int] = {"faculty_dean": 0, "faculty_accreditation": 0, "program_head": 0, "campus_phone": 0}

    # Load all faculties for matching
    faculties = db.query(UMBFaculty).all()
    programs = db.query(UMBStudyProgram).all()
    campuses = db.query(UMBCampus).all()

    # ------------------------------------------------------------------
    # Faculty dean + accreditation — search chunks from faculty websites
    # ------------------------------------------------------------------
    for faculty in faculties:
        if not faculty.website_url:
            continue
        hostname = faculty.website_url.split("/")[2] if faculty.website_url else None
        if not hostname:
            continue

        # Find chunks from this faculty's hostname
        rows = (
            db.query(Chunk, Source)
            .join(Source, Chunk.source_id == Source.id)
            .filter(Source.status == "indexed", Source.hostname == hostname)
            .limit(50)
            .all()
        )

        combined = " ".join(
            (chunk.chunk_text or "") + " " + (source.url or "") + " " + (source.title or "")
            for chunk, source in rows
        )
        if not combined.strip():
            continue

        changed = False
        if not faculty.dean:
            dean = _first_match(_RE_DEAN, combined)
            if dean and 3 < len(dean) < 80:
                faculty.dean = dean
                faculty.confidence = max(faculty.confidence or 0.0, confidence)
                updates["faculty_dean"] += 1
                changed = True

        if not faculty.accreditation_grade:
            grade = _first_match(_RE_AKREDITASI, combined)
            if grade:
                faculty.accreditation_grade = grade
                faculty.confidence = max(faculty.confidence or 0.0, confidence)
                updates["faculty_accreditation"] += 1
                changed = True

        if changed:
            db.flush()

    # ------------------------------------------------------------------
    # Study program kaprodi — search chunks mentioning program name
    # ------------------------------------------------------------------
    for program in programs:
        if program.head_of_program:
            continue
        name_lower = program.program_name.lower()
        rows = (
            db.query(Chunk, Source)
            .join(Source, Chunk.source_id == Source.id)
            .filter(
                Source.status == "indexed",
                Chunk.chunk_text.ilike(f"%{program.program_name}%"),
                Chunk.chunk_text.ilike("%kaprodi%"),
            )
            .limit(20)
            .all()
        )
        combined = " ".join((chunk.chunk_text or "") for chunk, _ in rows)
        if not combined.strip():
            continue
        head = _first_match(_RE_KAPRODI, combined)
        if head and 3 < len(head) < 80:
            program.head_of_program = head
            program.confidence = max(program.confidence or 0.0, confidence)
            updates["program_head"] += 1
            db.flush()

    # ------------------------------------------------------------------
    # Campus phone — search chunks from www.mercubuana.ac.id about campus
    # ------------------------------------------------------------------
    for campus in campuses:
        if campus.phone:
            continue
        campus_lower = campus.campus_name.lower()
        rows = (
            db.query(Chunk, Source)
            .join(Source, Chunk.source_id == Source.id)
            .filter(
                Source.status == "indexed",
                Source.hostname == "www.mercubuana.ac.id",
                Chunk.chunk_text.ilike(f"%{campus.campus_name}%"),
            )
            .limit(20)
            .all()
        )
        combined = " ".join((chunk.chunk_text or "") for chunk, _ in rows)
        phone = _first_match(_RE_PHONE, combined)
        if phone:
            normalized = _normalize_phone(phone)
            if _is_valid_indonesian_phone(normalized):
                campus.phone = phone.strip()
                campus.confidence = max(campus.confidence or 0.0, confidence)
                updates["campus_phone"] += 1
                db.flush()

    db.commit()
    return updates


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="UMB entity extractor — populate structured entity tables")
    parser.add_argument("--seed", action="store_true", help="Insert curated seed entities")
    parser.add_argument("--mine", action="store_true", help="Mine chunks to enrich entity fields")
    parser.add_argument(
        "--out",
        default="../data/reports/entity_extract.json",
        help="Output report path",
    )
    args = parser.parse_args(argv)

    if not args.seed and not args.mine:
        parser.print_help()
        sys.exit(0)

    from app.db.database import get_session_local

    session_factory = get_session_local()
    db: Session = session_factory()
    report: dict = {}

    try:
        # Ensure tables exist (SQLite test / first-time setup)
        try:
            from app.db.database import get_engine
            from app.db.models import Base

            engine = get_engine()
            Base.metadata.create_all(engine, checkfirst=True)
        except Exception as exc:
            logger.warning("create_all skipped: %s", exc)

        if args.seed:
            logger.info("Running seed pass…")
            counts = seed_entities(db)
            report["seed"] = counts
            logger.info("Seed: %s", counts)

        if args.mine:
            logger.info("Running mine pass…")
            updates = mine_entities(db)
            report["mine"] = updates
            logger.info("Mine: %s", updates)

    except OperationalError as exc:
        logger.error("DB error (tables missing? run migration 002_umb_entities.sql): %s", exc)
        raise
    finally:
        db.close()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Report written to %s", out_path)


if __name__ == "__main__":
    main()
