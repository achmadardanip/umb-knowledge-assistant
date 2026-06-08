from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

try:
    from dotenv import dotenv_values, load_dotenv

    for env_file in (Path.cwd() / ".env", Path.cwd().parent / ".env"):
        load_dotenv(env_file, override=True)
        if env_file.exists():
            for key, value in dotenv_values(env_file, encoding="utf-8-sig").items():
                if key and value is not None:
                    os.environ[key.lstrip("\ufeff")] = value
except Exception:
    pass


ProviderName = Literal["openrouter", "openai", "gemini", "anthropic", "hermes", "groq"]


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value)


def _float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return float(value)


def _provider(value: str | None) -> ProviderName:
    normalized = (value or "openrouter").strip().lower()
    if normalized not in {"openrouter", "openai", "gemini", "anthropic", "hermes", "groq"}:
        return "openrouter"
    return normalized  # type: ignore[return-value]


@dataclass(frozen=True)
class Settings:
    database_url: str | None = os.getenv("SUPABASE_POOLER_DATABASE_URL") or os.getenv("DATABASE_URL")
    local_sqlite_fallback_enabled: bool = _bool("LOCAL_SQLITE_FALLBACK_ENABLED", True)
    local_sqlite_path: str = os.getenv("LOCAL_SQLITE_PATH", "local-dev.db")

    ai_provider: ProviderName = _provider(os.getenv("AI_PROVIDER"))

    openrouter_api_key: str | None = os.getenv("OPENROUTER_API_KEY")
    openrouter_base_url: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "openai/gpt-oss-20b:free")

    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    openai_embedding_model: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")

    hermes_enabled: bool = _bool("HERMES_ENABLED", False)
    hermes_base_url: str = os.getenv("HERMES_BASE_URL", "http://127.0.0.1:8642/v1")
    hermes_api_key: str | None = os.getenv("HERMES_API_KEY")
    hermes_model: str = os.getenv("HERMES_MODEL", "hermes-agent")

    groq_api_key: str | None = os.getenv("GROQ_API_KEY")
    groq_base_url: str = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    groq_model: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    embedding_provider: str = os.getenv("EMBEDDING_PROVIDER", "openai").strip().lower()
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

    discovery_enabled: bool = _bool("DISCOVERY_ENABLED", True)
    discovery_domain: str = os.getenv("DISCOVERY_DOMAIN", "mercubuana.ac.id")
    discovery_max_depth: int = _int("DISCOVERY_MAX_DEPTH", 3)
    discovery_max_urls: int = _int("DISCOVERY_MAX_URLS", 2000)
    discovery_rate_limit: int = _int("DISCOVERY_RATE_LIMIT", 2)
    discovery_timeout_seconds: int = _int("DISCOVERY_TIMEOUT_SECONDS", 20)

    enable_sublist3r: bool = _bool("ENABLE_SUBLIST3R", True)
    enable_katana: bool = _bool("ENABLE_KATANA", True)
    enable_hakrawler: bool = _bool("ENABLE_HAKRAWLER", False)
    enable_gau: bool = _bool("ENABLE_GAU", True)
    enable_waybackurls: bool = _bool("ENABLE_WAYBACKURLS", True)
    enable_ffuf: bool = _bool("ENABLE_FFUF", False)
    enable_dirsearch: bool = _bool("ENABLE_DIRSEARCH", False)
    ffuf_rate_limit: int = _int("FFUF_RATE_LIMIT", 10)
    dirsearch_rate_limit: int = _int("DIRSEARCH_RATE_LIMIT", 10)
    safe_wordlist_path: str = os.getenv("SAFE_WORDLIST_PATH", "data/wordlists/safe_public_paths.txt")

    crawler_max_pages: int = _int("CRAWLER_MAX_PAGES", 500)
    crawler_max_depth: int = _int("CRAWLER_MAX_DEPTH", 3)
    crawler_timeout_seconds: int = _int("CRAWLER_TIMEOUT_SECONDS", 10)
    allowed_domain: str = os.getenv("ALLOWED_DOMAIN", "mercubuana.ac.id")
    chunk_size: int = _int("CHUNK_SIZE", 900)
    chunk_overlap: int = _int("CHUNK_OVERLAP", 120)
    index_target_sources: int = _int("INDEX_TARGET_SOURCES", 50000)
    crawler_rate_limit: float = _float("CRAWLER_RATE_LIMIT", 1.0)

    rag_top_k_default: int = _int("RAG_TOP_K_DEFAULT", 5)
    rag_top_k_max: int = _int("RAG_TOP_K_MAX", 8)
    chat_history_max_messages: int = _int("CHAT_HISTORY_MAX_MESSAGES", 5)
    rag_answer_cache_enabled: bool = _bool("RAG_ANSWER_CACHE_ENABLED", True)
    rag_answer_cache_ttl_seconds: int = _int("RAG_ANSWER_CACHE_TTL_SECONDS", 86400)
    llm_max_retries: int = _int("LLM_MAX_RETRIES", 2)
    llm_retry_backoff_seconds: float = _float("LLM_RETRY_BACKOFF_SECONDS", 2.0)
    llm_fallback_extractive: bool = _bool("LLM_FALLBACK_EXTRACTIVE", True)
    llm_fallback_providers: str = os.getenv("LLM_FALLBACK_PROVIDERS", "openai")

    # Corroboration-Gated Claim Verification (CGCV). Off by default until the
    # evaluation harness can measure its faithfulness/abstention impact; the
    # conformal layer (C²GV) will later set the threshold from a calibration set.
    cgcv_enabled: bool = _bool("CGCV_ENABLED", True)
    # 'lexical' = free offline entailment (no LLM call); 'llm' = provider judge.
    cgcv_entailment_mode: str = os.getenv("CGCV_ENTAILMENT_MODE", "lexical").strip().lower()
    cgcv_entailment_threshold: float = _float("CGCV_ENTAILMENT_THRESHOLD", 0.5)
    cgcv_min_supported_claims: int = _int("CGCV_MIN_SUPPORTED_CLAIMS", 1)

    # Safety floor (OWASP LLM10 / LLM01).
    rate_limit_enabled: bool = _bool("RATE_LIMIT_ENABLED", True)
    rate_limit_max_requests: int = _int("RATE_LIMIT_MAX_REQUESTS", 30)
    rate_limit_window_seconds: int = _int("RATE_LIMIT_WINDOW_SECONDS", 60)
    max_question_chars: int = _int("MAX_QUESTION_CHARS", 4000)

    # Trust-Aware Hybrid Fusion priors: S(d) = rel(d) + alpha*authority + beta*freshness.
    tahf_authority_weight: float = _float("TAHF_AUTHORITY_WEIGHT", 1.0)
    tahf_freshness_weight: float = _float("TAHF_FRESHNESS_WEIGHT", 0.5)
    # Dense semantic retrieval. Off until chunk embeddings are backfilled.
    dense_retrieval_enabled: bool = _bool("DENSE_RETRIEVAL_ENABLED", False)

    # Volatility-Aware Just-in-Time verification. Off (needs live web + cost budget).
    va_jit_enabled: bool = _bool("VA_JIT_ENABLED", False)
    va_jit_budget: int = _int("VA_JIT_BUDGET", 2)
    va_jit_volatility_threshold: float = _float("VA_JIT_VOLATILITY_THRESHOLD", 0.7)
    va_jit_freshness_threshold: float = _float("VA_JIT_FRESHNESS_THRESHOLD", 0.5)

    web_search_enabled: bool = _bool("WEB_SEARCH_ENABLED", False)
    web_search_provider: str = os.getenv("WEB_SEARCH_PROVIDER", "tavily").strip().lower()
    tavily_api_key: str | None = os.getenv("TAVILY_API_KEY")
    web_search_top_k: int = _int("WEB_SEARCH_TOP_K", 5)
    web_search_timeout_seconds: int = _int("WEB_SEARCH_TIMEOUT_SECONDS", 10)
    web_search_strict_domain: str = os.getenv("WEB_SEARCH_STRICT_DOMAIN", "mercubuana.ac.id")
    web_search_cache_answers: bool = _bool("WEB_SEARCH_CACHE_ANSWERS", False)
    # Persist live web-derived answer contexts into the KB so similar future
    # questions are served from the indexed KB (no second web round-trip / LLM call).
    web_kb_ingest_enabled: bool = _bool("WEB_KB_INGEST_ENABLED", True)

    # GraphRAG: entity co-occurrence graph over indexed chunks, used to expand
    # retrieval along entity relations (multi-hop). Built offline to JSON.
    graph_rag_enabled: bool = _bool("GRAPH_RAG_ENABLED", True)
    graph_path: str = os.getenv("GRAPH_PATH", "data/graph/umb_graph.json")
    graph_expansion_top_k: int = _int("GRAPH_EXPANSION_TOP_K", 3)

    agent_mode_enabled: bool = _bool("AGENT_MODE_ENABLED", True)
    agent_max_tool_iterations: int = _int("AGENT_MAX_TOOL_ITERATIONS", 3)
    llm_title_generation_enabled: bool = _bool("LLM_TITLE_GENERATION_ENABLED", False)

    multimodal_ingestion_enabled: bool = _bool("MULTIMODAL_INGESTION_ENABLED", True)
    max_pdf_size_mb: int = _int("MAX_PDF_SIZE_MB", 30)
    max_doc_size_mb: int = _int("MAX_DOC_SIZE_MB", 20)
    max_ppt_size_mb: int = _int("MAX_PPT_SIZE_MB", 50)
    max_spreadsheet_size_mb: int = _int("MAX_SPREADSHEET_SIZE_MB", 20)
    max_image_size_mb: int = _int("MAX_IMAGE_SIZE_MB", 10)
    max_audio_size_mb: int = _int("MAX_AUDIO_SIZE_MB", 50)
    max_video_size_mb: int = _int("MAX_VIDEO_SIZE_MB", 200)

    enable_ocr: bool = _bool("ENABLE_OCR", False)
    ocr_provider: str = os.getenv("OCR_PROVIDER", "tesseract")
    enable_asr: bool = _bool("ENABLE_ASR", False)
    asr_provider: str = os.getenv("ASR_PROVIDER", "faster-whisper")
    asr_model_size: str = os.getenv("ASR_MODEL_SIZE", "base")
    enable_video_download: bool = _bool("ENABLE_VIDEO_DOWNLOAD", False)
    enable_ytdlp_metadata: bool = _bool("ENABLE_YTDLP_METADATA", True)
    enable_table_extraction: bool = _bool("ENABLE_TABLE_EXTRACTION", True)
    multimodal_max_files_per_run: int = _int("MULTIMODAL_MAX_FILES_PER_RUN", 200)
    multimodal_min_extraction_chars: int = _int("MULTIMODAL_MIN_EXTRACTION_CHARS", 100)
    low_confidence_threshold: float = _float("LOW_CONFIDENCE_THRESHOLD", 0.5)

    memory_enabled: bool = _bool("MEMORY_ENABLED", True)
    memory_summary_interval: int = _int("MEMORY_SUMMARY_INTERVAL", 6)
    memory_max_items: int = _int("MEMORY_MAX_ITEMS", 20)

    project_root: Path = Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
