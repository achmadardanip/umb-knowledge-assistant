from app.api.routes_rag_eval import _adhoc_payload
from app.evaluation.rag_graders import FaithfulnessVerdict, RelevanceVerdict


def test_adhoc_payload_with_grades():
    faith = FaithfulnessVerdict(score=0.8, passed=True, reason="ok")
    rel = RelevanceVerdict(score=0.9, passed=True, reason="rel")
    out = _adhoc_payload("q", "a", "ctx", [{"hostname": "x"}], False, faith, rel)
    assert out["question"] == "q" and out["answer"] == "a" and out["not_found"] is False
    assert out["faithfulness"] == {"score": 0.8, "passed": True, "reason": "ok"}
    assert out["relevance"]["score"] == 0.9 and out["relevance"]["passed"] is True


def test_adhoc_payload_not_found_skips_faithfulness():
    rel = RelevanceVerdict(score=0.0, passed=False, reason="x")
    out = _adhoc_payload("q", "refusal", "", [], True, None, rel)
    assert out["not_found"] is True
    assert out["faithfulness"] is None
    assert out["relevance"]["passed"] is False
