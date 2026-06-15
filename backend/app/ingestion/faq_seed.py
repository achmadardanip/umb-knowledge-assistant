"""
Curated canonical FAQ seed data + seeder — Phase 3.

Covers the domains the Phase-1 benchmark flagged weak (admissions, SIA, SSO,
student services, scholarships) plus tuition, library, calendar, and contacts.

Answers are deliberately conservative: for volatile facts (exact tuition,
deadlines) they direct the user to the official portal rather than stating a
number that could go stale.  Each FAQ carries an official ``source_urls`` for
citation.

Usage (from backend/):
  PYTHONPATH=. .venv/Scripts/python.exe -m app.ingestion.faq_seed \
      --out ../data/reports/faq_seed.json
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


FAQ_SEEDS: list[dict] = [
    # ---------------- Admissions ----------------
    {
        "canonical_question": "Bagaimana cara mendaftar sebagai mahasiswa baru di UMB?",
        "answer": (
            "Pendaftaran mahasiswa baru Universitas Mercu Buana dilakukan secara online "
            "melalui portal resmi PMB di https://pendaftaran.mercubuana.ac.id/. Calon mahasiswa "
            "membuat akun, mengisi formulir pendaftaran, mengunggah dokumen yang dipersyaratkan, "
            "membayar biaya pendaftaran, lalu mengikuti seleksi sesuai jalur yang dipilih. "
            "Detail jalur, jadwal, dan persyaratan terbaru tersedia di portal pendaftaran."
        ),
        "aliases": [
            "cara daftar mahasiswa baru umb",
            "bagaimana mendaftar kuliah di mercu buana",
            "prosedur pendaftaran mahasiswa baru",
            "gimana cara daftar kuliah di umb",
            "langkah pendaftaran calon mahasiswa umb",
            "registrasi mahasiswa baru mercu buana",
        ],
        "category": "admissions",
        "intent": "admission",
        "source_urls": ["https://pendaftaran.mercubuana.ac.id/"],
        "source_confidence": 0.9,
    },
    {
        "canonical_question": "Apa saja syarat pendaftaran mahasiswa baru di UMB?",
        "answer": (
            "Syarat umum pendaftaran mahasiswa baru UMB meliputi ijazah/SKL dan rapor untuk "
            "jenjang sarjana (S1), pas foto, serta dokumen identitas. Untuk program pascasarjana "
            "(S2) dibutuhkan ijazah dan transkrip S1. Persyaratan lengkap dan terbaru per jalur "
            "masuk dapat dilihat di portal pendaftaran resmi https://pendaftaran.mercubuana.ac.id/."
        ),
        "aliases": [
            "syarat daftar kuliah umb",
            "persyaratan pendaftaran mahasiswa baru mercu buana",
            "dokumen apa saja untuk mendaftar umb",
            "berkas pendaftaran calon mahasiswa umb",
        ],
        "category": "admissions",
        "intent": "admission",
        "source_urls": ["https://pendaftaran.mercubuana.ac.id/"],
        "source_confidence": 0.85,
    },
    {
        "canonical_question": "Kapan jadwal pendaftaran mahasiswa baru UMB dibuka?",
        "answer": (
            "Universitas Mercu Buana membuka pendaftaran mahasiswa baru dalam beberapa gelombang "
            "sepanjang tahun. Jadwal pembukaan tiap gelombang dan tenggat masing-masing dapat "
            "berubah, sehingga sebaiknya dicek langsung di portal resmi PMB "
            "https://pendaftaran.mercubuana.ac.id/ untuk informasi terbaru."
        ),
        "aliases": [
            "kapan pendaftaran umb dibuka",
            "jadwal pmb mercu buana",
            "gelombang pendaftaran mahasiswa baru umb",
            "kapan buka pendaftaran kuliah umb",
        ],
        "category": "admissions",
        "intent": "admission",
        "source_urls": ["https://pendaftaran.mercubuana.ac.id/"],
        "source_confidence": 0.8,
    },
    # ---------------- Tuition ----------------
    {
        "canonical_question": "Berapa biaya kuliah di Universitas Mercu Buana?",
        "answer": (
            "Biaya kuliah di Universitas Mercu Buana berbeda-beda tergantung program studi, "
            "jenjang, kelas (reguler/karyawan), dan jalur masuk. Rincian biaya seperti uang "
            "pangkal, biaya per semester, dan skema angsuran tercantum di portal pendaftaran "
            "resmi https://pendaftaran.mercubuana.ac.id/. Karena nominal dapat berubah tiap "
            "periode, sebaiknya konfirmasi langsung ke PMB untuk angka terbaru."
        ),
        "aliases": [
            "biaya kuliah umb",
            "berapa uang kuliah mercu buana",
            "rincian biaya pendidikan umb",
            "biaya per semester di mercu buana",
            "uang pangkal kuliah umb",
        ],
        "category": "tuition",
        "intent": "tuition",
        "source_urls": ["https://pendaftaran.mercubuana.ac.id/"],
        "source_confidence": 0.82,
    },
    # ---------------- Scholarships ----------------
    {
        "canonical_question": "Apa saja beasiswa yang tersedia di UMB?",
        "answer": (
            "Universitas Mercu Buana menyediakan berbagai beasiswa, antara lain Beasiswa KIP "
            "Kuliah dari pemerintah untuk mahasiswa kurang mampu yang berprestasi, Beasiswa "
            "Peningkatan Prestasi Akademik (PPA), beasiswa prestasi internal UMB, serta beasiswa "
            "dari Yayasan Menara Bhakti. Persyaratan dan pendaftaran beasiswa dikelola melalui "
            "Direktorat/Biro Kemahasiswaan di https://kemahasiswaan.mercubuana.ac.id/."
        ),
        "aliases": [
            "beasiswa umb apa saja",
            "jenis beasiswa di mercu buana",
            "daftar beasiswa universitas mercu buana",
            "beasiswa yang ada di umb",
            "info beasiswa kuliah mercu buana",
        ],
        "category": "scholarship",
        "intent": "scholarship",
        "source_urls": ["https://kemahasiswaan.mercubuana.ac.id/"],
        "source_confidence": 0.82,
    },
    {
        "canonical_question": "Bagaimana cara mendaftar beasiswa KIP Kuliah di UMB?",
        "answer": (
            "Beasiswa KIP Kuliah ditujukan bagi calon mahasiswa dari keluarga kurang mampu yang "
            "berprestasi. Pendaftaran KIP Kuliah dilakukan melalui sistem KIP Kuliah Kemdikbud "
            "(kip-kuliah.kemdikbud.go.id) dan diverifikasi saat mendaftar di UMB. Informasi "
            "pendamping dan persyaratan di UMB tersedia melalui Biro Kemahasiswaan "
            "https://kemahasiswaan.mercubuana.ac.id/ dan portal PMB."
        ),
        "aliases": [
            "cara daftar kip kuliah umb",
            "beasiswa kip mercu buana",
            "pendaftaran kip kuliah di umb",
            "syarat kip kuliah umb",
        ],
        "category": "scholarship",
        "intent": "scholarship",
        "source_urls": ["https://kemahasiswaan.mercubuana.ac.id/"],
        "source_confidence": 0.8,
    },
    # ---------------- SSO ----------------
    {
        "canonical_question": "Bagaimana cara login SSO UMB?",
        "answer": (
            "SSO (Single Sign-On) UMB adalah satu akun untuk mengakses berbagai layanan digital "
            "Universitas Mercu Buana. Login dilakukan di https://sso.mercubuana.ac.id/ "
            "menggunakan username dan password yang diberikan kampus. Jika lupa password atau "
            "akun bermasalah, gunakan fitur reset di portal SSO atau hubungi Student Support "
            "Center di https://support.mercubuana.ac.id/."
        ),
        "aliases": [
            "cara login sso umb",
            "masuk sso mercu buana",
            "login single sign on umb",
            "gimana cara akses sso umb",
            "tidak bisa login sso umb",
        ],
        "category": "sso",
        "intent": "login_help",
        "source_urls": ["https://sso.mercubuana.ac.id/", "https://support.mercubuana.ac.id/"],
        "source_confidence": 0.85,
    },
    {
        "canonical_question": "Bagaimana cara reset atau lupa password SSO/SIA UMB?",
        "answer": (
            "Jika lupa password SSO atau SIA UMB, gunakan menu lupa/reset password pada portal "
            "SSO di https://sso.mercubuana.ac.id/. Apabila reset mandiri tidak berhasil atau akun "
            "terkunci, ajukan bantuan melalui Student Support Center "
            "https://support.mercubuana.ac.id/ dengan menyertakan identitas mahasiswa untuk "
            "verifikasi."
        ),
        "aliases": [
            "lupa password sia umb",
            "reset password sso mercu buana",
            "cara ganti password sia umb",
            "akun sia terkunci umb",
            "lupa kata sandi sso umb",
        ],
        "category": "sso",
        "intent": "login_help",
        "source_urls": ["https://sso.mercubuana.ac.id/", "https://support.mercubuana.ac.id/"],
        "source_confidence": 0.83,
    },
    # ---------------- SIA ----------------
    {
        "canonical_question": "Apa itu SIA UMB dan bagaimana cara mengaksesnya?",
        "answer": (
            "SIA (Sistem Informasi Akademik) adalah portal akademik mahasiswa Universitas Mercu "
            "Buana untuk mengisi KRS, melihat nilai, jadwal kuliah, dan data akademik lainnya. "
            "SIA diakses di https://sia.mercubuana.ac.id/ menggunakan akun SSO mahasiswa. "
            "Untuk kendala teknis, hubungi Student Support Center "
            "https://support.mercubuana.ac.id/."
        ),
        "aliases": [
            "apa itu sia umb",
            "cara akses sia mercu buana",
            "login sia umb",
            "sistem informasi akademik umb",
            "cara buka sia umb",
        ],
        "category": "sia",
        "intent": "login_help",
        "source_urls": ["https://sia.mercubuana.ac.id/", "https://support.mercubuana.ac.id/"],
        "source_confidence": 0.85,
    },
    {
        "canonical_question": "Bagaimana cara mengisi KRS di SIA UMB?",
        "answer": (
            "Pengisian KRS (Kartu Rencana Studi) dilakukan melalui SIA di "
            "https://sia.mercubuana.ac.id/ pada periode KRS yang ditentukan dalam kalender "
            "akademik. Mahasiswa login dengan akun SSO, memilih mata kuliah sesuai paket/semester, "
            "lalu menyimpan dan memvalidasi KRS (umumnya dengan persetujuan dosen pembimbing "
            "akademik). Jadwal periode KRS mengikuti kalender akademik UMB."
        ),
        "aliases": [
            "cara isi krs umb",
            "pengisian krs sia mercu buana",
            "input krs di sia umb",
            "kapan pengisian krs umb",
        ],
        "category": "sia",
        "intent": "academic",
        "source_urls": ["https://sia.mercubuana.ac.id/"],
        "source_confidence": 0.8,
    },
    # ---------------- Student services ----------------
    {
        "canonical_question": "Ke mana menghubungi layanan bantuan mahasiswa UMB?",
        "answer": (
            "Layanan bantuan untuk mahasiswa UMB ditangani oleh Student Support Center yang dapat "
            "diakses di https://support.mercubuana.ac.id/ untuk kendala akun, SSO/SIA, dan layanan "
            "teknis. Urusan kemahasiswaan (beasiswa, organisasi, kegiatan) dikelola Biro "
            "Kemahasiswaan https://kemahasiswaan.mercubuana.ac.id/, sedangkan administrasi "
            "akademik oleh BAA https://baa.mercubuana.ac.id/."
        ),
        "aliases": [
            "kontak layanan mahasiswa umb",
            "bantuan mahasiswa mercu buana",
            "student support center umb",
            "cara menghubungi helpdesk umb",
            "layanan bantuan teknis umb",
        ],
        "category": "student_services",
        "intent": "contact",
        "source_urls": ["https://support.mercubuana.ac.id/"],
        "source_confidence": 0.83,
    },
    {
        "canonical_question": "Bagaimana cara mengurus legalisir ijazah atau transkrip di UMB?",
        "answer": (
            "Pengurusan legalisir ijazah dan transkrip bagi alumni UMB dilayani melalui Biro "
            "Administrasi Akademik (BAA) di https://baa.mercubuana.ac.id/. Alumni umumnya mengajukan "
            "permohonan, menyerahkan salinan dokumen, dan mengikuti prosedur yang ditetapkan BAA. "
            "Detail prosedur dan kanal layanan terbaru tersedia di situs BAA."
        ),
        "aliases": [
            "legalisir ijazah umb",
            "cara legalisir transkrip mercu buana",
            "urus ijazah alumni umb",
            "legalisir dokumen akademik umb",
        ],
        "category": "student_services",
        "intent": "academic",
        "source_urls": ["https://baa.mercubuana.ac.id/"],
        "source_confidence": 0.8,
    },
    # ---------------- Library ----------------
    {
        "canonical_question": "Di mana mengakses perpustakaan dan repository UMB?",
        "answer": (
            "Perpustakaan Universitas Mercu Buana dapat diakses melalui https://lib.mercubuana.ac.id/ "
            "untuk katalog dan layanan perpustakaan. Karya ilmiah seperti skripsi, tesis, dan jurnal "
            "tersedia di repository institusi https://repository.mercubuana.ac.id/. Repository "
            "merupakan arsip karya akademik, bukan kanal informasi resmi terkini kampus."
        ),
        "aliases": [
            "perpustakaan umb",
            "akses perpustakaan mercu buana",
            "repository umb",
            "cara akses repository mercu buana",
            "digilib umb",
        ],
        "category": "campus_information",
        "intent": "library",
        "source_urls": ["https://lib.mercubuana.ac.id/"],
        "source_confidence": 0.82,
    },
    # ---------------- Academic calendar ----------------
    {
        "canonical_question": "Di mana melihat kalender akademik UMB?",
        "answer": (
            "Kalender akademik Universitas Mercu Buana memuat jadwal penting seperti awal "
            "perkuliahan, periode KRS, UTS, UAS, dan libur. Kalender akademik resmi dipublikasikan "
            "oleh Biro Administrasi Akademik (BAA) di https://baa.mercubuana.ac.id/ dan dapat "
            "diakses mahasiswa melalui portal akademik. Karena tanggal berubah tiap tahun "
            "akademik, rujuk versi terbaru di situs BAA."
        ),
        "aliases": [
            "kalender akademik umb",
            "jadwal akademik mercu buana",
            "academic calendar umb",
            "kapan mulai kuliah umb",
            "jadwal uts uas umb",
        ],
        "category": "academic_calendar",
        "intent": "academic",
        "source_urls": ["https://baa.mercubuana.ac.id/"],
        "source_confidence": 0.8,
    },
    # ---------------- Faculties / programs ----------------
    {
        "canonical_question": "Apa saja fakultas dan program studi di UMB?",
        "answer": (
            "Universitas Mercu Buana memiliki sejumlah fakultas, antara lain Fakultas Ekonomi dan "
            "Bisnis, Fakultas Teknik, Fakultas Ilmu Komputer, Fakultas Ilmu Komunikasi, Fakultas "
            "Desain dan Seni Kreatif, dan Fakultas Psikologi, serta program Pascasarjana. "
            "Masing-masing fakultas menaungi beberapa program studi jenjang S1 dan S2. Daftar "
            "lengkap program studi tersedia di https://www.mercubuana.ac.id/."
        ),
        "aliases": [
            "fakultas di umb apa saja",
            "program studi mercu buana",
            "jurusan yang ada di umb",
            "daftar prodi umb",
            "fakultas dan jurusan mercu buana",
        ],
        "category": "faculties",
        "intent": "faculty",
        "source_urls": ["https://www.mercubuana.ac.id/"],
        "source_confidence": 0.82,
    },
    # ---------------- Campus information ----------------
    {
        "canonical_question": "Di mana lokasi kampus Universitas Mercu Buana?",
        "answer": (
            "Universitas Mercu Buana memiliki beberapa lokasi kampus. Kampus utama berada di "
            "Meruya, Jakarta Barat (Jl. Meruya Selatan No.1, Kembangan). UMB juga memiliki kampus "
            "di Menteng (Jakarta Pusat), Warung Buncit (Jakarta Selatan), dan Bekasi. Alamat dan "
            "kontak tiap kampus tersedia di https://www.mercubuana.ac.id/."
        ),
        "aliases": [
            "lokasi kampus umb",
            "alamat mercu buana",
            "kampus umb dimana",
            "alamat kampus meruya umb",
            "dimana letak universitas mercu buana",
        ],
        "category": "campus_information",
        "intent": "location",
        "source_urls": ["https://www.mercubuana.ac.id/"],
        "source_confidence": 0.85,
    },
    # ---------------- Contact ----------------
    {
        "canonical_question": "Bagaimana cara menghubungi bagian pendaftaran (PMB) UMB?",
        "answer": (
            "Bagian Penerimaan Mahasiswa Baru (PMB) Universitas Mercu Buana dapat dihubungi melalui "
            "portal pendaftaran https://pendaftaran.mercubuana.ac.id/ yang memuat kanal kontak "
            "resmi (telepon, WhatsApp, dan email PMB). Layanan ini melayani pertanyaan seputar "
            "jalur masuk, biaya, jadwal, dan prosedur pendaftaran."
        ),
        "aliases": [
            "kontak pmb umb",
            "nomor telepon pendaftaran mercu buana",
            "cara hubungi pmb umb",
            "whatsapp pendaftaran umb",
            "kontak pendaftaran mahasiswa baru umb",
        ],
        "category": "admissions",
        "intent": "contact",
        "source_urls": ["https://pendaftaran.mercubuana.ac.id/"],
        "source_confidence": 0.82,
    },
]


def seed_faqs(db: Session, *, deactivate_missing: bool = False) -> dict:
    """Upsert curated FAQs by canonical_question. Returns counts."""
    from app.db.models import UMBFAQ
    from app.rag.answer_cache import normalize_question

    inserted = 0
    updated = 0
    for seed in FAQ_SEEDS:
        canonical = seed["canonical_question"]
        normalized = normalize_question(canonical)
        row = db.query(UMBFAQ).filter(UMBFAQ.canonical_question == canonical).first()
        if row is None:
            db.add(
                UMBFAQ(
                    canonical_question=canonical,
                    normalized_question=normalized,
                    answer=seed["answer"],
                    aliases=seed.get("aliases", []),
                    category=seed.get("category"),
                    intent=seed.get("intent"),
                    source_urls=seed.get("source_urls", []),
                    source_confidence=seed.get("source_confidence", 0.8),
                    is_active=True,
                )
            )
            inserted += 1
        else:
            # Refresh curated content (answers/aliases may have been revised).
            row.normalized_question = normalized
            row.answer = seed["answer"]
            row.aliases = seed.get("aliases", [])
            row.category = seed.get("category")
            row.intent = seed.get("intent")
            row.source_urls = seed.get("source_urls", [])
            row.source_confidence = seed.get("source_confidence", 0.8)
            row.is_active = True
            updated += 1
    db.commit()
    return {"inserted": inserted, "updated": updated, "total_seeds": len(FAQ_SEEDS)}


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Seed curated canonical FAQs into umb_faqs")
    parser.add_argument("--out", default="../data/reports/faq_seed.json", help="Report output path")
    args = parser.parse_args(argv)

    from app.db.database import get_engine, get_session_local
    from app.db.models import Base

    try:
        Base.metadata.create_all(get_engine(), checkfirst=True)
    except Exception as exc:
        logger.warning("create_all skipped: %s", exc)

    db: Session = get_session_local()()
    try:
        counts = seed_faqs(db)
        logger.info("FAQ seed: %s", counts)
    finally:
        db.close()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(counts, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Report written to %s", out_path)


if __name__ == "__main__":
    main()
