from app.agent.umb_agent import _dedupe_contexts


def test_dedupe_contexts_canonicalizes_umb_scheme_and_www():
    contexts = [
        {
            "url": "http://www.mercubuana.ac.id/fakultas",
            "chunk_text": "Fakultas resmi UMB.",
        },
        {
            "url": "https://mercubuana.ac.id/fakultas",
            "chunk_text": "Fakultas resmi UMB.",
        },
    ]

    deduped = _dedupe_contexts(contexts)

    assert len(deduped) == 1
    assert deduped[0]["url"] == "https://mercubuana.ac.id/fakultas"
