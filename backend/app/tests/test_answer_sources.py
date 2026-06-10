from app.rag.answer_generator import _build_sources


def test_build_sources_surfaces_last_verified_and_authority():
    contexts = [
        {
            "url": "https://pmb.mercubuana.ac.id/x",
            "title": "Biaya PMB",
            "hostname": "pmb.mercubuana.ac.id",
            "source_type": "html",
            "last_verified": "2026-06-07",
            "authority": 0.8,
        }
    ]
    sources = _build_sources(contexts)
    assert sources[0]["last_verified"] == "2026-06-07"
    assert sources[0]["authority"] == 0.8
