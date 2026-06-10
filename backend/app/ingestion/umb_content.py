from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from app.discovery.url_normalizer import normalize_url
from app.multimodal.source_classifier import classify_source


AUTH_PATH_MARKERS = (
    "/login",
    "/logout",
    "/signin",
    "/sign-in",
    "/register",
    "/forgot-password",
    "/reset-password",
    "/user/register",
    "/admin",
    "/administrator",
    "/wp-admin",
    "/dashboard",
    "/gate.php/login",
)

HIGH_PRIORITY_PAGE_TYPES = {
    "admissions",
    "academic",
    "academic_calendar",
    "campus_location",
    "faculty",
    "faculty_structure",
    "k3_report",
    "tuition",
    "university_profile",
}

_CTA_LINES = {
    "daftar sekarang",
    "daftar sekarang juga",
    "pendaftaran mahasiswa baru",
    "klik di sini untuk mendaftar",
    "register now",
}
_CHROME_LINES = {
    "skip to content",
    "back to top",
    "powered by google translate",
    "select language",
}


@dataclass(frozen=True)
class UMBURLClassification:
    content_type: str
    media_type: str
    page_type: str
    priority: int
    auth_or_system: bool


def canonicalize_umb_url(url: str, root_domain: str = "mercubuana.ac.id") -> str:
    normalized = normalize_url(url)
    parsed = urlparse(normalized)
    hostname = (parsed.hostname or "").lower()
    if hostname == f"www.{root_domain}":
        hostname = root_domain
    netloc = hostname
    if parsed.port and parsed.port not in {80, 443}:
        netloc = f"{hostname}:{parsed.port}"
    return urlunparse(("https", netloc, parsed.path or "/", "", parsed.query, ""))


def is_auth_or_system_url(url: str, title: str | None = None, description: str | None = None) -> bool:
    parsed = urlparse(url)
    path = (parsed.path or "/").lower()
    combined = " ".join((title or "", description or "")).lower()
    if any(marker in path for marker in AUTH_PATH_MARKERS):
        return True
    if re.search(r"\b(login|log in|sign in|register|forgot password|kata sandi|masuk)\b", combined):
        return True
    return False


def classify_umb_url(
    url: str,
    *,
    title: str | None = None,
    description: str | None = None,
    content_type: str | None = None,
) -> UMBURLClassification:
    source = classify_source(url, content_type)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "/").lower()
    text = " ".join((host, path, title or "", description or "")).lower()
    auth_or_system = is_auth_or_system_url(url, title, description)

    detected_content_type = source.source_type
    if detected_content_type == "unknown":
        detected_content_type = "html"
    if detected_content_type in {"pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "csv"}:
        media_type = "document"
    elif detected_content_type in {"image", "video", "audio"}:
        media_type = detected_content_type
    elif detected_content_type == "transcript":
        media_type = "transcript"
    else:
        media_type = "webpage"

    if auth_or_system:
        page_type = "auth_or_system"
    elif any(term in text for term in ("k3lk", "keselamatan dan kesehatan kerja", "/k3", "laporan-k3")):
        page_type = "k3_report"
    elif any(term in text for term in ("lokasi-kampus", "kampus meruya", "kampus menteng", "warung buncit")):
        page_type = "campus_location"
    elif any(term in text for term in ("rincian-pembayaran", "biaya-kuliah", "tuition", "uang kuliah")):
        page_type = "tuition"
    elif any(term in text for term in ("kalender-akademik", "academic-calendar", "jadwal akademik")):
        page_type = "academic_calendar"
    elif any(term in text for term in ("struktur-organisasi-dekanat", "struktural-dan-dosen", "dekan", "kaprodi")):
        page_type = "faculty_structure"
    elif "fasilkom." in host or any(term in text for term in ("fakultas-ilmu-komputer", "fasilkom", "/fakultas-")):
        page_type = "faculty"
    elif "pendaftaran." in host or any(
        term in text for term in ("pendaftaran", "pmb", "mahasiswa-baru", "kelas-internasional", "kelas-reguler")
    ):
        page_type = "admissions"
    elif "lib." in host or "digilib." in host or any(term in text for term in ("perpustakaan", "/library")):
        page_type = "library"
    elif "repository." in host or "/repository" in text:
        page_type = "repository"
    elif any(marker in host for marker in ("publikasi.", "proceeding.", "ecobiz.")) or "/article/" in path:
        page_type = "journal"
    elif "baa." in host or any(term in text for term in ("akademik", "biro pembelajaran", "/baa")):
        page_type = "academic"
    elif any(term in text for term in ("profil-universitas", "tentang-umb", "sejarah", "visi-misi", "rektor")):
        page_type = "university_profile"
    elif any(term in text for term in ("berita", "kabar-kampus", "news", "event")):
        page_type = "news"
    elif any(term in text for term in ("pengumuman", "announcement")):
        page_type = "announcement"
    elif any(term in text for term in ("hubungi-kami", "contact", "kontak")):
        page_type = "contact"
    elif any(term in text for term in ("biro-", "lembaga-", "unit-", "satgas", "direktorat")):
        page_type = "university_unit"
    elif media_type != "webpage":
        page_type = "official_document"
    else:
        page_type = "general"

    priority = 100 if page_type in HIGH_PRIORITY_PAGE_TYPES else 70
    if page_type in {"repository", "journal", "library", "news", "announcement", "university_unit"}:
        priority = 60
    if media_type == "document":
        priority += 5
    if page_type == "auth_or_system":
        priority = 0
    return UMBURLClassification(
        content_type=detected_content_type,
        media_type=media_type,
        page_type=page_type,
        priority=priority,
        auth_or_system=auth_or_system,
    )


def clean_umb_content(text: str) -> str:
    """Remove known UMB chrome/CTA noise without stripping useful body copy."""

    lines = []
    previous = None
    for raw_line in (text or "").replace("\r\n", "\n").splitlines():
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        plain = re.sub(r"[*_`#>\[\](){}|]", " ", line)
        plain = re.sub(r"\s+", " ", plain).strip(" :-").lower()
        if plain in _CTA_LINES or plain in _CHROME_LINES:
            continue
        if plain.startswith("select language"):
            continue
        if re.search(r"\bdaftar sekarang\b", plain) and len(plain) < 90:
            continue
        fingerprint = plain
        if fingerprint == previous:
            continue
        previous = fingerprint
        lines.append(line)
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def filename_title(url: str) -> str:
    name = Path(urlparse(url).path).name
    return name.replace("-", " ").replace("_", " ").strip() or url
