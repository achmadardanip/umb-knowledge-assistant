"""P1 — golden dataset framework tests."""

from __future__ import annotations

from app.evaluation.golden_dataset import (
    DATASET_VERSION,
    build_dataset,
    build_followups,
    from_benchmark_seed,
    from_entities,
    from_faqs,
    statistics,
)

_REQUIRED = {"id", "question", "intent", "expected_sources", "answerable",
             "synthetic", "source_type", "created_at", "dataset_version"}
_SOURCE_TYPES = {"official_faq", "official_page", "faq_alias", "entity_lookup",
                 "benchmark_seed", "synthetic_variant"}


def test_every_record_has_required_metadata():
    for r in build_dataset(target_total=900):
        assert _REQUIRED <= set(r), f"missing keys: {_REQUIRED - set(r)}"
        assert r["source_type"] in _SOURCE_TYPES
        assert r["dataset_version"] == DATASET_VERSION
        assert isinstance(r["expected_sources"], list)


def test_authenticity_invariant_and_traceability():
    ds = build_dataset(target_total=1200)
    for r in ds:
        if r["source_type"] == "synthetic_variant":
            assert r["synthetic"] is True
            assert r.get("derived_from"), "synthetic variant must trace to an authentic id"
        else:
            assert r["synthetic"] is False
    # every derived_from points at a real authentic record
    ids = {r["id"] for r in ds}
    for r in ds:
        if r.get("derived_from"):
            assert r["derived_from"] in ids


def test_phase1_authentic_floor_met():
    authentic = from_benchmark_seed() + from_faqs() + from_entities()
    # de-dup happens in build_dataset; the authentic pool must clear the 300 floor.
    assert len({r["question"].strip().lower() for r in authentic}) >= 300


def test_no_duplicate_questions():
    ds = build_dataset(target_total=1200)
    qs = [r["question"].strip().lower() for r in ds]
    assert len(qs) == len(set(qs))


def test_control_questions_marked_unanswerable():
    bench = from_benchmark_seed()
    controls = [r for r in bench if r["intent"] == "general" and not r["answerable"]]
    assert controls, "control (out_of_scope/private/unanswerable) seeds must exist"
    assert all(r["answerable"] is False for r in controls)


def test_statistics_shape():
    ds = build_dataset(target_total=1000)
    s = statistics(ds)
    assert s["total"] == len(ds)
    assert s["authentic"] + s["synthetic"] == s["total"]
    assert 0.0 <= s["synthetic_ratio"] <= 1.0
    assert 0.0 <= s["answerable_ratio"] <= 1.0
    assert s["source_distribution"] and s["intent_distribution"]


def test_followups_multi_turn_format():
    fu = build_followups()
    assert len(fu) >= 300
    sample = fu[0]
    assert isinstance(sample["conversation"], list) and len(sample["conversation"]) >= 2
    assert isinstance(sample["expected_followup"], bool)
    assert sample["expected_intent"]


# --- P4 mini-validation runner (memory-free: injected generation + stub checker) ---
def test_golden_validation_aggregates_five_metrics():
    from app.evaluation.golden_validation import run_validation
    from app.verification.groundedness import GroundednessVerifier

    class _Stub:
        def entails(self, *, premise, hypothesis):
            return 1.0 if "ok" in hypothesis.lower() else 0.0

    samples = [{"id": "a", "question": "qa"}, {"id": "b", "question": "qb"}]

    def generate(question):
        if question == "qa":
            return {"answer": "Pendaftaran ok [1].",
                    "sources": [{"citation_id": 1, "chunk_text": "Pendaftaran ok via PMB."}],
                    "not_found": False}
        return {"answer": "Biaya mahal sekali [1].",
                "sources": [{"citation_id": 1, "chunk_text": "Pendaftaran ok via PMB."}],
                "not_found": False}

    verifier = GroundednessVerifier(_Stub(), checker_name="stub")
    report = run_validation(samples, generate=generate, verifier=verifier)
    assert report["n"] == 2 and report["n_answered"] == 2
    assert report["groundedness"] == 0.5           # 1.0 (qa) + 0.0 (qb)
    assert report["unsupported_claim_rate"] == 0.5
    assert report["citation_alignment"] == 1.0     # both cite a retrieved [1]
    assert report["abstain_rate"] == 0.5           # qb scores 0 -> abstain
    assert report["regenerate_rate"] == 0.0
