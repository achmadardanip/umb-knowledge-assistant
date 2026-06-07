from app.verification.claims import Claim, extract_claims


def test_extract_claims_splits_sentences_and_parses_citation_ids():
    answer = "Biaya pendaftaran adalah Rp500.000 [1]. Pendaftaran dibuka setiap semester [2]."
    claims = extract_claims(answer)
    assert len(claims) == 2
    assert claims[0].citation_ids == (1,)
    assert "Rp500.000" in claims[0].text
    assert "[1]" not in claims[0].text
    assert claims[1].citation_ids == (2,)


def test_extract_claims_handles_multiple_and_missing_markers():
    answer = "Program tersedia di kampus A dan B [1][2]. Kampus buka setiap hari."
    claims = extract_claims(answer)
    assert len(claims) == 2
    assert claims[0].citation_ids == (1, 2)
    assert claims[1].citation_ids == ()


def test_extract_claims_returns_empty_for_blank_answer():
    assert extract_claims("") == []
    assert extract_claims("   \n  ") == []
