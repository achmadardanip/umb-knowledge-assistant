from __future__ import annotations

import json
import logging
import re
import time

from app.core.config import get_settings
from app.core.output_filter import sanitize_answer
from app.llm.base import ProviderConfigurationError
from app.llm.provider_factory import get_provider, normalize_provider
from app.rag.citation_validator import FALLBACK_ANSWER, validate_citations
from app.rag.language import language_instruction
from app.rag.prompts import SYSTEM_PROMPT, build_context_block
from app.verification.claim_gate import verify_claims
from app.verification.entailment import EntailmentChecker, LexicalEntailmentChecker, LLMJudgeEntailmentChecker


logger = logging.getLogger(__name__)


def fallback_payload(memory_used: bool = False, provider_used: str | None = None, model_used: str | None = None) -> dict:
    return {
        "answer": FALLBACK_ANSWER,
        "sources": [],
        "confidence": "low",
        "not_found": True,
        "provider_used": provider_used,
        "model_used": model_used,
        "memory_used": memory_used,
    }


def _build_sources(contexts: list[dict]) -> list[dict]:
    sources = []
    for index, context in enumerate(contexts, start=1):
        sources.append(
            {
                "citation_id": index,
                "title": context.get("title") or context.get("url"),
                "url": context.get("url"),
                "hostname": context.get("hostname"),
                "source_type": context.get("source_type"),
                "page_type": context.get("page_type"),
                "content_type": context.get("content_type"),
                "media_type": context.get("media_type"),
                "relevance_score": round(float(context.get("score", 0.0)), 4),
                "page_number": context.get("page_number"),
                "slide_number": context.get("slide_number"),
                "sheet_name": context.get("sheet_name"),
                "row_range": context.get("row_range"),
                "timestamp_start": context.get("timestamp_start"),
                "timestamp_end": context.get("timestamp_end"),
                "extraction_method": context.get("extraction_method"),
                "extraction_confidence": context.get("extraction_confidence"),
                "discovery_source": context.get("discovery_source"),
                "last_verified": context.get("last_verified"),
                "authority": context.get("authority"),
            }
        )
    return sources


def _context_source_key(context: dict) -> tuple:
    return (
        context.get("url"),
        context.get("page_number"),
        context.get("slide_number"),
        context.get("sheet_name"),
        context.get("row_range"),
        context.get("timestamp_start"),
        context.get("timestamp_end"),
    )


def _unique_contexts_by_source(contexts: list[dict]) -> list[dict]:
    seen = set()
    unique_contexts: list[dict] = []
    for context in contexts:
        key = _context_source_key(context)
        if key in seen:
            continue
        seen.add(key)
        unique_contexts.append(context)
    return unique_contexts


_FASILKOM_MARKERS = ("fasilkom", "fakultas ilmu komputer", "ilmu komputer")
_PROGRAM_QUERIES = ("program studi", "prodi", "jurusan", "programs", "degree programs", "majors")
_LECTURER_QUERIES = ("dosen", "pengajar", "lecturer", "lecturers")
_DEAN_QUERIES = ("dekan", "dean")
_FACULTY_REFERENCE_QUERIES = ("fakultas ini", "fakultas tersebut", "program studi ini", "prodi ini")
_GENERAL_FACULTY_QUERIES = (
    "faculties",
    "all faculty",
    "all faculties",
    "daftar fakultas",
    "fakultas apa saja",
    "semua fakultas",
)
_LOCATION_QUERIES = ("lokasi", "alamat", "kampus", "location", "locations", "located", "address", "campus")
_CAMPUS_NAMES = ("Meruya", "Menteng", "Pejaten", "Warung Buncit", "Jatisampurna", "Bekasi", "Keranggan")
_PROGRAM_PATTERNS = (
    (
        "Informatika",
        (
            r"\bInformatika\s*\(\s*Visi\s*:\s*Artificial Intelligence\s*\)",
            r"\bReguler\s+dan\s+Fleksibel\s+Informatika\b",
        ),
    ),
    ("Teknik Informatika", (r"\bTeknik Informatika\b",)),
    ("Sistem Informasi", (r"\bSistem Informasi\b",)),
    (
        "Informatika Program Belajar Jarak Jauh (PBJJ)",
        (
            r"\bInformatika\s+Program\s+Belajar\s+Jarak\s+Jauh\s*\(\s*PBJJ\s*\)",
            r"\bPBJJ\s+Informatika\b",
        ),
    ),
    ("Sains Data", (r"\bSains Data\b",)),
    ("Magister Ilmu Komputer", (r"\bMagister Ilmu Komputer\b",)),
    ("Doktor Ilmu Komputer", (r"\bDoktor Ilmu Komputer\b",)),
)
_ROLE_BOUNDARY_RE = re.compile(
    r"\b(wakil\s+dekan|ketua\s+program\s+studi|kaprodi|sekretaris|program\s+studi|dosen\s+tetap|pendidikan|nidn|jabatan)\b",
    flags=re.IGNORECASE,
)
_DEGREE_TOKEN = (
    r"(?:Prof\.?|Dr\.?|Ir\.?|S\.Kom|S\.T\.?|ST|M\.Kom|MMSI|M\.MSI|MTI|M\.TI|M\.T\.I|M\.T|"
    r"M\.Sc|Ph\.D|MM|M\.M|M\.Si|S\.Si|S\.E|SE|S\.H|M\.Hum|M\.Eng|IPM)"
)
_PERSON_WITH_DEGREES_RE = re.compile(
    rf"((?:[A-Z][A-Z.'-]*|[A-Z][a-zA-Z.'-]+)(?:\s+(?:[A-Z][A-Z.'-]*|[A-Z][a-zA-Z.'-]+)){{0,7}}\s*,\s*{_DEGREE_TOKEN}(?:\s*,\s*{_DEGREE_TOKEN})*)"
)


def _context_text(context: dict) -> str:
    return " ".join(
        str(value or "")
        for value in [context.get("title"), context.get("hostname"), context.get("url"), context.get("chunk_text")]
    )


def _is_fasilkom_text(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _FASILKOM_MARKERS)


def _fasilkom_contexts(contexts: list[dict]) -> list[dict]:
    focused = [context for context in contexts if _is_fasilkom_text(_context_text(context))]
    return focused or []


def _question_has(question: str, terms: tuple[str, ...]) -> bool:
    lowered = (question or "").lower()
    return any(term in lowered for term in terms)


def _clean_dean_candidate(raw: str) -> str | None:
    candidate = re.sub(r"\s+", " ", raw or "").strip(" :-–—|,;")
    candidate = re.sub(r"^(?:fakultas ilmu komputer|fasilkom|universitas mercu buana)\s+", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"^(?:dekan|dean)\s+", "", candidate, flags=re.IGNORECASE)
    boundary = _ROLE_BOUNDARY_RE.search(candidate)
    if boundary:
        candidate = candidate[: boundary.start()].strip(" :-–—|,;")
    candidate = re.sub(r"\s+", " ", candidate).strip(" :-–—|,;")
    if not candidate or len(candidate.split()) < 2:
        return None
    lowered = candidate.lower()
    if any(term in lowered for term in ("fakultas", "program studi", "dosen tetap", "universitas")):
        return None
    return candidate


def _extract_dean_name(contexts: list[dict]) -> str | None:
    for context in contexts:
        text = context.get("chunk_text") or ""
        lines = [line.strip() for line in re.split(r"[\r\n]+", text) if line.strip()]
        if not lines:
            lines = [text]
        for index, line in enumerate(lines):
            lowered = line.lower()
            if "dekan" not in lowered or "wakil dekan" in lowered:
                continue
            match = re.search(
                r"\bdekan(?:\s+fakultas\s+ilmu\s+komputer|\s+fasilkom)?\s*[:\-–—]?\s+(.{3,140})",
                line,
                flags=re.IGNORECASE,
            )
            if match:
                cleaned = _clean_dean_candidate(match.group(1))
                if cleaned:
                    return cleaned
            if index + 1 < len(lines):
                cleaned = _clean_dean_candidate(lines[index + 1])
                if cleaned:
                    return cleaned
    return None


def _clean_person_with_degrees(raw: str) -> str | None:
    candidate = re.sub(r"\s+", " ", raw or "").strip(" ,;")
    if "," not in candidate:
        return None
    name, degrees = candidate.split(",", 1)
    name = name.strip()
    lowered = name.lower()
    for marker in ("pendidikan", "dosen tetap fakultas ilmu komputer", "dosen tetap", "fakultas ilmu komputer", "nama dosen", "nama"):
        pos = lowered.rfind(marker)
        if pos != -1:
            name = name[pos + len(marker) :].strip()
            lowered = name.lower()
    if not name or any(term in lowered for term in ("fakultas", "program studi", "pendidikan", "dosen")):
        return None
    if len(name.split()) > 6:
        name = " ".join(name.split()[-4:])
    if name.isupper():
        name = name.title()
    normalized_degrees = re.sub(r"\s+", " ", degrees).strip(" ,;")
    if not normalized_degrees:
        return None
    return f"{name}, {normalized_degrees}"


def _extract_lecturer_names(contexts: list[dict], limit: int = 40) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for context in contexts:
        text = context.get("chunk_text") or ""
        dosen_start = text.lower().find("dosen tetap")
        if dosen_start != -1:
            text = text[dosen_start:]
        for match in _PERSON_WITH_DEGREES_RE.findall(text):
            cleaned = _clean_person_with_degrees(match)
            if not cleaned:
                continue
            key = re.sub(r"[^a-z0-9]+", "", cleaned.lower())
            if key in seen:
                continue
            seen.add(key)
            names.append(cleaned)
            if len(names) >= limit:
                return names
    return names


def _extract_programs(contexts: list[dict]) -> list[str]:
    found: list[str] = []
    combined = "\n".join(context.get("chunk_text") or "" for context in contexts)
    for program, patterns in _PROGRAM_PATTERNS:
        if any(re.search(pattern, combined, flags=re.IGNORECASE) for pattern in patterns):
            found.append(program)
    return found


def _extract_campus_locations(context: dict) -> list[tuple[str, str]]:
    text = re.sub(r"\s+", " ", context.get("chunk_text") or "").strip()
    if not text:
        return []
    names_pattern = "|".join(re.escape(name) for name in _CAMPUS_NAMES)
    matches = list(
        re.finditer(
            rf"\bKampus\s+({names_pattern})\b(.*?)(?=\bKampus\s+(?:{names_pattern})\b|$)",
            text,
            flags=re.IGNORECASE,
        )
    )
    locations: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in matches:
        name = match.group(1).title()
        address = re.sub(r"^\s*(?:Default Title\s*)?", "", match.group(2), flags=re.IGNORECASE).strip(" :-–—|,;")
        if not address or not re.search(r"\b(?:Jl\.?|Jalan)\b", address, flags=re.IGNORECASE):
            continue
        address = address[:300].rstrip(" ,;")
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        locations.append((name, address))
    return locations


def _structured_location_payload(
    *,
    question: str,
    contexts: list[dict],
    memory_used: bool,
    language: str | None = None,
) -> dict | None:
    if not _question_has(question, _LOCATION_QUERIES):
        return None
    for context in _unique_contexts_by_source(contexts):
        locations = _extract_campus_locations(context)
        if len(locations) < 2:
            continue
        rendered = "\n".join(f"{index}. **Kampus {name}**: {address}" for index, (name, address) in enumerate(locations, start=1))
        if (language or "").lower().startswith("en"):
            answer = f"The official UMB source lists these campus locations [1]:\n\n{rendered}"
        else:
            answer = f"Sumber resmi UMB mencantumkan lokasi kampus berikut [1]:\n\n{rendered}"
        payload = {
            "answer": answer,
            "sources": _build_sources([context]),
            "confidence": "high",
            "not_found": False,
            "provider_used": "system",
            "model_used": "structured-campus-location-extractor",
            "memory_used": memory_used,
        }
        validated = validate_citations(payload, [context], require_citation_markers=True)
        validated["answer"] = sanitize_answer(validated.get("answer") or "")
        return validated
    return None


def _structured_fasilkom_payload(
    *,
    question: str,
    contexts: list[dict],
    memory_used: bool,
    language: str | None = None,
) -> dict | None:
    focused_contexts = _unique_contexts_by_source(_fasilkom_contexts(contexts))[:3]
    explicit_fasilkom = _is_fasilkom_text(question)
    asks_general_faculties = _question_has(question, _GENERAL_FACULTY_QUERIES)
    asks_fasilkom_topic = explicit_fasilkom or (
        not asks_general_faculties
        and bool(focused_contexts)
        and (
            _question_has(question, _FACULTY_REFERENCE_QUERIES)
            or _question_has(question, _PROGRAM_QUERIES)
            or _question_has(question, _LECTURER_QUERIES)
            or _question_has(question, _DEAN_QUERIES)
        )
    )
    if not asks_fasilkom_topic:
        return None
    if not focused_contexts:
        return None

    title = focused_contexts[0].get("title") or "sumber resmi Fasilkom"
    answer: str | None = None
    if _question_has(question, _DEAN_QUERIES):
        dean_name = _extract_dean_name(focused_contexts)
        if dean_name:
            answer = f"Dekan Fakultas Ilmu Komputer/Fasilkom yang tercantum pada sumber resmi adalah **{dean_name}** [1]."
    elif _question_has(question, _LECTURER_QUERIES):
        names = _extract_lecturer_names(focused_contexts)
        if names:
            rendered = "\n".join(f"{index}. {name}" for index, name in enumerate(names, start=1))
            answer = f"Data berikut berasal dari halaman resmi **{title}** [1].\n\n{rendered}"
    elif _question_has(question, _PROGRAM_QUERIES):
        programs = _extract_programs(focused_contexts)
        if programs:
            rendered = "\n".join(f"{index}. {program}" for index, program in enumerate(programs, start=1))
            if (language or "").lower().startswith("en"):
                answer = f"According to the official source, the listed Faculty of Computer Science/Fasilkom programs are [1]:\n\n{rendered}"
            else:
                answer = f"Berdasarkan sumber resmi, program studi di Fakultas Ilmu Komputer/Fasilkom yang tercantum adalah [1]:\n\n{rendered}"

    if not answer:
        return None
    payload = {
        "answer": answer,
        "sources": _build_sources(focused_contexts),
        "confidence": "high",
        "not_found": False,
        "provider_used": "system",
        "model_used": "structured-fasilkom-extractor",
        "memory_used": memory_used,
    }
    validated = validate_citations(payload, focused_contexts, require_citation_markers=True)
    validated["answer"] = sanitize_answer(validated.get("answer") or "")
    return validated


def _structured_faculty_overview_payload(
    *,
    question: str,
    contexts: list[dict],
    memory_used: bool,
    language: str | None = None,
) -> dict | None:
    if not _question_has(question, _GENERAL_FACULTY_QUERIES):
        return None
    overview = next(
        (
            context
            for context in contexts
            if re.search(r"mercubuana\.ac\.id/(?:en/)?fakultas/?$", str(context.get("url") or ""), re.IGNORECASE)
        ),
        None,
    )
    if overview is None:
        return None
    faculty_names: list[str] = []
    seen: set[str] = set()
    for match in re.findall(r"\[(Fakultas [^\]]+)\]\(https?://[^)]+/fakultas[^)]*\)", overview.get("chunk_text") or ""):
        name = re.sub(r"\s+", " ", match).strip()
        key = name.lower()
        if key not in seen:
            seen.add(key)
            faculty_names.append(name)
    if len(faculty_names) < 3:
        return None

    rendered = "\n".join(f"{index}. {name}" for index, name in enumerate(faculty_names, start=1))
    if (language or "").lower().startswith("en"):
        answer = (
            "The official UMB faculty overview lists these faculties [1]:\n\n"
            f"{rendered}\n\n"
            "For the complete study-program catalog, open each faculty's official page linked from the overview; "
            "the overview itself summarizes program areas rather than one exhaustive program-by-program list."
        )
    else:
        answer = (
            "Halaman resmi fakultas UMB mencantumkan fakultas berikut [1]:\n\n"
            f"{rendered}\n\n"
            "Untuk daftar program studi yang lengkap, buka halaman resmi tiap fakultas yang ditautkan dari halaman "
            "tersebut; halaman overview merangkum bidang program, bukan satu katalog prodi lengkap."
        )
    payload = {
        "answer": answer,
        "sources": _build_sources([overview]),
        "confidence": "high",
        "not_found": False,
        "provider_used": "system",
        "model_used": "structured-faculty-overview-extractor",
        "memory_used": memory_used,
    }
    validated = validate_citations(payload, [overview], require_citation_markers=True)
    validated["answer"] = sanitize_answer(validated.get("answer") or "")
    return validated


def extractive_fallback_payload(
    *,
    contexts: list[dict],
    memory_used: bool = False,
    provider_used: str | None = None,
    model_used: str | None = None,
    reason: str | None = None,
    language: str | None = None,
) -> dict:
    fallback_contexts = _unique_contexts_by_source(contexts)[:5]
    sources = _build_sources(fallback_contexts)
    snippets = []
    for index, context in enumerate(fallback_contexts[:3], start=1):
        text = " ".join((context.get("chunk_text") or "").split())
        if not text:
            continue
        title = context.get("title") or context.get("hostname") or (
            "Official source" if (language or "").lower().startswith("en") else "Sumber resmi"
        )
        snippets.append(f"**{title}** — {text[:240].rstrip()}… [{index}]")
    answer = FALLBACK_ANSWER
    if snippets:
        is_english = (language or "").lower().startswith("en")
        if is_english and reason and "missing_valid_citations" in reason:
            lead = (
                "I could not verify a complete answer to this question from the indexed official sources, "
                "so I will not guess. These are the most relevant excerpts from official UMB sources:"
            )
        elif is_english:
            lead = (
                "Relevant official sources were found, but a complete answer could not be generated right now. "
                "These are the most relevant excerpts from official UMB sources:"
            )
        elif reason and "missing_valid_citations" in reason:
            lead = (
                "Saya belum dapat memverifikasi jawaban yang utuh untuk pertanyaan ini dari sumber resmi yang terindeks, "
                "jadi saya tidak menebak. Berikut kutipan paling relevan dari sumber resmi UMB:"
            )
        else:
            lead = (
                "Sumber resmi yang relevan ditemukan, namun jawaban lengkap belum dapat disusun saat ini. "
                "Berikut kutipan paling relevan dari sumber resmi UMB:"
            )
        answer = lead + "\n\n" + "\n\n".join(f"- {snippet}" for snippet in snippets)
    payload = {
        "answer": answer,
        "sources": sources,
        "confidence": "medium" if sources else "low",
        "not_found": not bool(sources),
        "provider_used": provider_used,
        "model_used": model_used,
        "memory_used": memory_used,
        "metadata": {"fallback": "extractive", "reason": reason},
    }
    sanitized = validate_citations(payload, contexts, require_citation_markers=bool(sources))
    sanitized["answer"] = sanitize_answer(sanitized.get("answer") or "")
    return sanitized


def _is_retryable_provider_error(exc: Exception) -> bool:
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    if status_code in {408, 429, 500, 502, 503, 504}:
        return True
    message = str(exc).lower()
    return any(marker in message for marker in ("429", "408", "500", "502", "503", "504", "timeout", "timed out"))


def _json_text(content: str) -> str:
    text = (content or "").strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    if text.startswith("{"):
        return text
    # Browser models sometimes wrap the JSON in prose; extract the outermost object.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


def _provider_candidates(provider_override: str | None) -> list[str | None]:
    settings = get_settings()
    selected = normalize_provider(provider_override)
    candidates: list[str | None] = [selected]
    if not settings.answer_enable_fallback:
        return candidates
    for raw_provider in settings.llm_fallback_providers.split(","):
        provider_name = raw_provider.strip().lower()
        if not provider_name:
            continue
        normalized = normalize_provider(provider_name)
        if normalized not in candidates:
            candidates.append(normalized)
    return candidates


def _chat_with_failover(messages: list[dict], provider_override: str | None, max_retries: int):
    settings = get_settings()
    last_error: Exception | None = None
    selected_provider = normalize_provider(provider_override)
    for candidate in _provider_candidates(provider_override):
        provider = get_provider(candidate)
        for attempt in range(max_retries + 1):
            try:
                return provider, provider.chat(messages), None
            except ProviderConfigurationError as exc:
                if provider.provider_name == selected_provider:
                    raise
                last_error = exc
                logger.warning("Fallback provider %s is not configured; skipping.", provider.provider_name)
                break
            except Exception as exc:
                last_error = exc
                retryable = _is_retryable_provider_error(exc)
                logger.warning(
                    "Provider %s call failed on attempt %s/%s: %s",
                    provider.provider_name,
                    attempt + 1,
                    max_retries + 1,
                    exc,
                )
                if attempt >= max_retries or not retryable:
                    break
                time.sleep(settings.llm_retry_backoff_seconds * (2**attempt))
        if provider.provider_name != selected_provider and last_error:
            logger.warning("Fallback provider %s failed; trying next fallback if available.", provider.provider_name)
    return None, None, last_error


def _cgcv_enabled() -> bool:
    return get_settings().cgcv_enabled


def build_default_entailment_checker(provider_override: str | None) -> EntailmentChecker:
    """Entailment engine for CGCV. Default 'lexical' is free (no LLM call) so the trust
    gate runs on every answer without burning rate-limited quota; 'llm' uses a provider
    judge. Swappable for MiniCheck/NLI via the model gateway later."""
    settings = get_settings()
    if settings.cgcv_entailment_mode == "lexical":
        return LexicalEntailmentChecker()

    def chat(messages: list[dict]) -> str:
        return get_provider(provider_override).chat(messages).content

    return LLMJudgeEntailmentChecker(chat=chat)


def _contexts_by_citation(sources: list[dict], contexts: list[dict]) -> dict[int, dict]:
    contexts_by_url = {context.get("url"): context for context in contexts if context.get("url")}
    mapping: dict[int, dict] = {}
    for source in sources:
        citation_id = source.get("citation_id")
        url = source.get("url")
        if citation_id is None or not url:
            continue
        context = contexts_by_url.get(url)
        if context and context.get("chunk_text"):
            mapping[int(citation_id)] = context
    return mapping


_CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


def _min_confidence(first: str | None, second: str | None) -> str:
    first = first or "medium"
    second = second or "medium"
    return first if _CONFIDENCE_ORDER.get(first, 1) <= _CONFIDENCE_ORDER.get(second, 1) else second


def _apply_cgcv(payload: dict, contexts: list[dict], provider_override: str | None) -> dict:
    """Verify each cited claim by entailment; drop unsupported claims, abstain if too few survive."""
    settings = get_settings()
    sources = payload.get("sources") or []
    checker = build_default_entailment_checker(provider_override)
    result = verify_claims(
        payload.get("answer") or "",
        _contexts_by_citation(sources, contexts),
        checker,
        threshold=settings.cgcv_entailment_threshold,
        min_supported=settings.cgcv_min_supported_claims,
    )
    if result.not_found:
        return {**payload, "answer": FALLBACK_ANSWER, "sources": [], "confidence": "low", "not_found": True}
    surviving_ids = {citation_id for claim in result.supported_claims for citation_id in claim.citation_ids}
    filtered_sources = [source for source in sources if int(source.get("citation_id") or 0) in surviving_ids] or sources
    return {
        **payload,
        "answer": result.answer,
        "sources": filtered_sources,
        "confidence": _min_confidence(payload.get("confidence"), result.confidence),
        "not_found": False,
    }


def build_generation_messages(
    *,
    question: str,
    contexts: list[dict],
    recent_messages: list[dict] | None = None,
    memories: list[dict] | None = None,
    language: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """Build the grounded LLM prompt. Returns (messages, truncated_contexts).

    Shared by the server-side providers and the browser (Puter.js) path so both
    answer from the *same* official-context-only prompt.
    """
    settings = get_settings()
    contexts = contexts[: max(1, settings.rag_top_k_max)]
    context_block = build_context_block(contexts)
    memory_block = "\n".join(memory.get("content", "") for memory in (memories or []))[:2000]
    conversation_block = "\n".join(
        f"{message.get('role')}: {message.get('content')}" for message in (recent_messages or [])[-settings.chat_history_max_messages :]
    )
    language_block = language_instruction(language)
    user_prompt = f"""Instruksi bahasa:
{language_block}

Pertanyaan:
{question}

Konteks resmi yang boleh digunakan:
{context_block}

Memori aman untuk kontinuitas, bukan sumber resmi:
{memory_block}

Percakapan terbaru:
{conversation_block}

Kembalikan JSON valid sesuai format yang diminta.
Gunakan hanya URL dari konteks resmi.
Setiap kalimat faktual penting pada field answer harus mencantumkan marker sitasi bernomor seperti [1] atau [2].
Nomor marker harus sesuai urutan sources yang Anda kembalikan.
Untuk daftar dari satu sumber yang sama, kelompokkan sitasi pada kalimat pengantar/penutup daftar agar jawaban tetap rapi.
Jangan sertakan chain-of-thought, thought/action/observation, reasoning trace, atau tag <think> pada field mana pun.
Tulis isi field answer dengan rapi memakai Markdown: gunakan poin atau penomoran untuk langkah/daftar, **tebalkan** istilah penting, dan susun jawaban yang ringkas serta mudah dibaca."""

    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_prompt}]
    return messages, contexts


def finalize_generated_answer(
    content: str,
    contexts: list[dict],
    *,
    provider_used: str | None,
    model_used: str | None,
    memory_used: bool = False,
    provider_override: str | None = None,
    language: str | None = None,
) -> dict:
    """Verify + clean a raw LLM answer (server-side trust gate).

    Runs the JSON parse, citation validation, CGCV claim gate, extractive fallback,
    and output sanitiser. Applied identically whether ``content`` came from a server
    provider or from a browser LLM (Puter.js), so the browser path is just as gated.
    """
    settings = get_settings()
    try:
        parsed_payload = json.loads(_json_text(content))
        payload = parsed_payload if isinstance(parsed_payload, dict) else {"answer": parsed_payload}
    except json.JSONDecodeError:
        payload = {
            "answer": (content or "").strip(),
            "sources": _build_sources(contexts[:3]),
            "confidence": "medium",
            "not_found": False,
        }
    raw_answer = payload.get("answer")
    if isinstance(raw_answer, list):
        payload["answer"] = "\n".join(
            f"- {item}" if isinstance(item, str) else f"- {json.dumps(item, ensure_ascii=False)}"
            for item in raw_answer
        )
    elif not isinstance(raw_answer, str):
        payload["answer"] = "" if raw_answer is None else json.dumps(raw_answer, ensure_ascii=False)
    if not isinstance(payload.get("sources"), list):
        payload["sources"] = []
    payload["provider_used"] = provider_used
    payload["model_used"] = model_used
    payload["memory_used"] = memory_used
    if not payload.get("sources"):
        payload["sources"] = _build_sources(contexts[:3])
    validated_payload = validate_citations(payload, contexts, require_citation_markers=True)
    if not validated_payload.get("not_found") and _cgcv_enabled():
        validated_payload = _apply_cgcv(validated_payload, contexts, provider_override)
    if validated_payload.get("not_found") and settings.llm_fallback_extractive:
        return extractive_fallback_payload(
            contexts=contexts,
            memory_used=memory_used,
            provider_used=provider_used,
            model_used=model_used,
            reason="provider_answer_missing_valid_citations",
            language=language,
        )
    validated_payload["answer"] = sanitize_answer(validated_payload.get("answer") or "")
    return validated_payload


def generate_answer(
    *,
    question: str,
    contexts: list[dict],
    recent_messages: list[dict] | None = None,
    memories: list[dict] | None = None,
    provider_override: str | None = None,
    language: str | None = None,
) -> dict:
    settings = get_settings()
    memory_used = bool(memories)
    if not contexts:
        return fallback_payload(memory_used=memory_used)

    structured_payload = _structured_location_payload(
        question=question,
        contexts=contexts,
        memory_used=memory_used,
        language=language,
    )
    if structured_payload:
        return structured_payload

    structured_payload = _structured_faculty_overview_payload(
        question=question,
        contexts=contexts,
        memory_used=memory_used,
        language=language,
    )
    if structured_payload:
        return structured_payload

    structured_payload = _structured_fasilkom_payload(
        question=question,
        contexts=contexts,
        memory_used=memory_used,
        language=language,
    )
    if structured_payload:
        return structured_payload

    messages, contexts = build_generation_messages(
        question=question,
        contexts=contexts,
        recent_messages=recent_messages,
        memories=memories,
        language=language,
    )
    max_retries = max(settings.llm_max_retries, 0)
    provider, response, last_error = _chat_with_failover(messages, provider_override, max_retries)

    if response is None:
        if settings.llm_fallback_extractive:
            return extractive_fallback_payload(
                contexts=contexts,
                memory_used=memory_used,
                provider_used=provider.provider_name if provider else normalize_provider(provider_override),
                model_used=provider.model if provider else None,
                reason=str(last_error) if last_error else "provider_unavailable",
                language=language,
            )
        if last_error:
            raise last_error
        raise RuntimeError("Provider returned no response.")

    return finalize_generated_answer(
        response.content,
        contexts,
        provider_used=response.provider_used,
        model_used=response.model_used,
        memory_used=memory_used,
        provider_override=provider_override,
        language=language,
    )
