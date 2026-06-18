from __future__ import annotations

import re

from app.llm.base import ProviderConfigurationError
from app.llm.provider_factory import get_provider


STOPWORDS = {
    "bagaimana", "cara", "apa", "itu", "yang", "dan", "di", "ke", "dari", "untuk",
    "dengan", "the", "is", "are", "how", "what",
    # leading question words / fillers — drop so titles read as the topic, e.g.
    # "Siapa dekan FEB?" -> "Dekan FEB", "Berapa biaya kuliah?" -> "Biaya Kuliah".
    "siapa", "kapan", "berapa", "dimana", "mengapa", "kenapa", "adalah", "tolong",
    "mohon", "saya", "ingin", "tahu", "who", "when", "where", "why", "which", "a", "an",
}


def generate_title_from_question(question: str, max_words: int = 6) -> str:
    words = [word for word in re.findall(r"[\w\-]+", question or "", re.UNICODE) if word.lower() not in STOPWORDS]
    if not words:
        return "New Chat"
    # Title-case ordinary words but preserve acronyms (FEB, SIA, KRS, UTS, PMB, SSO).
    def _case(w: str) -> str:
        return w if (w.isupper() and len(w) <= 5) else w.capitalize()
    return " ".join(_case(w) for w in words[:max_words]).strip()


def generate_title_with_llm(question: str, provider_override: str | None = None, max_words: int = 6) -> str | None:
    """Best-effort title generation; deterministic title remains the fallback."""

    try:
        provider = get_provider(provider_override)
        response = provider.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Create a concise chat title from the user's first question. "
                        f"Return only the title, maximum {max_words} words, same language as the question. "
                        "Do not include citations or reasoning."
                    ),
                },
                {"role": "user", "content": question[:1200]},
            ],
            temperature=0.0,
        )
    except ProviderConfigurationError:
        return None
    except Exception:
        return None
    raw_title = re.sub(r"[\r\n\"`]+", " ", response.content or "").strip()
    words = re.findall(r"[\w\-]+", raw_title, re.UNICODE)[:max_words]
    if not words:
        return None
    return " ".join(words).strip()[:80]
