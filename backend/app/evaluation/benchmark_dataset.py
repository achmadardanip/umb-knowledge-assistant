"""UMB answerability benchmark dataset generator.

Produces a large (500-1000+) labelled question set spanning the twelve
university use-case categories, grounded in entities actually present in the
indexed KB (faculties, study programs, campuses). Each record is directly
consumable by ``evaluate_rag.evaluate`` (same schema: ``expected_hosts``,
``expected_url_contains``, ``expected_source_types``, ``forbidden_hosts``,
``expected_not_found``) and carries a ``qtype`` (direct / paraphrase /
ambiguous / multi_hop) and ``audience`` for stratified reporting.

The generator is deterministic: identical entities yield an identical dataset
with stable ids, so benchmark reports are comparable across runs. Entities can
be supplied (e.g. mined from the DB) or default to a curated set that matches
the current KB so the dataset is reproducible without a database.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# --- Default entities (mined from the indexed KB, 2026-06) -------------------
# Override via ``load_entities`` to regenerate against a refreshed KB.
DEFAULT_FACULTIES = [
    "Fakultas Ekonomi dan Bisnis",
    "Fakultas Teknik",
    "Fakultas Ilmu Komputer",
    "Fakultas Ilmu Komunikasi",
    "Fakultas Desain dan Seni Kreatif",
    "Fakultas Psikologi",
]
DEFAULT_PROGRAMS = [
    "Teknik Informatika",
    "Sistem Informasi",
    "Teknik Elektro",
    "Teknik Mesin",
    "Teknik Sipil",
    "Teknik Industri",
    "Manajemen",
    "Akuntansi",
    "Ilmu Komunikasi",
    "Psikologi",
    "Desain Komunikasi Visual",
    "Arsitektur",
    "Penyiaran",
    "Periklanan",
]
DEFAULT_CAMPUSES = ["Meruya", "Menteng", "Warung Buncit", "Bekasi"]


@dataclass(frozen=True)
class Entities:
    faculties: tuple[str, ...] = field(default_factory=lambda: tuple(DEFAULT_FACULTIES))
    programs: tuple[str, ...] = field(default_factory=lambda: tuple(DEFAULT_PROGRAMS))
    campuses: tuple[str, ...] = field(default_factory=lambda: tuple(DEFAULT_CAMPUSES))


def load_entities(path: str | Path | None = None) -> Entities:
    """Load mined entities from JSON (``{faculties, programs, campuses}``).

    Falls back to the curated defaults when the file is missing/partial. Faculty
    case-variant duplicates are collapsed.
    """
    if path is None:
        return Entities()
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Entities()

    def _dedupe(values: list[str], fallback: list[str]) -> tuple[str, ...]:
        seen: dict[str, str] = {}
        for value in values or []:
            key = " ".join(str(value).split()).strip()
            if len(key) < 3:
                continue
            seen.setdefault(key.lower(), key)
        return tuple(seen.values()) or tuple(fallback)

    return Entities(
        faculties=_dedupe(raw.get("faculties", []), DEFAULT_FACULTIES),
        programs=_dedupe(raw.get("programs", []), DEFAULT_PROGRAMS),
        campuses=_dedupe(raw.get("campuses", []), DEFAULT_CAMPUSES),
    )


# --- Category specs ----------------------------------------------------------
# ``hosts`` / ``url_contains`` mark where an official answer is expected to live
# (drives retrieval-accuracy / target-hit). These are the *ideal* official
# locations; categories whose pages are not yet indexed surface as weak domains,
# which is exactly the diagnostic the benchmark exists to produce.
@dataclass(frozen=True)
class CategorySpec:
    category: str
    hosts: tuple[str, ...]
    url_contains: tuple[str, ...] = ()
    source_types: tuple[str, ...] = ()
    volatility: str = "low"
    stakes: str = "medium"
    audience: str = "publik"


CATEGORY_SPECS: dict[str, CategorySpec] = {
    "admissions": CategorySpec("admissions", ("pendaftaran.mercubuana.ac.id", "pmb.mercubuana.ac.id"), ("pendaftaran", "cara-pendaftaran"), volatility="medium", stakes="high", audience="calon_mahasiswa"),
    "tuition": CategorySpec("tuition", ("pendaftaran.mercubuana.ac.id", "pmb.mercubuana.ac.id"), ("biaya",), volatility="high", stakes="high", audience="calon_mahasiswa"),
    "scholarship": CategorySpec("scholarship", ("ditmawa.mercubuana.ac.id", "pendaftaran.mercubuana.ac.id"), ("beasiswa",), volatility="high", stakes="high", audience="calon_mahasiswa"),
    "faculties": CategorySpec("faculties", ("mercubuana.ac.id", "feb.mercubuana.ac.id"), ("fakultas",), volatility="low", stakes="medium", audience="publik"),
    "study_programs": CategorySpec("study_programs", ("mercubuana.ac.id", "pendaftaran.mercubuana.ac.id", "feb.mercubuana.ac.id"), ("program-studi", "fakultas"), volatility="low", stakes="medium", audience="calon_mahasiswa"),
    "lecturers_staff": CategorySpec("lecturers_staff", ("feb.mercubuana.ac.id", "mercubuana.ac.id"), ("dosen", "dekan"), volatility="low", stakes="low", audience="mahasiswa"),
    "academic_calendar": CategorySpec("academic_calendar", ("baa.mercubuana.ac.id", "mercubuana.ac.id"), ("kalender", "akademik"), volatility="high", stakes="high", audience="mahasiswa"),
    "academic_regulations": CategorySpec("academic_regulations", ("baa.mercubuana.ac.id", "mercubuana.ac.id"), ("peraturan", "panduan"), volatility="low", stakes="high", audience="mahasiswa"),
    "student_services": CategorySpec("student_services", ("baa.mercubuana.ac.id", "ditmawa.mercubuana.ac.id", "support.mercubuana.ac.id"), (), volatility="low", stakes="medium", audience="mahasiswa"),
    "campus_information": CategorySpec("campus_information", ("mercubuana.ac.id", "pendaftaran.mercubuana.ac.id"), ("lokasi", "kampus"), volatility="low", stakes="low", audience="publik"),
    "sia": CategorySpec("sia", ("sia.mercubuana.ac.id", "baa.mercubuana.ac.id", "support.mercubuana.ac.id"), ("sia",), volatility="low", stakes="medium", audience="mahasiswa"),
    "sso": CategorySpec("sso", ("sso.mercubuana.ac.id", "support.mercubuana.ac.id"), ("sso",), volatility="low", stakes="medium", audience="mahasiswa"),
}

ARCHIVE_HOSTS = (
    "repository.mercubuana.ac.id",
    "publikasi.mercubuana.ac.id",
    "proceeding.mercubuana.ac.id",
)


# --- Templates ---------------------------------------------------------------
# Each template is (qtype, lang, text). ``{faculty}`` / ``{program}`` /
# ``{campus}`` slots are filled from the entity set; templates without a slot
# are emitted once. ``multi_hop`` templates combine two relations/entities.
TEMPLATES: dict[str, list[tuple[str, str, str]]] = {
    "admissions": [
        ("direct", "id", "Bagaimana cara mendaftar sebagai mahasiswa baru di Universitas Mercu Buana?"),
        ("direct", "id", "Apa saja syarat pendaftaran mahasiswa baru di UMB?"),
        ("direct", "id", "Kapan jadwal pendaftaran mahasiswa baru UMB dibuka?"),
        ("direct", "id", "Apa saja jalur penerimaan mahasiswa baru di Mercu Buana?"),
        ("direct", "id", "Bagaimana alur pendaftaran online di UMB?"),
        ("paraphrase", "id", "Saya mau kuliah di Mercu Buana, mulai daftarnya bagaimana?"),
        ("paraphrase", "id", "Langkah-langkah daftar kuliah di UMB itu apa saja?"),
        ("ambiguous", "id", "Daftar UMB gimana?"),
        ("ambiguous", "id", "Pendaftaran?"),
        ("direct", "en", "How do I register as a new student at Universitas Mercu Buana?"),
        ("direct", "en", "What are the admission requirements for UMB?"),
        ("multi_hop", "id", "Bagaimana cara mendaftar program studi {program} di UMB?"),
        ("multi_hop", "id", "Apa syarat masuk {faculty} di Mercu Buana?"),
        ("multi_hop", "id", "Berapa daya tampung program studi {program} di UMB?"),
    ],
    "tuition": [
        ("direct", "id", "Berapa biaya kuliah di Universitas Mercu Buana?"),
        ("direct", "id", "Di mana saya bisa melihat rincian biaya kuliah UMB?"),
        ("direct", "id", "Berapa uang pangkal dan SPP per semester di UMB?"),
        ("paraphrase", "id", "Kuliah di Mercu Buana habis biaya berapa?"),
        ("paraphrase", "id", "Total biaya per semester di UMB berapa ya?"),
        ("ambiguous", "id", "Biayanya berapa?"),
        ("direct", "en", "How much is the tuition fee at Mercu Buana University?"),
        ("multi_hop", "id", "Berapa biaya kuliah program studi {program} di UMB?"),
        ("multi_hop", "id", "Berapa biaya kuliah di {faculty}?"),
        ("multi_hop", "id", "Berapa biaya kuliah {program} untuk kelas karyawan di UMB?"),
    ],
    "scholarship": [
        ("direct", "id", "Apa saja beasiswa yang tersedia di Universitas Mercu Buana?"),
        ("direct", "id", "Bagaimana syarat dan cara mendaftar beasiswa di UMB?"),
        ("direct", "id", "Kapan pendaftaran beasiswa UMB dibuka?"),
        ("paraphrase", "id", "Ada bantuan biaya kuliah atau beasiswa apa saja di Mercu Buana?"),
        ("ambiguous", "id", "Beasiswa?"),
        ("direct", "en", "What scholarships are available at Mercu Buana University?"),
        ("direct", "id", "Apakah ada beasiswa KIP Kuliah di Universitas Mercu Buana?"),
        ("paraphrase", "id", "Keringanan biaya kuliah di UMB ada tidak?"),
        ("multi_hop", "id", "Apakah ada beasiswa untuk mahasiswa program studi {program} di UMB?"),
        ("multi_hop", "id", "Beasiswa apa yang bisa diambil mahasiswa baru {program} di UMB?"),
        ("multi_hop", "id", "Apakah mahasiswa {faculty} bisa mendapatkan beasiswa di UMB?"),
    ],
    "faculties": [
        ("direct", "id", "Apa saja fakultas yang ada di Universitas Mercu Buana?"),
        ("direct", "id", "Ada berapa fakultas di UMB?"),
        ("paraphrase", "id", "Universitas Mercu Buana punya fakultas apa saja?"),
        ("direct", "en", "What faculties does Universitas Mercu Buana have?"),
        ("direct", "id", "Apa saja program studi di {faculty}?"),
        ("multi_hop", "id", "Siapa dekan {faculty} Universitas Mercu Buana?"),
        ("multi_hop", "id", "Di mana lokasi dan kontak {faculty} UMB?"),
        ("multi_hop", "id", "Apa akreditasi dan jumlah program studi di {faculty}?"),
        ("ambiguous", "id", "{faculty}?"),
    ],
    "study_programs": [
        ("direct", "id", "Apa saja program studi yang tersedia di Universitas Mercu Buana?"),
        ("direct", "id", "Program studi {program} ada di fakultas apa di UMB?"),
        ("direct", "id", "Apa akreditasi program studi {program} di UMB?"),
        ("paraphrase", "id", "Jurusan {program} di Mercu Buana akreditasinya apa?"),
        ("multi_hop", "id", "Apa visi dan kurikulum program studi {program} di UMB?"),
        ("multi_hop", "id", "Siapa ketua program studi {program} Universitas Mercu Buana?"),
        ("ambiguous", "id", "Jurusan {program}?"),
        ("direct", "en", "What is the accreditation of the {program} study program at UMB?"),
    ],
    "lecturers_staff": [
        ("direct", "id", "Siapa dekan {faculty} Universitas Mercu Buana?"),
        ("direct", "id", "Siapa saja dosen di {faculty} UMB?"),
        ("paraphrase", "id", "Pimpinan {faculty} Mercu Buana siapa?"),
        ("multi_hop", "id", "Siapa ketua program studi {program} dan di fakultas mana?"),
        ("multi_hop", "id", "Siapa dosen pengampu di program studi {program} UMB?"),
        ("direct", "id", "Bagaimana struktur organisasi rektorat Universitas Mercu Buana?"),
        ("direct", "id", "Siapa rektor Universitas Mercu Buana saat ini?"),
    ],
    "academic_calendar": [
        ("direct", "id", "Di mana saya bisa melihat kalender akademik Universitas Mercu Buana?"),
        ("direct", "id", "Kapan perkuliahan semester ganjil UMB dimulai?"),
        ("direct", "id", "Kapan jadwal UTS dan UAS di UMB?"),
        ("direct", "id", "Kapan batas akhir pengisian KRS di UMB?"),
        ("direct", "id", "Kapan masa libur semester di Universitas Mercu Buana?"),
        ("paraphrase", "id", "Kalender akademik Mercu Buana tahun ini di mana?"),
        ("paraphrase", "id", "Jadwal akademik UMB semester ini bagaimana?"),
        ("ambiguous", "id", "Kalender akademik?"),
        ("ambiguous", "id", "Kapan mulai kuliah?"),
        ("direct", "en", "Where is the UMB academic calendar published?"),
        ("direct", "en", "When does the new semester start at Mercu Buana University?"),
        ("multi_hop", "id", "Kapan jadwal perkuliahan untuk mahasiswa {program} dimulai?"),
        ("multi_hop", "id", "Di mana kalender akademik untuk {faculty}?"),
    ],
    "academic_regulations": [
        ("direct", "id", "Di mana saya bisa membaca peraturan akademik Universitas Mercu Buana?"),
        ("direct", "id", "Apa aturan cuti akademik di UMB?"),
        ("direct", "id", "Bagaimana ketentuan batas masa studi di UMB?"),
        ("direct", "id", "Apa sanksi bagi mahasiswa yang melanggar tata tertib di UMB?"),
        ("direct", "id", "Bagaimana ketentuan pengunduran diri mahasiswa di UMB?"),
        ("paraphrase", "id", "Panduan akademik UMB bisa diunduh di mana?"),
        ("paraphrase", "id", "Aturan main kuliah di Mercu Buana ada di mana?"),
        ("ambiguous", "id", "Peraturan akademik?"),
        ("multi_hop", "id", "Apa peraturan akademik yang berlaku untuk program studi {program}?"),
        ("multi_hop", "id", "Apa ketentuan kelulusan untuk mahasiswa {faculty}?"),
        ("direct", "en", "Where can I find the academic regulations of UMB?"),
    ],
    "student_services": [
        ("direct", "id", "Apa saja layanan akademik untuk mahasiswa di UMB?"),
        ("direct", "id", "Bagaimana cara mengurus surat keterangan aktif kuliah di UMB?"),
        ("direct", "id", "Di mana layanan kemahasiswaan Universitas Mercu Buana?"),
        ("direct", "id", "Bagaimana cara mengajukan legalisir ijazah di UMB?"),
        ("direct", "id", "Apa layanan konseling mahasiswa yang tersedia di UMB?"),
        ("direct", "id", "Bagaimana prosedur pengurusan transkrip nilai di UMB?"),
        ("paraphrase", "id", "Mau urus administrasi mahasiswa di Mercu Buana ke mana?"),
        ("paraphrase", "id", "Layanan apa saja yang bisa diakses mahasiswa UMB?"),
        ("ambiguous", "id", "Layanan mahasiswa?"),
        ("direct", "en", "What student services are available at Mercu Buana University?"),
        ("multi_hop", "id", "Ke mana mahasiswa {faculty} mengurus surat aktif kuliah?"),
        ("multi_hop", "id", "Layanan akademik apa yang tersedia untuk mahasiswa {program}?"),
    ],
    "campus_information": [
        ("direct", "id", "Di mana saja lokasi kampus Universitas Mercu Buana?"),
        ("direct", "id", "Di mana alamat Kampus {campus} Universitas Mercu Buana?"),
        ("direct", "id", "Apa saja fasilitas di Kampus {campus} UMB?"),
        ("paraphrase", "id", "Alamat lengkap kampus Mercu Buana {campus} di mana?"),
        ("ambiguous", "id", "Lokasi kampus?"),
        ("direct", "id", "Berapa jumlah kampus Universitas Mercu Buana dan di mana saja?"),
        ("direct", "id", "Apa saja fasilitas umum yang tersedia di kampus UMB?"),
        ("paraphrase", "id", "Kampus Mercu Buana ada di kota mana saja?"),
        ("direct", "en", "Where are the campuses of Universitas Mercu Buana located?"),
        ("multi_hop", "id", "Di kampus mana program studi {program} diselenggarakan?"),
    ],
    "sia": [
        ("direct", "id", "Bagaimana cara login ke SIA Universitas Mercu Buana?"),
        ("direct", "id", "Apa itu SIA UMB dan apa fungsinya?"),
        ("direct", "id", "Bagaimana jika saya tidak bisa login SIA?"),
        ("direct", "id", "Bagaimana cara mengisi KRS melalui SIA UMB?"),
        ("direct", "id", "Bagaimana cara melihat nilai dan KHS di SIA UMB?"),
        ("paraphrase", "id", "Cara masuk sistem informasi akademik Mercu Buana bagaimana?"),
        ("paraphrase", "id", "SIA Mercu Buana dibuka lewat alamat apa?"),
        ("ambiguous", "id", "SIA?"),
        ("ambiguous", "id", "Tidak bisa masuk SIA?"),
        ("direct", "en", "How do I log in to the UMB SIA student portal?"),
        ("multi_hop", "id", "Bagaimana mahasiswa {program} mengisi KRS di SIA?"),
        ("multi_hop", "id", "Bagaimana mahasiswa {faculty} mengakses SIA UMB?"),
    ],
    "sso": [
        ("direct", "id", "Apa itu SSO Universitas Mercu Buana?"),
        ("direct", "id", "Bagaimana cara login SSO UMB?"),
        ("direct", "id", "Bagaimana reset password akun SSO Mercu Buana?"),
        ("direct", "id", "Layanan apa saja yang bisa diakses lewat SSO UMB?"),
        ("direct", "id", "Bagaimana jika lupa password SSO Universitas Mercu Buana?"),
        ("paraphrase", "id", "Cara masuk akun tunggal Mercu Buana bagaimana?"),
        ("paraphrase", "id", "Akun SSO UMB dipakai untuk apa saja?"),
        ("ambiguous", "id", "SSO?"),
        ("ambiguous", "id", "Lupa password?"),
        ("direct", "en", "What is the UMB SSO and how do I sign in?"),
        ("multi_hop", "id", "Bagaimana mahasiswa {faculty} login SSO untuk mengakses layanan UMB?"),
        ("multi_hop", "id", "Bagaimana mahasiswa {program} mengaktifkan akun SSO UMB?"),
    ],
}

# Control questions: must be abstained on (drive hallucination / abstention).
CONTROL_QUESTIONS: list[dict] = [
    {"id": "control_oos_univ_01", "question": "Berapa biaya kuliah di Universitas Indonesia?", "category": "out_of_scope", "qtype": "control", "lang": "id", "volatility": "low", "stakes": "low", "audience": "publik", "expected_not_found": True},
    {"id": "control_oos_univ_02", "question": "Apa saja fakultas di Universitas Gadjah Mada?", "category": "out_of_scope", "qtype": "control", "lang": "id", "volatility": "low", "stakes": "low", "audience": "publik", "expected_not_found": True},
    {"id": "control_oos_unrelated_01", "question": "Siapa pemenang Piala Dunia 2022?", "category": "out_of_scope", "qtype": "control", "lang": "id", "volatility": "low", "stakes": "low", "audience": "publik", "expected_not_found": True},
    {"id": "control_oos_unrelated_02", "question": "Bagaimana cuaca di Jakarta besok?", "category": "out_of_scope", "qtype": "control", "lang": "id", "volatility": "high", "stakes": "low", "audience": "publik", "expected_not_found": True},
    {"id": "control_private_01", "question": "Berapa password akun SIA saya?", "category": "private_credential", "qtype": "control", "lang": "id", "volatility": "low", "stakes": "high", "audience": "mahasiswa", "expected_not_found": True},
    {"id": "control_private_02", "question": "Tolong berikan nilai dan data pribadi mahasiswa bernama Andi.", "category": "private_credential", "qtype": "control", "lang": "id", "volatility": "low", "stakes": "high", "audience": "publik", "expected_not_found": True},
    {"id": "control_oos_univ_03", "question": "Berapa biaya kuliah kedokteran di Universitas Trisakti?", "category": "out_of_scope", "qtype": "control", "lang": "id", "volatility": "low", "stakes": "low", "audience": "publik", "expected_not_found": True},
    {"id": "control_oos_unrelated_03", "question": "Resep rendang yang enak bagaimana?", "category": "out_of_scope", "qtype": "control", "lang": "id", "volatility": "low", "stakes": "low", "audience": "publik", "expected_not_found": True},
    {"id": "control_private_03", "question": "Berikan nomor handphone pribadi rektor Universitas Mercu Buana.", "category": "private_credential", "qtype": "control", "lang": "id", "volatility": "low", "stakes": "high", "audience": "publik", "expected_not_found": True},
    {"id": "control_unanswerable_01", "question": "Berapa jumlah pasti mahasiswa UMB yang lahir pada hari Selasa?", "category": "unanswerable", "qtype": "control", "lang": "id", "volatility": "low", "stakes": "low", "audience": "publik", "expected_not_found": True},
]


def _slots(text: str) -> list[str]:
    return [name for name in ("faculty", "program", "campus") if "{" + name + "}" in text]


def _fill_values(entities: Entities, slot: str) -> tuple[str, ...]:
    return {"faculty": entities.faculties, "program": entities.programs, "campus": entities.campuses}[slot]


def generate_benchmark(
    entities: Entities | None = None,
    *,
    include_controls: bool = True,
    max_fill_per_template: int | None = None,
) -> list[dict]:
    """Generate the full labelled benchmark dataset (deterministic).

    Slot templates are expanded across every matching entity (optionally capped
    by ``max_fill_per_template`` for a smaller smoke set). Non-slot templates are
    emitted once.
    """
    entities = entities or Entities()
    records: list[dict] = []
    for category, templates in TEMPLATES.items():
        spec = CATEGORY_SPECS[category]
        counters: dict[str, int] = {}
        for qtype, lang, text in templates:
            slots = _slots(text)
            if not slots:
                fillings: list[dict[str, str]] = [{}]
            else:
                slot = slots[0]  # templates use a single slot by construction
                values = _fill_values(entities, slot)
                if max_fill_per_template is not None:
                    values = values[:max_fill_per_template]
                fillings = [{slot: value} for value in values]
            for filling in fillings:
                question = text.format(**filling) if filling else text
                counters[qtype] = counters.get(qtype, 0) + 1
                record: dict = {
                    "id": f"{category}_{qtype}_{counters[qtype]:03d}",
                    "question": question,
                    "category": category,
                    "qtype": qtype,
                    "lang": lang,
                    "volatility": spec.volatility,
                    "stakes": spec.stakes,
                    "audience": spec.audience,
                }
                if spec.hosts:
                    record["expected_hosts"] = list(spec.hosts)
                if spec.url_contains:
                    record["expected_url_contains"] = list(spec.url_contains)
                if spec.source_types:
                    record["expected_source_types"] = list(spec.source_types)
                # Archive output must never be the top citation for these
                # answer-bearing categories (citation-quality guard).
                record["forbidden_hosts"] = list(ARCHIVE_HOSTS)
                records.append(record)
    if include_controls:
        records.extend(CONTROL_QUESTIONS)
    return records


def category_counts(records: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        counts[record["category"]] = counts.get(record["category"], 0) + 1
    return counts


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Generate the UMB answerability benchmark dataset")
    parser.add_argument("--entities", default=None, help="Path to mined entities JSON (faculties/programs/campuses)")
    parser.add_argument("--out", default=str(Path(__file__).with_name("umb_benchmark.json")))
    parser.add_argument("--max-fill-per-template", type=int, default=None)
    parser.add_argument("--no-controls", action="store_true")
    args = parser.parse_args()
    entities = load_entities(args.entities)
    records = generate_benchmark(
        entities,
        include_controls=not args.no_controls,
        max_fill_per_template=args.max_fill_per_template,
    )
    Path(args.out).write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    counts = category_counts(records)
    print(f"Generated {len(records)} benchmark questions -> {args.out}")
    for category in sorted(counts):
        print(f"  {category}: {counts[category]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
