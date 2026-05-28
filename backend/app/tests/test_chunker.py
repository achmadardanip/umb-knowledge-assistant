from app.ingestion.chunker import chunk_segments, chunk_text


def test_chunker_creates_chunks_with_metadata():
    text = " ".join(["akademik"] * 120)
    chunks = chunk_text(text, metadata={"url": "https://mercubuana.ac.id/akademik", "title": "Akademik", "source_type": "html"}, chunk_size=50, overlap=10)
    assert chunks
    assert chunks[0].metadata["url"] == "https://mercubuana.ac.id/akademik"
    assert chunks[0].source_type == "html"


def test_multimodal_chunks_include_source_type_and_extraction_metadata():
    segments = [
        {
            "content": " ".join(["pendaftaran"] * 120),
            "source_type": "pdf",
            "page_number": 2,
            "extraction_method": "pymupdf",
            "extraction_confidence": 0.85,
        }
    ]
    chunks = chunk_segments(segments, chunk_size=60, overlap=10)
    assert chunks[0].page_number == 2
    assert chunks[0].extraction_method == "pymupdf"
    assert chunks[0].extraction_confidence == 0.85

