from app.verification.entailment import LexicalEntailmentChecker

PREMISE_FEE = "Biaya pendaftaran mahasiswa baru adalah Rp500.000 untuk gelombang pertama tahun ini."


def _c() -> LexicalEntailmentChecker:
    return LexicalEntailmentChecker()


def test_supported_claim_scores_high():
    assert _c().entails(premise=PREMISE_FEE, hypothesis="Biaya pendaftaran adalah Rp500.000") >= 0.5


def test_fabricated_number_scores_low():
    # right topic, wrong (made-up) figure -> must be dropped
    assert _c().entails(premise=PREMISE_FEE, hypothesis="Biaya pendaftaran adalah Rp2.000.000") < 0.5


def test_paraphrase_of_supported_fact_passes():
    premise = "SIA adalah sistem informasi akademik untuk melihat nilai dan KRS mahasiswa."
    assert _c().entails(premise=premise, hypothesis="Mahasiswa dapat melihat nilai melalui SIA") >= 0.5


def test_fabricated_procedure_on_irrelevant_premise_scores_low():
    # the SIA-password hallucination: a plausible procedure cited to an unrelated SIA page
    premise = "Daftar pengalaman mahasiswa pada sistem akademik SIA."
    hyp = "Untuk mengubah password SIA buka menu profil lalu klik ganti kata sandi dan masukkan email verifikasi."
    assert _c().entails(premise=premise, hypothesis=hyp) < 0.5


def test_empty_premise_scores_zero():
    assert _c().entails(premise="", hypothesis="apa saja") == 0.0
