from app.rag.citation_validator import FALLBACK_ANSWER
from app.verification.claim_gate import verify_claims


class _StubChecker:
    """Entailment by substring match on the hypothesis — deterministic, no network."""

    def __init__(self, scores: dict[str, float]):
        self._scores = scores

    def entails(self, *, premise: str, hypothesis: str) -> float:
        for key, score in self._scores.items():
            if key in hypothesis:
                return score
        return 0.0


def test_gate_drops_unsupported_claim_and_keeps_supported_one():
    answer = "Biaya pendaftaran adalah Rp500.000 [1]. Kampus memiliki kolam renang [1]."
    contexts_by_citation = {
        1: {"url": "https://pmb.mercubuana.ac.id/biaya", "chunk_text": "Biaya pendaftaran program sarjana adalah Rp500.000 untuk semua jalur."}
    }
    checker = _StubChecker({"Biaya pendaftaran": 1.0, "kolam renang": 0.0})

    result = verify_claims(answer, contexts_by_citation, checker)

    assert result.not_found is False
    assert any("Rp500.000" in claim.text for claim in result.supported_claims)
    assert any("kolam renang" in claim.text for claim in result.dropped_claims)
    assert "Rp500.000" in result.answer
    assert "kolam renang" not in result.answer


def test_gate_abstains_when_no_claim_is_supported():
    answer = "Kampus memiliki kolam renang [1]."
    contexts_by_citation = {1: {"chunk_text": "Biaya pendaftaran Rp500.000."}}
    checker = _StubChecker({"kolam renang": 0.0})

    result = verify_claims(answer, contexts_by_citation, checker)

    assert result.not_found is True
    assert result.answer == FALLBACK_ANSWER


def test_gate_drops_uncited_claim_even_if_true():
    # An uncited factual sentence must never be asserted (replaces auto-[1] stapling).
    answer = "Biaya pendaftaran adalah Rp500.000."
    contexts_by_citation = {1: {"chunk_text": "Biaya pendaftaran Rp500.000."}}
    checker = _StubChecker({"Biaya": 1.0})

    result = verify_claims(answer, contexts_by_citation, checker)

    assert result.not_found is True


def test_gate_drops_claim_citing_unknown_source_id():
    # A claim citing a source id that was never retrieved is unsupported.
    answer = "Kampus memiliki kolam renang [9]."
    contexts_by_citation = {1: {"chunk_text": "Biaya pendaftaran Rp500.000."}}
    checker = _StubChecker({"kolam renang": 1.0})  # would "entail" if premise existed

    result = verify_claims(answer, contexts_by_citation, checker)

    assert result.not_found is True
