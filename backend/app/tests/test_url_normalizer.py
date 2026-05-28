from app.discovery.url_deduplicator import deduplicate_urls
from app.discovery.url_normalizer import archive_to_live_candidate, normalize_url


def test_url_normalizer_removes_tracking_parameters_and_fragments():
    url = "HTTPS://MercuBuana.ac.id//Berita/?utm_source=x&fbclid=y&id=7#frag"
    assert normalize_url(url) == "https://mercubuana.ac.id/Berita?id=7"


def test_url_deduplicator_removes_duplicates():
    urls = ["https://mercubuana.ac.id/berita/", "https://mercubuana.ac.id/berita#top"]
    assert deduplicate_urls(urls) == ["https://mercubuana.ac.id/berita"]


def test_url_normalizer_keeps_subdomain_hostname():
    assert normalize_url("HTTPS://PMB.MercuBuana.ac.id//pendaftaran/?utm_campaign=x") == "https://pmb.mercubuana.ac.id/pendaftaran"


def test_url_normalizer_removes_utm_id():
    assert normalize_url("https://pendaftaran.mercubuana.ac.id/?utm_id=official") == "https://pendaftaran.mercubuana.ac.id/"


def test_archive_url_handling_converts_archived_urls_to_live_candidates():
    archive = "https://web.archive.org/web/20200101000000/https://mercubuana.ac.id/berita?utm_medium=x"
    assert archive_to_live_candidate(archive) == "https://mercubuana.ac.id/berita"
