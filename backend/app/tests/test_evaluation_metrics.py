from app.evaluation.metrics import (
    abstention_outcome,
    calibrate_threshold,
    citation_metrics,
    conformal_threshold,
    faithfulness_score,
    risk_coverage_points,
)


class _StubChecker:
    def __init__(self, scores: dict[str, float]):
        self._scores = scores

    def entails(self, *, premise: str, hypothesis: str) -> float:
        for key, score in self._scores.items():
            if key in hypothesis:
                return score
        return 0.0


def test_faithfulness_is_fraction_of_entailed_claims():
    answer = "Biaya pendaftaran adalah Rp500.000 [1]. Kampus memiliki kolam renang [1]."
    contexts_by_citation = {1: {"chunk_text": "Biaya pendaftaran program sarjana adalah Rp500.000."}}
    checker = _StubChecker({"Biaya pendaftaran": 1.0, "kolam renang": 0.0})
    assert faithfulness_score(answer, contexts_by_citation, checker) == 0.5


def test_faithfulness_is_one_for_abstention_answer():
    # No factual claims asserted -> vacuously faithful (nothing false was stated).
    assert faithfulness_score("", {}, _StubChecker({})) == 1.0


def test_uncited_claim_counts_as_unfaithful():
    answer = "Biaya pendaftaran adalah Rp500.000."
    contexts_by_citation = {1: {"chunk_text": "Biaya pendaftaran Rp500.000."}}
    checker = _StubChecker({"Biaya": 1.0})
    assert faithfulness_score(answer, contexts_by_citation, checker) == 0.0


def test_citation_precision_and_recall_on_mixed_answer():
    answer = "Biaya pendaftaran adalah Rp500.000 [1]. Kampus memiliki kolam renang [1]."
    contexts_by_citation = {1: {"chunk_text": "Biaya pendaftaran program sarjana adalah Rp500.000."}}
    checker = _StubChecker({"Biaya pendaftaran": 1.0, "kolam renang": 0.0})
    metrics = citation_metrics(answer, contexts_by_citation, checker)
    assert metrics.precision == 0.5
    assert metrics.recall == 0.5


def test_citation_precision_full_when_all_cited_claims_supported():
    answer = "Biaya pendaftaran adalah Rp500.000 [1]."
    contexts_by_citation = {1: {"chunk_text": "Biaya pendaftaran program sarjana adalah Rp500.000."}}
    checker = _StubChecker({"Biaya pendaftaran": 1.0})
    metrics = citation_metrics(answer, contexts_by_citation, checker)
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0


def test_abstention_outcomes_classify_all_four_quadrants():
    assert abstention_outcome(predicted_not_found=True, expected_not_found=True) == "correct_abstention"
    # Answered when it should have abstained — the dangerous hallucination quadrant.
    assert abstention_outcome(predicted_not_found=False, expected_not_found=True) == "missed_abstention"
    # Abstained when an official answer existed — a usability cost.
    assert abstention_outcome(predicted_not_found=True, expected_not_found=False) == "over_abstention"
    assert abstention_outcome(predicted_not_found=False, expected_not_found=False) == "answered"


# (support_score, is_truly_supported)
_RECORDS = [(0.9, True), (0.8, True), (0.4, False), (0.2, False)]


def test_risk_coverage_points_trade_coverage_for_risk():
    points = {round(p.threshold, 1): p for p in risk_coverage_points(_RECORDS, [0.0, 0.5, 1.0])}
    assert points[0.0].coverage == 1.0
    assert points[0.0].risk == 0.5
    assert points[0.5].coverage == 0.5
    assert points[0.5].risk == 0.0
    assert points[1.0].coverage == 0.0


def test_calibrate_threshold_picks_min_threshold_meeting_target_risk():
    # Lowest threshold (max coverage) whose empirical risk <= target.
    assert calibrate_threshold(_RECORDS, target_risk=0.0, thresholds=[0.0, 0.5, 1.0]) == 0.5
    assert calibrate_threshold(_RECORDS, target_risk=0.5, thresholds=[0.0, 0.5, 1.0]) == 0.0


def test_conformal_threshold_certifies_with_enough_clean_data():
    # 300 high-score correct claims clear a 10% risk bound at 95% confidence.
    records = [(0.9, True)] * 300 + [(0.2, False)] * 270 + [(0.2, True)] * 30
    threshold = conformal_threshold(records, target_risk=0.1, confidence=0.05, thresholds=[0.0, 0.5, 1.0])
    assert threshold == 0.5


def test_conformal_threshold_abstains_when_data_too_sparse_to_certify():
    # Only 10 clean samples: the finite-sample penalty forbids certifying 10% risk -> abstain-all.
    records = [(0.9, True)] * 10 + [(0.2, False)] * 10
    threshold = conformal_threshold(records, target_risk=0.1, confidence=0.05, thresholds=[0.0, 0.5, 1.0])
    assert threshold == 1.0
