from app.db.models import Chunk, Document, Source
from app.retrieval.hybrid_retriever import HybridRetriever, _terms


class _SameVectorEmbedder:
    def embed_query(self, query):
        return [1.0, 0.0, 0.0]


def _add_chunk(db, *, url: str, hostname: str, title: str, text: str):
    source = Source(
        url=url,
        title=title,
        hostname=hostname,
        path="/" + url.rsplit("/", 1)[-1],
        status="indexed",
        discovery_source="test",
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
            embedding=[1.0, 0.0, 0.0],
            meta={
                "url": url,
                "hostname": hostname,
                "title": title,
                "source_type": "html",
            },
        )
    )
    db.commit()


def test_english_queries_expand_to_indonesian_retrieval_terms():
    tuition = _terms("Where can I find the tuition fees for Informatics?")
    calendar = _terms("Where is the latest academic calendar?")

    assert "biaya kuliah" in tuition
    assert "rincian pembayaran" in tuition
    assert "teknik informatika" in tuition
    assert "kalender akademik" in calendar
    assert "fakultas" in _terms("What faculties and study programs are available?")


def test_metadata_phrase_match_recovers_indonesian_calendar_for_english_query(db):
    _add_chunk(
        db,
        url="https://baa.mercubuana.ac.id/en/academic-calendar",
        hostname="baa.mercubuana.ac.id",
        title="Academic Calendar - Biro Pembelajaran",
        text="Kalender semester ganjil dan genap Universitas Mercu Buana.",
    )
    _add_chunk(
        db,
        url="https://support.mercubuana.ac.id/kb",
        hostname="support.mercubuana.ac.id",
        title="Knowledgebase",
        text="Academic support and general student information.",
    )

    contexts = HybridRetriever(db, dense_enabled=False).search(
        "Where is the latest UMB academic calendar?",
        top_k=2,
    )

    assert contexts[0]["url"].endswith("/academic-calendar")


def test_hybrid_topic_priority_keeps_tuition_page_above_semantic_faculty_match(db):
    _add_chunk(
        db,
        url="https://pendaftaran.mercubuana.ac.id/rincian-pembayaran",
        hostname="pendaftaran.mercubuana.ac.id",
        title="Biaya Kuliah",
        text="Rincian pembayaran dan total biaya semester Teknik Informatika.",
    )
    _add_chunk(
        db,
        url="https://mercubuana.ac.id/fakultas-ilmu-komputer",
        hostname="mercubuana.ac.id",
        title="Fakultas Ilmu Komputer",
        text="Program studi Teknik Informatika dan Sistem Informasi.",
    )

    contexts = HybridRetriever(
        db,
        embedder=_SameVectorEmbedder(),
        dense_enabled=True,
    ).search("Where can I find tuition fees for Informatics?", top_k=2)

    assert contexts[0]["url"].endswith("/rincian-pembayaran")
    assert contexts[0]["topic_priority"] > contexts[1]["topic_priority"]


def test_admissions_contact_does_not_rank_library_footer_first(db):
    _add_chunk(
        db,
        url="https://lib.mercubuana.ac.id/panduan",
        hostname="lib.mercubuana.ac.id",
        title="Panduan Perpustakaan",
        text="Panduan akses perpustakaan. Hubungi kami untuk bantuan.",
    )
    _add_chunk(
        db,
        url="https://pendaftaran.mercubuana.ac.id/faq",
        hostname="pendaftaran.mercubuana.ac.id",
        title="FAQ Pendaftaran",
        text="Informasi penerimaan mahasiswa baru dan cara menghubungi bagian pendaftaran.",
    )

    contexts = HybridRetriever(db, dense_enabled=False).search(
        "Bagaimana menghubungi bagian penerimaan mahasiswa UMB?",
        top_k=2,
    )

    assert contexts[0]["hostname"] == "pendaftaran.mercubuana.ac.id"


def test_k3_report_query_prioritizes_official_pdf_over_generic_reports(db):
    _add_chunk(
        db,
        url="https://publikasi.mercubuana.ac.id/laporan-kegiatan",
        hostname="publikasi.mercubuana.ac.id",
        title="Laporan Kegiatan Februari 2026",
        text="Laporan kegiatan dan publikasi kampus pada Februari 2026.",
    )
    _add_chunk(
        db,
        url="https://agv-api.mercubuana.ac.id/uploads/media/laporan-k3lk-februari-2026.pdf",
        hostname="agv-api.mercubuana.ac.id",
        title="Laporan K3LK Februari 2026",
        text=(
            "Laporan K3LK Februari 2026 membahas keselamatan dan kesehatan kerja "
            "serta lingkungan kampus Universitas Mercu Buana."
        ),
    )

    contexts = HybridRetriever(db, dense_enabled=False).search(
        "Apa isi laporan K3LK Februari 2026?",
        top_k=2,
    )

    assert contexts[0]["url"].endswith(".pdf")
    assert all("k3" in (context["title"] or "").lower() for context in contexts)


def test_english_faculty_overview_query_avoids_news_and_repository(db):
    _add_chunk(
        db,
        url="https://repository.mercubuana.ac.id/92028",
        hostname="repository.mercubuana.ac.id",
        title="Thesis from Faculty of Economics",
        text="A study by a student in one faculty and study program.",
    )
    _add_chunk(
        db,
        url="https://mercubuana.ac.id/campus-update/berita/program-motorsport",
        hostname="mercubuana.ac.id",
        title="Study Program Motorsport News",
        text="Latest news from one study program at the engineering faculty.",
    )
    _add_chunk(
        db,
        url="https://mercubuana.ac.id/fakultas",
        hostname="mercubuana.ac.id",
        title="Fakultas - Universitas Mercu Buana",
        text="Daftar fakultas dan program studi Universitas Mercu Buana.",
    )

    contexts = HybridRetriever(db, dense_enabled=False).search(
        "What faculties and study programs are available at Mercu Buana University?",
        top_k=3,
    )

    assert contexts[0]["url"].endswith("/fakultas")
