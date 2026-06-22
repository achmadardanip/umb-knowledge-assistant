from app.evaluation.rag_golden_subset import stratified_sample

ROWS = [
    {"id": f"q{i}", "question": f"Q{i}",
     "intent": ["admissions", "tuition", "faculty"][i % 3],
     "answerable": True, "synthetic": False}
    for i in range(30)
]


def test_sample_is_deterministic():
    assert stratified_sample(ROWS, 9, seed=1) == stratified_sample(ROWS, 9, seed=1)


def test_sample_size_and_fields():
    s = stratified_sample(ROWS, 9)
    assert len(s) == 9
    assert all(set(r) == {"id", "question", "intent"} for r in s)


def test_sample_excludes_synthetic_and_unanswerable():
    rows = ROWS + [
        {"id": "x", "question": "x", "intent": "admissions", "answerable": False, "synthetic": False},
        {"id": "y", "question": "y", "intent": "admissions", "answerable": True, "synthetic": True},
    ]
    ids = {r["id"] for r in stratified_sample(rows, 30)}
    assert "x" not in ids and "y" not in ids


def test_sample_spreads_across_intents():
    s = stratified_sample(ROWS, 9)
    assert len({r["intent"] for r in s}) == 3


def test_sample_size_exceeds_pool():
    assert len(stratified_sample(ROWS, 1000)) == 30
