from app.verification.xlec import is_cross_lingual, xlec_penalty

_EN = "What is the tuition fee for this study program and when is the payment deadline"
_ID = "Biaya kuliah program studi ini adalah lima ratus ribu rupiah dan harus dibayar"


def test_cross_lingual_true_for_en_claim_id_chunk():
    assert is_cross_lingual(_EN, _ID) is True


def test_cross_lingual_false_for_same_language():
    assert is_cross_lingual(_ID, _ID) is False


def test_xlec_penalty_applied_only_for_cross_lingual_claims():
    assert xlec_penalty(_EN, _ID) > 0
    assert xlec_penalty(_ID, _ID) == 0.0
