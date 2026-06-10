from app.trust.va_jit import should_reverify, va_jit_reverify


def test_trigger_fires_for_volatile_stale_fact():
    assert should_reverify(volatility=0.9, best_freshness=0.2, corroboration=3) is True


def test_trigger_skips_volatile_but_fresh_and_corroborated():
    assert should_reverify(volatility=0.9, best_freshness=0.95, corroboration=3) is False


def test_trigger_skips_low_volatility_even_if_stale():
    assert should_reverify(volatility=0.2, best_freshness=0.1, corroboration=1) is False


def test_trigger_fires_for_volatile_under_corroborated():
    # Fresh but only one authoritative source asserting a volatile fact -> re-verify.
    assert should_reverify(volatility=0.9, best_freshness=0.95, corroboration=1) is True


def test_va_jit_reverify_fetches_when_triggered():
    contexts = [{"hostname": "pmb.mercubuana.ac.id", "freshness": 0.1}]  # volatile + stale

    def fake_fetcher(query, *, budget):
        return [{"url": "https://pmb.mercubuana.ac.id/live", "hostname": "pmb.mercubuana.ac.id", "chunk_text": "Biaya terbaru.", "freshness": 1.0}]

    fresh = va_jit_reverify("biaya pendaftaran", contexts, fetcher=fake_fetcher, budget=2)
    assert fresh and fresh[0]["url"].endswith("/live")


def test_va_jit_reverify_is_budget_bounded():
    contexts = [{"hostname": "pmb.mercubuana.ac.id", "freshness": 0.1}]

    def greedy_fetcher(query, *, budget):
        return [{"url": f"https://pmb.mercubuana.ac.id/{i}"} for i in range(10)]

    fresh = va_jit_reverify("biaya pendaftaran", contexts, fetcher=greedy_fetcher, budget=2)
    assert len(fresh) == 2


def test_va_jit_reverify_skips_when_not_triggered():
    contexts = [{"hostname": "a.mercubuana.ac.id", "freshness": 0.99}, {"hostname": "b.mercubuana.ac.id", "freshness": 0.99}]
    calls = []

    def fake_fetcher(query, *, budget):
        calls.append(1)
        return [{"url": "x"}]

    fresh = va_jit_reverify("apa visi dan misi umb", contexts, fetcher=fake_fetcher)  # low volatility
    assert fresh == []
    assert not calls
