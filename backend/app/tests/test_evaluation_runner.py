from app.db.models import Chunk, Document, Source
from app.evaluation.evaluate_rag import evaluate, evaluate_grounding_cases


def _insert_indexed_chunk(db):
    source = Source(
        url="https://pmb.mercubuana.ac.id/pendaftaran",
        title="Pendaftaran Mahasiswa Baru",
        hostname="pmb.mercubuana.ac.id",
        path="/pendaftaran",
        status="indexed",
        discovery_source="katana",
    )
    db.add(source)
    db.flush()
    document = Document(source_id=source.id, raw_text="pendaftaran mahasiswa baru", cleaned_text="pendaftaran mahasiswa baru")
    db.add(document)
    db.flush()
    db.add(
        Chunk(
            document_id=document.id,
            source_id=source.id,
            chunk_text="Informasi pendaftaran mahasiswa baru Universitas Mercu Buana melalui PMB.",
            chunk_index=0,
            token_count=10,
            source_type="html",
            meta={
                "url": source.url,
                "hostname": source.hostname,
                "path": source.path,
                "title": source.title,
                "source_type": "html",
                "discovery_source": "katana",
            },
        )
    )
    db.commit()


def test_evaluate_reports_hit_rate_and_abstention(db):
    _insert_indexed_chunk(db)
    questions = [
        {"id": "q1", "question": "Bagaimana cara daftar mahasiswa baru?", "category": "admission", "volatility": "medium", "stakes": "high"},
        {"id": "oos", "question": "Siapa pemenang Piala Dunia 2022?", "category": "out_of_scope", "expected_not_found": True},
    ]

    report = evaluate(questions, db=db, top_k=5)

    assert report["total_questions"] == 2
    # In-scope question retrieved a context; the out-of-scope item is excluded from hit-rate.
    assert report["retrieval_hit_rate"] == 1.0
    # The out-of-scope item should abstain (no context) and be scored correct.
    assert report["abstention"]["correct_abstention"] == 1
    assert report["volatility_distribution"]["medium"] == 1
    assert report["results"][1]["intent"] == "out_of_scope"


def test_evaluate_skips_retrieval_for_guarded_questions():
    class _Retriever:
        def search(self, *_args, **_kwargs):
            raise AssertionError("guarded questions must not reach retrieval")

    report = evaluate(
        [
            {
                "id": "unsafe",
                "question": "What is my SIA account password?",
                "category": "private_credential",
                "expected_not_found": True,
            }
        ],
        db=None,
        retriever=_Retriever(),
    )

    assert report["abstention"]["correct_abstention"] == 1
    assert report["results"][0]["intent"] == "unsafe_private_data"


def test_evaluate_reports_labelled_target_hits(db):
    _insert_indexed_chunk(db)
    questions = [
        {
            "id": "q1",
            "question": "Bagaimana cara daftar mahasiswa baru?",
            "category": "admission",
            "expected_hosts": ["pmb.mercubuana.ac.id"],
        }
    ]

    report = evaluate(questions, db=db, top_k=5, strategy="keyword")

    assert report["labelled_target_questions"] == 1
    assert report["labelled_target_hit_rate"] == 1.0


def test_grounding_fixture_is_classified_offline():
    report = evaluate_grounding_cases()
    assert report["total_cases"] == 4
    assert report["classification_accuracy"] == 1.0


def test_evaluate_reports_ranking_metrics_and_latency():
    class _Retriever:
        def search(self, question, top_k, apply_model_reranker):
            target = {
                "url": "https://mercubuana.ac.id/fakultas-ilmu-komputer",
                "hostname": "mercubuana.ac.id",
            }
            noisy = {
                "url": "https://lib.mercubuana.ac.id/bidang-ilmu-komputer",
                "hostname": "lib.mercubuana.ac.id",
            }
            return [target, noisy] if apply_model_reranker else [noisy, target]

    questions = [
        {
            "id": "rank",
            "question": "program studi fasilkom",
            "expected_url_contains": ["/fakultas-ilmu-komputer"],
            "forbidden_hosts": ["lib.mercubuana.ac.id"],
        }
    ]

    baseline = evaluate(
        questions,
        db=None,
        retriever=_Retriever(),
        reranker_enabled=False,
    )
    reranked = evaluate(
        questions,
        db=None,
        retriever=_Retriever(),
        reranker_enabled=True,
    )

    assert baseline["hit_at_1"] == 0.0
    assert baseline["hit_at_3"] == 1.0
    assert baseline["mrr"] == 0.5
    assert baseline["noisy_at_1_rate"] == 1.0
    assert reranked["hit_at_1"] == 1.0
    assert reranked["mrr"] == 1.0
    assert reranked["latency_ms"]["median"] >= 0.0
