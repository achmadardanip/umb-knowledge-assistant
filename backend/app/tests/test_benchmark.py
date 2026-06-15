"""Tests for the UMB answerability benchmark (dataset generator + runner)."""

from __future__ import annotations

from app.evaluation.benchmark import _stratified_sample, run_benchmark
from app.evaluation.benchmark_dataset import (
    CATEGORY_SPECS,
    Entities,
    generate_benchmark,
    load_entities,
)


# --- dataset generator -------------------------------------------------------
def test_generate_benchmark_meets_minimum_and_covers_categories():
    records = generate_benchmark()
    assert len(records) >= 500
    categories = {r["category"] for r in records}
    # all twelve answer-bearing categories present
    assert set(CATEGORY_SPECS).issubset(categories)
    # control categories present (needed to measure hallucination/abstention)
    assert {"out_of_scope", "private_credential"}.issubset(categories)


def test_generate_benchmark_records_are_well_formed():
    records = generate_benchmark()
    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids)), "ids must be unique"
    for record in records:
        assert record["question"].strip()
        assert record["qtype"] in {"direct", "paraphrase", "ambiguous", "multi_hop", "control"}
        if record["category"] in CATEGORY_SPECS:
            # answer-bearing questions carry retrieval labels + an archive guard
            assert record.get("expected_hosts") or record.get("expected_url_contains")
            assert "repository.mercubuana.ac.id" in record["forbidden_hosts"]
        else:
            assert record.get("expected_not_found") is True


def test_generate_benchmark_has_all_qtypes():
    qtypes = {r["qtype"] for r in generate_benchmark()}
    assert {"direct", "paraphrase", "ambiguous", "multi_hop"}.issubset(qtypes)


def test_slot_templates_expand_across_entities():
    small = Entities(faculties=("Fakultas A", "Fakultas B"), programs=("Prog X",), campuses=("Kampus Y",))
    records = generate_benchmark(small)
    dekan = [r for r in records if "dekan" in r["question"].lower() and "{" not in r["question"]]
    # both faculties produce a dean question; no unfilled slots remain
    assert any("Fakultas A" in r["question"] for r in dekan)
    assert any("Fakultas B" in r["question"] for r in dekan)
    assert all("{" not in r["question"] for r in records)


def test_load_entities_dedupes_case_variants(tmp_path):
    path = tmp_path / "ents.json"
    path.write_text('{"faculties": ["Fakultas Ekonomi dan Bisnis", "Fakultas Ekonomi dan bisnis"]}', encoding="utf-8")
    entities = load_entities(path)
    # case-variant collapsed to a single faculty
    assert len(entities.faculties) == 1


def test_load_entities_missing_file_falls_back_to_defaults():
    entities = load_entities("/no/such/file.json")
    assert len(entities.faculties) >= 3
    assert len(entities.programs) >= 3


# --- stratified sampling -----------------------------------------------------
def test_stratified_sample_is_deterministic_and_bounded():
    records = generate_benchmark()
    a = _stratified_sample(records, 2)
    b = _stratified_sample(records, 2)
    assert a == b  # deterministic
    by_cat: dict[str, int] = {}
    id_to_cat = {r["id"]: r["category"] for r in records}
    for sid in a:
        by_cat[id_to_cat[sid]] = by_cat.get(id_to_cat[sid], 0) + 1
    assert all(count <= 2 for count in by_cat.values())


# --- runner (retrieval tier) -------------------------------------------------
class _StubRetriever:
    """Returns a context whose host is chosen by a marker in the question."""

    def __init__(self, mapping: dict[str, dict]):
        self._mapping = mapping

    def search(self, question: str, top_k: int = 5):
        for marker, context in self._mapping.items():
            if marker in question:
                return [context]
        return []


def _q(qid: str, question: str, **extra) -> dict:
    base = {"id": qid, "question": question, "category": "admissions", "qtype": "direct", "lang": "id", "audience": "publik"}
    base.update(extra)
    return base


def test_run_benchmark_scores_answerable_and_citation_failures():
    official = {"hostname": "pendaftaran.mercubuana.ac.id", "url": "https://pendaftaran.mercubuana.ac.id/biaya", "chunk_text": "Biaya kuliah ...", "score": 3.0}
    archive = {"hostname": "repository.mercubuana.ac.id", "url": "https://repository.mercubuana.ac.id/123", "chunk_text": "tesis ...", "score": 2.0}
    retriever = _StubRetriever({"HIT": official, "NOISE": archive})

    questions = [
        _q("hit_01", "Pertanyaan HIT biaya", expected_hosts=["pendaftaran.mercubuana.ac.id"], forbidden_hosts=["repository.mercubuana.ac.id"]),
        _q("noise_01", "Pertanyaan NOISE biaya", expected_hosts=["pendaftaran.mercubuana.ac.id"], forbidden_hosts=["repository.mercubuana.ac.id"]),
        _q("miss_01", "Pertanyaan tanpa hasil", expected_hosts=["pendaftaran.mercubuana.ac.id"], forbidden_hosts=["repository.mercubuana.ac.id"]),
    ]
    report = run_benchmark(questions, db=None, retriever=retriever, top_k=5)

    rows = {r["id"]: r for r in report["results"]}
    assert rows["hit_01"]["answerable"] is True
    assert rows["hit_01"]["target_hit"] is True
    assert rows["noise_01"]["noisy_at_1"] is True
    assert rows["noise_01"]["answerable"] is False  # forbidden host at rank 1
    assert rows["miss_01"]["sources_found"] is False
    assert rows["miss_01"]["answerable"] is False
    assert report["citation_failure_count"] == 1
    assert report["overall"]["answerability"] == round(1 / 3, 3)


def test_run_benchmark_generation_tier_flags_hallucination(monkeypatch):
    official = {"hostname": "pendaftaran.mercubuana.ac.id", "url": "https://pendaftaran.mercubuana.ac.id/biaya", "chunk_text": "Biaya kuliah program sarjana adalah Rp500.000.", "score": 3.0}
    retriever = _StubRetriever({"GROUNDED": official, "HALLUCINATE": official})

    def fake_generate(*, question, contexts, recent_messages, memories, provider_override, language):
        if "GROUNDED" in question:
            return {"not_found": False, "answer": "Biaya kuliah program sarjana adalah Rp500.000 [1].", "confidence": "high", "sources": [{"url": official["url"]}]}
        return {"not_found": False, "answer": "Biaya kuliah adalah Rp99.999.999 [1].", "confidence": "high", "sources": [{"url": official["url"]}]}

    monkeypatch.setattr("app.rag.answer_generator.generate_answer", fake_generate)

    questions = [
        _q("gen_grounded", "Pertanyaan GROUNDED biaya", expected_hosts=["pendaftaran.mercubuana.ac.id"], forbidden_hosts=[]),
        _q("gen_hallu", "Pertanyaan HALLUCINATE biaya", expected_hosts=["pendaftaran.mercubuana.ac.id"], forbidden_hosts=[]),
    ]
    sample = {"gen_grounded", "gen_hallu"}
    report = run_benchmark(questions, db=None, retriever=retriever, top_k=5, generation_sample=sample)

    rows = {r["id"]: r for r in report["results"]}
    assert rows["gen_grounded"]["generated"] is True
    assert rows["gen_grounded"]["grounded"] is True
    assert rows["gen_grounded"]["hallucinated"] is False
    # unsupported number -> faithfulness fails -> hallucinated
    assert rows["gen_hallu"]["hallucinated"] is True
    assert report["overall"]["generation"]["evaluated"] == 2
