from app.trust.authority import host_authority
from app.trust.freshness import freshness


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
