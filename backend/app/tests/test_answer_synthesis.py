"""Tests for Batch 3 — answer synthesis (canonical-FAQ direct path + prompt)."""

from __future__ import annotations

from app.rag.answer_generator import _structured_faq_payload, generate_answer
from app.rag.prompts import SYSTEM_PROMPT


def _faq_ctx(score=14.0, demoted=False):
    return {
        "source_type": "faq",
        "score": score,
        "intent_demoted": demoted,
        "chunk_text": "Pendaftaran mahasiswa baru UMB dilakukan online melalui portal PMB di "
        "https://pendaftaran.mercubuana.ac.id/. Calon mahasiswa membuat akun lalu mengisi formulir.",
        "url": "https://pendaftaran.mercubuana.ac.id/",
        "hostname": "pendaftaran.mercubuana.ac.id",
        "title": "Bagaimana cara mendaftar mahasiswa baru di UMB?",
    }


def test_faq_direct_returns_complete_answer():
    payload = _structured_faq_payload(contexts=[_faq_ctx()], memory_used=False)
    assert payload is not None
    assert payload["not_found"] is False
    assert payload["confidence"] == "high"
    assert payload["provider_used"] == "system"
    assert payload["model_used"] == "canonical-faq"
    assert "[1]" in payload["answer"]
    assert payload["sources"] and payload["sources"][0]["url"] == "https://pendaftaran.mercubuana.ac.id/"


def test_faq_direct_skips_low_score():
    # a weak FAQ (below the strong-match threshold) is not short-circuited
    assert _structured_faq_payload(contexts=[_faq_ctx(score=9.0)], memory_used=False) is None


def test_faq_direct_skips_demoted_faq():
    assert _structured_faq_payload(contexts=[_faq_ctx(demoted=True)], memory_used=False) is None


def test_faq_direct_skips_non_faq_top():
    chunk = {"source_type": "html", "score": 14.0, "chunk_text": "x", "url": "https://x", "hostname": "x"}
    assert _structured_faq_payload(contexts=[chunk], memory_used=False) is None


def test_generate_answer_uses_faq_direct_without_llm():
    # With a strong FAQ at rank-1, generate_answer must return the curated answer
    # via the system path (no provider/LLM call needed).
    result = generate_answer(question="Bagaimana cara daftar mahasiswa baru?", contexts=[_faq_ctx()])
    assert result["not_found"] is False
    assert result["provider_used"] == "system"
    assert result["model_used"] == "canonical-faq"


def test_system_prompt_has_synthesis_directive():
    # the "knowledge assistant not search engine" directive is present
    assert "ASISTEN PENGETAHUAN" in SYSTEM_PROMPT
    assert "snippet" in SYSTEM_PROMPT.lower()
