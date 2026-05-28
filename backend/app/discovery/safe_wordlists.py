from __future__ import annotations

from pathlib import Path

from app.discovery.scope_validator import SENSITIVE_PATH_KEYWORDS


SAFE_PUBLIC_PATHS = [
    "berita",
    "artikel",
    "akademik",
    "fakultas",
    "program-studi",
    "pendaftaran",
    "biaya",
    "beasiswa",
    "pengumuman",
    "kontak",
    "layanan",
    "perpustakaan",
    "repository",
    "kemahasiswaan",
    "kalender-akademik",
    "kurikulum",
    "dosen",
    "penelitian",
    "publikasi",
    "event",
    "news",
    "about",
    "contact",
    "admission",
    "scholarship",
    "faculty",
    "study-program",
    "campus",
    "location",
]


def validate_safe_wordlist(paths: list[str] = SAFE_PUBLIC_PATHS) -> bool:
    lowered = {path.lower().strip("/") for path in paths}
    return not any(keyword in lowered for keyword in SENSITIVE_PATH_KEYWORDS)


def write_safe_wordlist(path: str | Path) -> None:
    if not validate_safe_wordlist():
        raise ValueError("Safe wordlist contains sensitive/private paths.")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(SAFE_PUBLIC_PATHS) + "\n", encoding="utf-8")

