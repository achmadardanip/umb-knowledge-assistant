from app.core.output_filter import contains_prompt_leak, strip_prompt_leak
from app.rag.prompts import DATA_BEGIN


def test_detects_system_prompt_echo():
    assert contains_prompt_leak("Anda adalah UMB Knowledge Assistant. Jawab mengikuti bahasa...") is True


def test_detects_data_delimiter_leak():
    assert contains_prompt_leak(f"Berikut {DATA_BEGIN} isi sumber") is True


def test_clean_answer_is_not_flagged():
    assert contains_prompt_leak("Biaya pendaftaran adalah Rp500.000 [1].") is False


def test_strip_removes_leaked_lines_but_keeps_answer():
    answer = "Biaya pendaftaran adalah Rp500.000 [1].\nAnda adalah UMB Knowledge Assistant."
    cleaned = strip_prompt_leak(answer)
    assert "UMB Knowledge Assistant" not in cleaned
    assert "Rp500.000" in cleaned
