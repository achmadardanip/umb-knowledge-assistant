"""P4 — groundedness verifier + decision + metrics."""

from __future__ import annotations

from app.evaluation.metrics import citation_alignment, unsupported_claim_rate
from app.verification.groundedness import (
    DECISION_ABSTAIN,
    DECISION_REGENERATE,
    DECISION_RETURN,
    GroundednessVerifier,
    build_groundedness_checker,
)


class _StubChecker:
    """Returns a fixed score for every (premise, hypothesis)."""

    def __init__(self, score: float) -> None:
        self._score = score

    def entails(self, *, premise: str, hypothesis: str) -> float:
        return self._score


class _SequenceChecker:
    """Returns successive scores in claim order (one call per cited claim)."""

    def __init__(self, scores: list[float]) -> None:
        self._scores = list(scores)
        self._i = 0

    def entails(self, *, premise: str, hypothesis: str) -> float:
        score = self._scores[self._i] if self._i < len(self._scores) else 0.0
        self._i += 1
        return score


_CTX = {1: {"chunk_text": "Sumber resmi UMB tentang pendaftaran dan beasiswa."},
        2: {"chunk_text": "Halaman resmi perpustakaan dan layanan kampus."}}

_ANSWER_2 = "Pendaftaran dibuka setiap gelombang [1]. Beasiswa KIP tersedia untuk mahasiswa [2]."
_ANSWER_4 = (
    "Pendaftaran dibuka setiap gelombang [1]. Biaya pendaftaran tersedia di portal [1]. "
    "Beasiswa KIP tersedia untuk mahasiswa [2]. Perpustakaan buka setiap hari kerja [2]."
)


def _verifier(checker, **kw):
    return GroundednessVerifier(checker, checker_name="stub", **kw)


def test_all_supported_returns():
    r = _verifier(_StubChecker(1.0)).verify(_ANSWER_2, _CTX)
    assert r.score == 1.0
    assert r.decision == DECISION_RETURN
    assert r.unsupported_claim_rate == 0.0
    assert r.citation_alignment == 1.0


def test_all_unsupported_abstains():
    r = _verifier(_StubChecker(0.0)).verify(_ANSWER_2, _CTX)
    assert r.score == 0.0
    assert r.decision == DECISION_ABSTAIN
    assert r.unsupported_claim_rate == 1.0


def test_partial_support_regenerates():
    # 4 cited claims, 3 supported -> 0.75 -> regenerate band [0.70, 0.90)
    r = _verifier(_SequenceChecker([1.0, 1.0, 1.0, 0.0])).verify(_ANSWER_4, _CTX)
    assert r.total == 4 and r.supported == 3
    assert r.score == 0.75
    assert r.decision == DECISION_REGENERATE


def test_no_claims_is_vacuously_grounded():
    r = _verifier(_StubChecker(0.0)).verify("", _CTX)
    assert r.total == 0
    assert r.score == 1.0
    assert r.decision == DECISION_RETURN


def test_citation_alignment_flags_dangling_citation():
    # cites [3] which is not among the retrieved contexts {1,2}
    answer = "Pendaftaran dibuka setiap gelombang [3]."
    assert citation_alignment(answer, _CTX) == 0.0
    assert citation_alignment(_ANSWER_2, _CTX) == 1.0


def test_unsupported_claim_rate_metric():
    assert unsupported_claim_rate(_ANSWER_2, _CTX, _StubChecker(1.0)) == 0.0
    assert unsupported_claim_rate(_ANSWER_2, _CTX, _StubChecker(0.0)) == 1.0


def test_build_checker_degrades_and_never_raises():
    # 'nli'/'minicheck' may be unavailable offline → must fall back, never raise.
    checker, name = build_groundedness_checker("nli")
    assert name in {"minicheck", "nli", "lexical"}
    assert hasattr(checker, "entails")
    # explicit lexical request always works
    checker2, name2 = build_groundedness_checker("lexical")
    assert name2 == "lexical"


def test_custom_thresholds_change_decision():
    # with a lenient return threshold, 0.75 should RETURN instead of regenerate
    r = _verifier(_SequenceChecker([1.0, 1.0, 1.0, 0.0]), return_threshold=0.70).verify(_ANSWER_4, _CTX)
    assert r.decision == DECISION_RETURN


def test_apply_groundedness_decision_abstains_keeps_official_sources(monkeypatch):
    from app.rag import answer_generator as ag
    import app.verification.groundedness as g

    monkeypatch.setattr(g, "build_groundedness_checker", lambda pref, chat=None: (_StubChecker(0.0), "stub"))
    payload = {
        "answer": _ANSWER_2,
        "sources": [{"citation_id": 1, "url": "u1"}, {"citation_id": 2, "url": "u2"}],
        "not_found": False,
        "metadata": {},
    }
    contexts = [{"url": "u1", "chunk_text": "resmi 1"}, {"url": "u2", "chunk_text": "resmi 2"}]
    out = ag._apply_groundedness_decision(payload, contexts, None)
    assert out["not_found"] is True
    assert out["metadata"]["fallback"] == "groundedness_abstain"
    assert out["metadata"]["groundedness"]["decision"] == DECISION_ABSTAIN
    assert out["sources"]  # official source cards retained ("official sources only")
