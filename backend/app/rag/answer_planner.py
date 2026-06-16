"""
v3 P3 — answer-type planner.

Classifies the question into an answer shape and emits a concise formatting
instruction injected into the generation prompt, so the model produces a
*synthesized, structured* answer (steps / list / fact / explanation) instead of a
snippet dump. Deterministic; reuses the v3 intent router.

  FACTUAL     — who/where/how-much/when → a direct 1-2 sentence fact + citation.
  LIST        — "apa saja" / "daftar"   → a bulleted/numbered list, deduped.
  PROCEDURE   — "cara" / login / admission → numbered steps.
  EXPLANATION — "apa itu" / "jelaskan"  → a short cohesive explanation.
"""

from __future__ import annotations

import re

ANSWER_FACTUAL = "FACTUAL"
ANSWER_LIST = "LIST"
ANSWER_PROCEDURE = "PROCEDURE"
ANSWER_EXPLANATION = "EXPLANATION"

_PROCEDURE_INTENTS = {"admissions", "sia", "sso", "student_services"}
_LIST_INTENTS = {"scholarship", "study_program", "faculty"}


def plan_answer_type(question: str, intent: str | None = None) -> str:
    t = re.sub(r"\s+", " ", (question or "").strip().lower())
    if not t:
        return ANSWER_EXPLANATION
    from app.rag.intent_router import detect_intent

    intent = intent or detect_intent(question)

    def has(*terms: str) -> bool:
        return any(re.search(rf"(?<!\w){re.escape(x)}(?!\w)", t) for x in terms)

    # Procedure: how-to / steps / login / registration.
    if has("cara", "bagaimana cara", "langkah", "prosedur", "how do i", "how to", "steps", "reset", "lupa password", "isi krs", "mendaftar", "daftar") or intent in _PROCEDURE_INTENTS:
        return ANSWER_PROCEDURE
    # List: "what are all …", catalogues.
    if has("apa saja", "apa sajakah", "daftar", "list", "sebutkan", "what are", "which") or intent in _LIST_INTENTS:
        return ANSWER_LIST
    # Factual: who / where / how-much / when.
    if has("siapa", "who", "berapa", "kapan", "when", "di mana", "dimana", "where", "alamat", "how much"):
        return ANSWER_FACTUAL
    return ANSWER_EXPLANATION


def answer_format_hint(answer_type: str, language: str | None = None) -> str:
    en = (language or "").lower().startswith("en")
    if answer_type == ANSWER_PROCEDURE:
        return ("Format jawaban sebagai langkah bernomor yang jelas dan ringkas."
                if not en else "Format the answer as clear, concise numbered steps.")
    if answer_type == ANSWER_LIST:
        return ("Format jawaban sebagai daftar berpoin yang ringkas tanpa duplikasi."
                if not en else "Format the answer as a concise, de-duplicated bulleted list.")
    if answer_type == ANSWER_FACTUAL:
        return ("Jawab langsung dan padat (1-2 kalimat) dengan fakta yang diminta."
                if not en else "Answer directly and concisely (1-2 sentences) with the requested fact.")
    return ("Jawab dengan penjelasan ringkas yang menyatu (bukan potongan sumber)."
            if not en else "Answer with a short, cohesive explanation (not source snippets).")
