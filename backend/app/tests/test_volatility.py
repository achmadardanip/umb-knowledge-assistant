from app.trust.volatility import half_life_for_volatility, query_volatility


def test_volatility_high_for_fees_and_deadlines():
    assert query_volatility("Berapa biaya pendaftaran semester ini?") >= 0.7
    assert query_volatility("Kapan batas akhir pembayaran UKT?") >= 0.7


def test_volatility_low_for_vision_and_history():
    assert query_volatility("Apa visi dan misi Universitas Mercu Buana?") <= 0.3
    assert query_volatility("Bagaimana sejarah berdirinya UMB?") <= 0.3


def test_volatility_detects_english_time_sensitive_terms():
    assert query_volatility("What is the tuition fee payment deadline?") >= 0.7


def test_volatility_defaults_to_medium_for_neutral_query():
    assert 0.3 < query_volatility("Di mana perpustakaan kampus?") < 0.7


def test_half_life_is_shorter_for_higher_volatility():
    assert half_life_for_volatility(0.9) < half_life_for_volatility(0.1)
