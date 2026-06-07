from app.verification.entailment import LLMJudgeEntailmentChecker

PREMISE = "Biaya pendaftaran program sarjana adalah Rp500.000."
HYPOTHESIS = "Biaya pendaftaran adalah Rp500.000."


def test_llm_judge_high_score_when_model_says_yes():
    checker = LLMJudgeEntailmentChecker(chat=lambda messages: "YES")
    assert checker.entails(premise=PREMISE, hypothesis=HYPOTHESIS) >= 0.5


def test_llm_judge_low_score_when_model_says_no():
    checker = LLMJudgeEntailmentChecker(chat=lambda messages: "NO")
    assert checker.entails(premise=PREMISE, hypothesis="Perpustakaan buka pukul 8.") < 0.5


def test_llm_judge_defaults_to_not_entailed_on_unparseable_response():
    # Safety-critical: if the judge is ambiguous, never treat the claim as supported.
    checker = LLMJudgeEntailmentChecker(chat=lambda messages: "I'm not sure about that")
    assert checker.entails(premise=PREMISE, hypothesis=HYPOTHESIS) < 0.5
