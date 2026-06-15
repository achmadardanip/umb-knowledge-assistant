"""v3 P5 — cache layer + FAQ/entity cache wiring + metadata pruning tests."""

from __future__ import annotations

import time

from app.core.cache import (
    cache_clear,
    cache_get,
    cache_set,
    make_key,
    reset_backend_for_tests,
)
from app.ingestion.metadata_pruning import CHUNK_META_KEEP, prune_metadata


def setup_function():
    reset_backend_for_tests()
    cache_clear()


# --- cache primitives --------------------------------------------------------
def test_cache_set_get_roundtrip():
    k = make_key("t", "a", 1)
    cache_set(k, {"x": 1}, ttl=60)
    assert cache_get(k) == {"x": 1}


def test_cache_ttl_expiry():
    k = make_key("t", "ttl")
    cache_set(k, "v", ttl=0.05)
    assert cache_get(k) == "v"
    time.sleep(0.08)
    assert cache_get(k) is None


def test_cache_miss_returns_none():
    assert cache_get(make_key("t", "missing")) is None


def test_make_key_is_stable_and_namespaced():
    assert make_key("ns", "a", "b") == make_key("ns", "a", "b")
    assert make_key("ns", "a").startswith("umb:ns:")


# --- metadata pruning --------------------------------------------------------
def test_prune_metadata_keeps_only_allowlist():
    bloated = {
        "url": "https://x.mercubuana.ac.id/", "hostname": "x.mercubuana.ac.id",
        "title": "T", "source_type": "html",
        "links": ["https://a"] * 500, "DC.description": "x" * 40000,
        "eprints.abstract": "y" * 40000, "images": ["i"] * 50, "schema_org": {"a": 1},
    }
    pruned = prune_metadata(bloated)
    assert set(pruned) <= CHUNK_META_KEEP
    assert "links" not in pruned and "DC.description" not in pruned and "eprints.abstract" not in pruned
    assert pruned["url"] == "https://x.mercubuana.ac.id/" and pruned["title"] == "T"
    # massive reduction
    import json
    assert len(json.dumps(pruned)) < 300 < len(json.dumps(bloated))


def test_prune_metadata_handles_non_dict():
    assert prune_metadata(None) == {}
    assert prune_metadata("not a dict") == {}


# --- FAQ cache wiring --------------------------------------------------------
def test_faq_loader_is_cached(db):
    from app.ingestion.faq_seed import seed_faqs
    from app.retrieval.faq_retriever import _load_active_faqs, match_faq

    seed_faqs(db)
    first = _load_active_faqs(db)
    assert first and all(hasattr(r, "canonical_question") for r in first)
    # match works off the cached records
    hits = match_faq(db, "Beasiswa apa saja yang tersedia di UMB?")
    assert hits and hits[0]["source_type"] == "faq"
    cache_clear()


# --- entity cache wiring -----------------------------------------------------
def test_entity_lookup_cached_returns_copies(db):
    from app.ingestion.entity_extractor import seed_entities
    from app.retrieval.entity_retriever import query_entities

    seed_entities(db)
    r1 = query_entities(db, "dekan fakultas ilmu komputer")
    r2 = query_entities(db, "dekan fakultas ilmu komputer")
    assert r1 and r2 and r1[0]["title"] == r2[0]["title"]
    # mutating one result must not corrupt the cache (copies returned)
    r1[0]["score"] = -999
    r3 = query_entities(db, "dekan fakultas ilmu komputer")
    assert r3[0]["score"] != -999
    cache_clear()
