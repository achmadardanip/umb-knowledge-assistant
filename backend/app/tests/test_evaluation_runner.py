from app.db.models import Chunk, Document, Source
from app.evaluation.evaluate_rag import evaluate


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
