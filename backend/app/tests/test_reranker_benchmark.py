import pytest

from app.evaluation.benchmark_reranker import _added_latency


def test_added_latency_uses_per_question_deltas():
    baseline = {
        "results": [
            {"id": "a", "latency_ms": 100.0},
            {"id": "b", "latency_ms": 200.0},
            {"id": "c", "latency_ms": 300.0},
        ]
    }
    reranked = {
        "results": [
            {"id": "a", "latency_ms": 150.0},
            {"id": "b", "latency_ms": 350.0},
            {"id": "c", "latency_ms": 550.0},
        ]
    }

    result = _added_latency(reranked, baseline)

    assert result["median"] == pytest.approx(150.0)
    assert result["p95"] == pytest.approx(250.0)
