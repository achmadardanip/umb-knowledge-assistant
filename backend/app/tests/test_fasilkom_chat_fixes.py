from app.api.routes_chat import ChatRequest, _build_retrieval_query, process_chat
from app.db.models import Chunk, Document, Source
from app.rag.answer_generator import generate_answer
from app.rag.intent_classifier import classify_intent
from app.retrieval.hybrid_retriever import HybridRetriever


def _add_chunk(db, *, url: str, title: str, hostname: str, path: str, text: str):
    source = Source(
        url=url,
        title=title,
        hostname=hostname,
        path=path,
        status="indexed",
        discovery_source="katana",
    )
    db.add(source)
    db.flush()
    document = Document(source_id=source.id, raw_text=text, cleaned_text=text)
    db.add(document)
    db.flush()
    db.add(
        Chunk(
            document_id=document.id,
            source_id=source.id,
            chunk_text=text,
            chunk_index=0,
            token_count=len(text.split()),
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


def _add_fasilkom_chunk(db):
    _add_chunk(
        db,
        url="https://fasilkom.mercubuana.ac.id/struktural-dan-dosen",
        title="Struktural dan Dosen Fasilkom - Universitas Mercu Buana",
        hostname="fasilkom.mercubuana.ac.id",
        path="/struktural-dan-dosen",
        text=(
            "Fakultas Ilmu Komputer Fasilkom Universitas Mercu Buana. "
            "Dekan Fakultas Ilmu Komputer: Dr. Ada Lovelace, M.Kom. "
            "Dosen Tetap Fakultas Ilmu Komputer Pendidikan Sarwati Rahayu, ST, MMSI "
            "Suhendra, S.Kom, M.Kom Sulis Sandiwarno, S.Kom, M.Kom "
            "Program studi Fakultas Ilmu Komputer terdiri dari Teknik Informatika dan Sistem Informasi."
        ),
    )


def _add_noisy_library_chunk(db):
    _add_chunk(
        db,
        url="https://lib.mercubuana.ac.id/id/berita-literasi",
        title="Berita Perpustakaan Universitas Mercu Buana",
        hostname="lib.mercubuana.ac.id",
        path="/id/berita-literasi",
        text=(
            "Kegiatan Literasi Informasi Perpustakaan Universitas Mercu Buana. "
            "Artikel ini menyebut fakultas, program, studi, dan workshop document control."
        ),
    )


def test_capability_question_does_not_use_retrieval(db, monkeypatch):
    result = classify_intent("kamu bisa melakukan apa saja?")
    assert result.intent == "capability_query"

    def fail_search(self, query, top_k=5, source_types=None):
        raise AssertionError("capability answers must not call retrieval")

    monkeypatch.setattr("app.api.routes_chat.HybridRetriever.search", fail_search)
    response = process_chat(
        ChatRequest(
            anonymous_session_id="anon-capability",
            question="kamu bisa melakukan apa saja?",
            retrieval_mode="indexed",
            memory_enabled=False,
        ),
        db,
    )

    assert response["not_found"] is False
    assert response["sources"] == []
    assert "sumber resmi" in response["answer"].lower()


def test_contextual_query_rewrites_fakultas_ini_to_fasilkom():
    question = "Apa saja program studi di fakultas ini?"
    history = [
        {"role": "user", "content": "siapa dosen fasilkom"},
        {
            "role": "assistant",
            "content": "Data dosen Fasilkom tersedia.",
            "sources": [
                {
                    "title": "Struktural dan Dosen Fasilkom - Universitas Mercu Buana",
                    "hostname": "fasilkom.mercubuana.ac.id",
                    "url": "https://fasilkom.mercubuana.ac.id/struktural-dan-dosen",
                }
            ],
        },
        {"role": "user", "content": question},
    ]

    query = _build_retrieval_query(question, history, "Siapa Dosen Fasilkom")

    assert "Fakultas Ilmu Komputer" in query
    assert "Maksud frasa seperti 'fakultas ini'" in query
    assert "perpustakaan" in query


def test_fasilkom_retrieval_prioritizes_faculty_over_library(db):
    _add_noisy_library_chunk(db)
    _add_fasilkom_chunk(db)

    contexts = HybridRetriever(db).search(
        "Apa saja program studi di fakultas ini? Fakultas Ilmu Komputer Fasilkom",
        top_k=5,
    )

    assert contexts
    assert contexts[0]["hostname"] == "fasilkom.mercubuana.ac.id"
    assert all(context["hostname"] != "lib.mercubuana.ac.id" for context in contexts)


def test_structured_fasilkom_answers_are_readable_without_citation_spam(db):
    _add_fasilkom_chunk(db)
    contexts = HybridRetriever(db).search("siapa dosen fasilkom", top_k=5)

    result = generate_answer(
        question="siapa dosen fasilkom",
        contexts=contexts,
        recent_messages=[],
        memories=[],
        provider_override="openrouter",
        language="id",
    )

    assert result["provider_used"] == "system"
    assert "1. Sarwati Rahayu, ST, MMSI" in result["answer"]
    assert "2. Suhendra, S.Kom, M.Kom" in result["answer"]
    assert result["answer"].count("[1]") == 1


def test_structured_fasilkom_dean_answer_extracts_role(db):
    _add_fasilkom_chunk(db)
    contexts = HybridRetriever(db).search("siapa dekan fasilkom", top_k=5)

    result = generate_answer(
        question="siapa dekan fasilkom",
        contexts=contexts,
        recent_messages=[],
        memories=[],
        provider_override="openrouter",
        language="id",
    )

    assert "Dr. Ada Lovelace, M.Kom" in result["answer"]
    assert result["model_used"] == "structured-fasilkom-extractor"


def test_structured_fasilkom_program_followup_uses_context(db):
    _add_fasilkom_chunk(db)
    contexts = HybridRetriever(db).search(
        "Apa saja program studi di fakultas ini? Fakultas Ilmu Komputer Fasilkom",
        top_k=5,
    )

    result = generate_answer(
        question="Apa saja program studi di fakultas ini?",
        contexts=contexts,
        recent_messages=[],
        memories=[],
        provider_override="openrouter",
        language="id",
    )

    assert "Teknik Informatika" in result["answer"]
    assert "Sistem Informasi" in result["answer"]
    assert result["sources"][0]["hostname"] == "fasilkom.mercubuana.ac.id"
