from app.verification.support import SupportWeights, support_score


def test_support_score_defaults_to_entailment_only():
    assert support_score(entailment=0.8) == 0.8


def test_support_score_blends_features_by_weight():
    weights = SupportWeights(entailment=0.5, authority=0.5)
    # entailment 1.0, authority 0.0, equal weight -> 0.5
    assert support_score(entailment=1.0, authority=0.0, weights=weights) == 0.5


def test_support_score_ignores_missing_features():
    weights = SupportWeights(entailment=0.5, authority=0.5)
    # authority absent -> normalize over the entailment term only, no penalty
    assert support_score(entailment=0.7, weights=weights) == 0.7
