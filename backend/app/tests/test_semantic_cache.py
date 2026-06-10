from app.rag.semantic_cache import SemanticCache


def test_hit_for_semantically_similar_query():
    cache = SemanticCache(threshold=0.9)
    cache.put([1.0, 0.0, 0.0], {"answer": "Biaya pendaftaran Rp500.000"})
    hit = cache.get([0.99, 0.01, 0.0])  # near-paraphrase embedding
    assert hit == {"answer": "Biaya pendaftaran Rp500.000"}


def test_miss_for_dissimilar_query():
    cache = SemanticCache(threshold=0.9)
    cache.put([1.0, 0.0, 0.0], {"answer": "x"})
    assert cache.get([0.0, 1.0, 0.0]) is None


def test_empty_cache_returns_none():
    assert SemanticCache().get([1.0, 0.0]) is None


def test_returns_nearest_above_threshold():
    cache = SemanticCache(threshold=0.8)
    cache.put([1.0, 0.0], {"answer": "A"})
    cache.put([0.0, 1.0], {"answer": "B"})
    assert cache.get([0.1, 0.99]) == {"answer": "B"}
