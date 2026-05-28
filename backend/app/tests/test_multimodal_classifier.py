import pytest

from app.multimodal.source_classifier import classify_source


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://mercubuana.ac.id/", "unknown"),
        ("https://mercubuana.ac.id/index.html", "html"),
        ("https://mercubuana.ac.id/file.pdf", "pdf"),
        ("https://mercubuana.ac.id/file.docx", "docx"),
        ("https://mercubuana.ac.id/file.pptx", "pptx"),
        ("https://mercubuana.ac.id/file.xlsx", "xlsx"),
        ("https://mercubuana.ac.id/file.csv", "csv"),
        ("https://mercubuana.ac.id/file.jpg", "image"),
        ("https://mercubuana.ac.id/file.mp3", "audio"),
        ("https://mercubuana.ac.id/file.mp4", "video"),
        ("https://mercubuana.ac.id/file.vtt", "transcript"),
    ],
)
def test_source_classifier_detects_supported_urls(url, expected):
    assert classify_source(url).source_type == expected


def test_source_classifier_falls_back_to_html_for_text_html():
    assert classify_source("https://mercubuana.ac.id/", "text/html").source_type == "html"

