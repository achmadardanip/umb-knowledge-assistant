from app.rag.citation_validator import FALLBACK_ANSWER, validate_citations


def test_citation_validator_rejects_unsupported_citation():
    payload = {"answer": "Biaya tersedia.", "sources": [{"url": "https://example.com"}], "confidence": "high", "not_found": False}
    result = validate_citations(payload, [{"url": "https://mercubuana.ac.id/biaya", "hostname": "mercubuana.ac.id"}])
    assert result["not_found"] is True
    assert result["answer"] == FALLBACK_ANSWER


def test_citation_validator_supports_pdf_video_and_spreadsheet_metadata():
    contexts = [
        {"url": "https://mercubuana.ac.id/file.pdf", "hostname": "mercubuana.ac.id", "source_type": "pdf", "page_number": 3},
        {"url": "https://mercubuana.ac.id/video.mp4", "hostname": "mercubuana.ac.id", "source_type": "video", "timestamp_start": 10, "timestamp_end": 20, "extraction_confidence": 0.7},
        {"url": "https://mercubuana.ac.id/data.xlsx", "hostname": "mercubuana.ac.id", "source_type": "spreadsheet", "sheet_name": "Biaya", "row_range": "1-5"},
    ]
    payload = {
        "answer": "Informasi ditemukan.",
        "sources": contexts,
        "confidence": "medium",
        "not_found": False,
    }
    result = validate_citations(payload, contexts)
    assert result["not_found"] is False
    assert len(result["sources"]) == 3


def test_citation_validator_accepts_live_subdomain_source():
    context = {
        "url": "https://pmb.mercubuana.ac.id/pendaftaran",
        "hostname": "pmb.mercubuana.ac.id",
        "source_type": "html",
    }
    payload = {"answer": "Informasi pendaftaran ditemukan.", "sources": [context], "confidence": "high", "not_found": False}
    result = validate_citations(payload, [context])
    assert result["not_found"] is False
    assert result["sources"][0]["hostname"] == "pmb.mercubuana.ac.id"


def test_citation_validator_accepts_model_source_as_url_string():
    context = {
        "url": "https://pendaftaran.mercubuana.ac.id/",
        "hostname": "pendaftaran.mercubuana.ac.id",
        "source_type": "html",
    }
    payload = {"answer": "Informasi pendaftaran ditemukan.", "sources": [context["url"]], "confidence": "medium", "not_found": False}
    result = validate_citations(payload, [context])
    assert result["not_found"] is False
    assert result["sources"][0]["url"] == context["url"]


def test_citation_validator_matches_normalized_tracking_url():
    context = {
        "url": "https://pendaftaran.mercubuana.ac.id/?utm_id=official",
        "hostname": "pendaftaran.mercubuana.ac.id",
        "source_type": "html",
    }
    payload = {
        "answer": "Pendaftaran tersedia di portal resmi.",
        "sources": ["https://pendaftaran.mercubuana.ac.id/"],
        "confidence": "high",
        "not_found": False,
    }
    result = validate_citations(payload, [context])
    assert result["not_found"] is False
    assert result["sources"][0]["url"] == context["url"]


def test_citation_validator_normalizes_numeric_confidence():
    context = {"url": "https://mercubuana.ac.id/", "hostname": "mercubuana.ac.id", "source_type": "html"}
    payload = {"answer": "Informasi ditemukan.", "sources": [context], "confidence": 0.9, "not_found": False}
    result = validate_citations(payload, [context])
    assert result["confidence"] == "high"


def test_citation_validator_rejects_lookalike_umb_domain():
    context = {
        "url": "https://mercubuana.ac.id.evil.com/pendaftaran",
        "hostname": "mercubuana.ac.id.evil.com",
        "source_type": "html",
    }
    payload = {"answer": "Tidak boleh valid.", "sources": [context], "confidence": "high", "not_found": False}
    result = validate_citations(payload, [context])
    assert result["not_found"] is True


def test_low_confidence_ocr_asr_does_not_produce_high_confidence_answers():
    contexts = [{"url": "https://mercubuana.ac.id/poster.jpg", "hostname": "mercubuana.ac.id", "source_type": "image", "extraction_confidence": 0.3}]
    payload = {"answer": "Ada teks poster.", "sources": contexts, "confidence": "high", "not_found": False}
    result = validate_citations(payload, contexts)
    assert result["confidence"] == "medium"
