"""v3 P1 — citation / URL hallucination prevention tests.

Goal: 0 fabricated URLs, 100% of cited URLs traceable to the KB.
"""

from __future__ import annotations

from app.rag.citation_validator import (
    scrub_unverified_urls,
    validate_citations,
    verified_url_set,
)


# --- scrubber ----------------------------------------------------------------
def test_scrub_removes_fabricated_faculty_url_keeps_verified():
    verified = {"https://fasilkom.mercubuana.ac.id"}
    answer = (
        "Dekan FASILKOM tercantum pada https://fasilkom.mercubuana.ac.id/ [1]. "
        "Lihat juga https://www.mercubuana.ac.id/fakultas/ilmu-komputer/struktur-organisasi/."
    )
    out = scrub_unverified_urls(answer, verified)
    assert "fasilkom.mercubuana.ac.id" in out
    assert "struktur-organisasi" not in out  # fabricated slug URL removed


def test_scrub_markdown_link_keeps_text_drops_fake_link():
    verified = {"https://sia.mercubuana.ac.id"}
    answer = "Akses [SIA](https://www.mercubuana.ac.id/sia/login/fake) untuk KRS."
    out = scrub_unverified_urls(answer, verified)
    assert "SIA" in out and "fake" not in out and "](http" not in out


def test_scrub_keeps_all_verified_urls():
    verified = {"https://sso.mercubuana.ac.id", "https://support.mercubuana.ac.id"}
    answer = "Login di https://sso.mercubuana.ac.id/ atau hubungi https://support.mercubuana.ac.id/."
    out = scrub_unverified_urls(answer, verified)
    assert "sso.mercubuana.ac.id" in out and "support.mercubuana.ac.id" in out


def test_verified_set_includes_context_source_urls():
    contexts = [
        {"url": "https://kemahasiswaan.mercubuana.ac.id/", "source_urls": ["https://www.mercubuana.ac.id/"]},
    ]
    vs = verified_url_set(contexts)
    assert any("kemahasiswaan" in u for u in vs)
    assert any("www.mercubuana.ac.id" in u or "mercubuana.ac.id" in u for u in vs)


# --- validate_citations scrubs the answer body -------------------------------
def _payload(answer, url):
    return {"answer": answer, "sources": [{"url": url, "citation_id": 1}], "confidence": "high", "not_found": False}


def test_validate_citations_strips_fabricated_inline_url():
    ctx = [{"url": "https://fasilkom.mercubuana.ac.id/", "hostname": "fasilkom.mercubuana.ac.id",
            "chunk_text": "Fakultas Ilmu Komputer", "title": "FASILKOM"}]
    answer = ("Fakultas Ilmu Komputer [1]. Sumber: https://fasilkom.mercubuana.ac.id/ "
              "dan https://www.mercubuana.ac.id/fakultas/ilmu-komputer/struktur-organisasi/.")
    result = validate_citations(_payload(answer, "https://fasilkom.mercubuana.ac.id/"), ctx, require_citation_markers=True)
    assert result["not_found"] is False
    assert "struktur-organisasi" not in result["answer"]
    assert "fasilkom.mercubuana.ac.id" in result["answer"]
    # every cited source URL is traceable to the retrieved context
    assert all(s["url"] == "https://fasilkom.mercubuana.ac.id/" for s in result["sources"])


def test_validate_citations_drops_source_url_not_in_contexts():
    # a "source" whose URL is not among retrieved contexts must be dropped
    ctx = [{"url": "https://sia.mercubuana.ac.id/", "hostname": "sia.mercubuana.ac.id", "chunk_text": "SIA"}]
    payload = {
        "answer": "Akses SIA [1].",
        "sources": [{"url": "https://sia.mercubuana.ac.id/fabricated-path", "citation_id": 1}],
        "confidence": "high",
        "not_found": False,
    }
    result = validate_citations(payload, ctx, require_citation_markers=True)
    # fabricated source dropped → no valid sources → abstain
    assert result["not_found"] is True


# --- canonical URL registry --------------------------------------------------
def test_canonical_urls_rebuild_and_load(db):
    from app.ingestion.entity_extractor import seed_entities
    from app.ingestion.faq_seed import seed_faqs
    from app.rag.canonical_urls import canonical_url_set, invalidate_cache, rebuild_canonical_urls

    seed_entities(db)
    seed_faqs(db)
    result = rebuild_canonical_urls(db)
    assert result["inserted"] > 0
    invalidate_cache()
    urls = canonical_url_set()
    # faculty + SIA/SSO/scholarship canonical URLs present, normalized
    joined = " ".join(urls)
    assert "fasilkom.mercubuana.ac.id" in joined
    assert "sia.mercubuana.ac.id" in joined
    assert "sso.mercubuana.ac.id" in joined
    invalidate_cache()
