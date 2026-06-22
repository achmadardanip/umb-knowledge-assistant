from app.evaluation.rag_graders import grade_faithfulness, grade_relevance


def test_faithfulness_parses_clean_json():
    fn = lambda m: '{"score": 1.0, "supported": ["a"], "unsupported": [], "reason": "ok"}'
    v = grade_faithfulness("q", "ctx", "ans", chat_fn=fn, threshold=0.8)
    assert v.score == 1.0 and v.passed is True and v.grader_error is False


def test_faithfulness_handles_fenced_json():
    fn = lambda m: "```json\n{\"score\": 0.5, \"reason\": \"half\"}\n```"
    v = grade_faithfulness("q", "c", "a", chat_fn=fn, threshold=0.8)
    assert v.score == 0.5 and v.passed is False


def test_faithfulness_grader_error_on_garbage():
    fn = lambda m: "not json at all"
    v = grade_faithfulness("q", "c", "a", chat_fn=fn)
    assert v.grader_error is True and v.score is None and v.passed is None


def test_faithfulness_clamps_out_of_range():
    fn = lambda m: '{"score": 1.4, "reason": "x"}'
    assert grade_faithfulness("q", "c", "a", chat_fn=fn).score == 1.0


def test_relevance_threshold_pass():
    fn = lambda m: '{"score": 0.7, "reason": "addresses"}'
    assert grade_relevance("q", "a", chat_fn=fn, threshold=0.7).passed is True


def test_relevance_grader_error():
    fn = lambda m: "{bad json"
    assert grade_relevance("q", "a", chat_fn=fn).grader_error is True
