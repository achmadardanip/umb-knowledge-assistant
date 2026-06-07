from datetime import datetime, timedelta, timezone

from app.trust.authority import host_authority
from app.trust.freshness import freshness, freshness_from_age


def test_authority_zero_for_out_of_scope_or_lookalike_host():
    assert host_authority("evil.com") == 0.0
    # Subdomain-takeover / lookalike host must not borrow the registrar's authority.
    assert host_authority("mercubuana.ac.id.evil.com") == 0.0


def test_authority_high_for_official_functional_subdomain():
    assert host_authority("pmb.mercubuana.ac.id") >= 0.8


def test_authority_registrar_root_is_high():
    assert host_authority("mercubuana.ac.id") >= 0.8


def test_authority_medium_for_unknown_in_scope_subdomain():
    score = host_authority("klubmahasiswa.mercubuana.ac.id")
    assert 0.0 < score < 0.8


def test_freshness_full_at_zero_age_and_half_at_one_half_life():
    assert freshness(0, half_life_seconds=86400) == 1.0
    assert freshness(86400, half_life_seconds=86400) == 0.5


def test_freshness_decreases_with_age():
    assert freshness(2 * 86400, 86400) < freshness(86400, 86400)


_NOW = datetime(2026, 6, 7, tzinfo=timezone.utc)


def test_freshness_from_age_recent_high_volatility_is_fresh():
    assert freshness_from_age(_NOW - timedelta(hours=2), 0.9, now=_NOW) > 0.9


def test_freshness_from_age_old_high_volatility_is_stale():
    # half-life for v=0.9 is ~19 days, so 60 days is very stale
    assert freshness_from_age(_NOW - timedelta(days=60), 0.9, now=_NOW) < 0.2


def test_freshness_from_age_old_low_volatility_still_fresh():
    # half-life for v=0.1 is ~162 days, so 60 days is still fresh
    assert freshness_from_age(_NOW - timedelta(days=60), 0.1, now=_NOW) > 0.7


def test_freshness_from_age_unknown_timestamp_is_neutral():
    assert freshness_from_age(None, 0.9) == 1.0
