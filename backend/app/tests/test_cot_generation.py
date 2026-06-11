"""Chain-of-Thought generation: the model reasons in a <think> block before emitting
JSON, which improves grounding for weak local models (qwen2.5) without ever leaking the
reasoning into the answer or breaking JSON parsing."""

import app.rag.answer_generator as ag
from app.core.output_filter import sanitize_answer
from app.rag.answer_generator import finalize_generated_answer
from app.rag.prompts import SYSTEM_PROMPT

_CONTEXTS = [
    {
        "url": "https://pendaftaran.mercubuana.ac.id/cara-pendaftaran",
        "title": "Cara Pendaftaran - Universitas Mercu Buana",
        "hostname": "pendaftaran.mercubuana.ac.id",
        "chunk_text": "Cara pendaftaran mahasiswa baru: daftar online melalui PMB, pilih program studi, lalu bayar biaya pendaftaran.",
        "source_type": "html",
    }
]


def test_finalize_strips_think_block(monkeypatch):
    monkeypatch.setattr(ag, "_cgcv_enabled", lambda: False)
    content = (
        "<think>User asks how to register as a new student. Context [1] explains the "
        "online PMB flow. I will synthesize the steps.</think>\n"
        '{"answer":"Pendaftaran mahasiswa baru dilakukan secara online melalui PMB, '
        'pilih program studi, lalu bayar biaya pendaftaran [1].",'
        '"sources":[{"url":"https://pendaftaran.mercubuana.ac.id/cara-pendaftaran",'
        '"title":"Cara Pendaftaran","hostname":"pendaftaran.mercubuana.ac.id","source_type":"html"}],'
        '"confidence":"high","not_found":false}'
    )
    payload = finalize_generated_answer(
        content, _CONTEXTS, provider_used="local_ollama", model_used="qwen2.5:7b-instruct"
    )
    assert payload["not_found"] is False
    assert "Pendaftaran mahasiswa baru" in payload["answer"]
    assert "think" not in payload["answer"].lower()
    assert "User asks" not in payload["answer"]


def test_sanitize_strips_think_block():
    assert sanitize_answer("<think>internal reasoning</think>Jawaban resmi [1].").strip() == "Jawaban resmi [1]."
    # unclosed/garbled think tags must not leak either
    assert "reasoning" not in sanitize_answer("<reasoning>x y z</reasoning>Hasil [1].").lower()


def test_salvages_truncated_json_list_answer(monkeypatch):
    """A weak local model that exceeds the token budget mid-list must not collapse to
    the extractive dump — we recover the complete list items it did produce."""
    monkeypatch.setattr(ag, "_cgcv_enabled", lambda: False)
    # invalid JSON: the list is unterminated (truncated) and the object never closes
    content = (
        '{"answer": ["Daftar online melalui PMB UMB [1].", '
        '"Pilih program studi dan unggah dokumen [1].", '
        '"Bayar biaya pendaftaran lalu ikuti seleksi [1].", '
        '"Verifikasi email yang terdaft'
    )
    payload = finalize_generated_answer(
        content, _CONTEXTS, provider_used="local_ollama", model_used="qwen2.5:7b-instruct"
    )
    assert (payload.get("metadata") or {}).get("fallback") != "extractive"
    assert "Daftar online melalui PMB" in payload["answer"]
    assert "Bayar biaya pendaftaran" in payload["answer"]
    assert "memverifikasi" not in payload["answer"].lower()  # not the extractive lead
    # must be CLEAN prose, not raw JSON dumped to the user
    assert '"answer"' not in payload["answer"]
    assert not payload["answer"].lstrip().startswith("{")


def test_system_prompt_requests_cot_and_synthesis():
    assert "<think>" in SYSTEM_PROMPT
    low = SYSTEM_PROMPT.lower()
    assert "sintesis" in low or "menyintesis" in low
    # must steer away from cherry-picking tangential facts
    assert "sampingan" in low or "acak" in low or "langsung menjawab" in low
