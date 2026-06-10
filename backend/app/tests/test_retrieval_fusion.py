from app.retrieval.fusion import reciprocal_rank_fusion, tahf_score


def test_rrf_promotes_items_with_cross_list_consensus():
    # 'y' is #2 in both lists; 'x' and 'z' are #1 in only one list each.
    list1 = ["x", "y"]
    list2 = ["z", "y"]
    fused = dict(reciprocal_rank_fusion([list1, list2], k=1))
    assert max(fused, key=fused.get) == "y"


def test_rrf_top_two_are_items_present_in_both_lists():
    dense = ["a", "b", "c"]
    sparse = ["b", "a", "d"]
    ids = [item for item, _ in reciprocal_rank_fusion([dense, sparse], k=60)]
    assert set(ids[:2]) == {"a", "b"}


def test_rrf_handles_empty_lists():
    assert reciprocal_rank_fusion([[], []]) == []


def test_tahf_adds_weighted_authority_and_freshness():
    assert tahf_score(1.0, authority=0.8, freshness=0.5, alpha=0.5, beta=0.2) == 1.0 + 0.4 + 0.1


def test_tahf_with_zero_priors_returns_relevance():
    assert tahf_score(2.0, authority=0.0, freshness=0.0, alpha=1.0, beta=1.0) == 2.0


def test_tahf_higher_authority_wins_at_equal_relevance():
    high = tahf_score(1.0, authority=0.9, freshness=0.5, alpha=1.0, beta=0.5)
    low = tahf_score(1.0, authority=0.2, freshness=0.5, alpha=1.0, beta=0.5)
    assert high > low
