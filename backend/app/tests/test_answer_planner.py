"""v3 P3 — answer-type planner tests."""

from __future__ import annotations

import pytest

from app.rag.answer_planner import (
    ANSWER_EXPLANATION,
    ANSWER_FACTUAL,
    ANSWER_LIST,
    ANSWER_PROCEDURE,
    answer_format_hint,
    plan_answer_type,
)


@pytest.mark.parametrize(
    "q,expected",
    [
        ("Bagaimana cara mendaftar mahasiswa baru?", ANSWER_PROCEDURE),
        ("cara login sia", ANSWER_PROCEDURE),
        ("Bagaimana cara reset password SSO?", ANSWER_PROCEDURE),
        ("Apa saja beasiswa yang tersedia di UMB?", ANSWER_LIST),
        ("Sebutkan program studi di Fakultas Teknik", ANSWER_LIST),
        ("Siapa dekan Fakultas Ilmu Komputer?", ANSWER_FACTUAL),
        ("Di mana lokasi kampus Meruya?", ANSWER_FACTUAL),
        ("Berapa biaya kuliah Informatika?", ANSWER_FACTUAL),
        ("Apa itu Tracer Study UMB?", ANSWER_EXPLANATION),
    ],
)
def test_plan_answer_type(q, expected):
    assert plan_answer_type(q) == expected


def test_plan_answer_type_empty():
    assert plan_answer_type("") == ANSWER_EXPLANATION


def test_format_hint_language_and_shape():
    assert "langkah" in answer_format_hint(ANSWER_PROCEDURE).lower()
    assert "steps" in answer_format_hint(ANSWER_PROCEDURE, "en").lower()
    assert "daftar" in answer_format_hint(ANSWER_LIST).lower() or "poin" in answer_format_hint(ANSWER_LIST).lower()
    assert answer_format_hint(ANSWER_FACTUAL)  # non-empty
    assert answer_format_hint(ANSWER_EXPLANATION)


def test_generation_prompt_includes_format_hint():
    from app.rag.answer_generator import build_generation_messages

    ctx = [{"url": "https://pendaftaran.mercubuana.ac.id/", "hostname": "pendaftaran.mercubuana.ac.id",
            "chunk_text": "Pendaftaran online.", "title": "PMB", "source_type": "html"}]
    messages, _ = build_generation_messages(question="Bagaimana cara mendaftar?", contexts=ctx)
    user = messages[-1]["content"]
    assert "Bentuk jawaban yang diharapkan" in user
    assert "langkah" in user.lower()  # procedure hint injected
