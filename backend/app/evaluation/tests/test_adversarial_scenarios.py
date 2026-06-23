import random

from app.evaluation import adversarial_scenarios as a


def _rng(seed=1):
    return random.Random(seed)


def test_make_typo_changes_string_deterministically():
    q = "Siapa dekan Fakultas Psikologi UMB"
    out1 = a.make_typo(q, _rng(7))
    out2 = a.make_typo(q, _rng(7))
    assert out1 == out2          # deterministic per seed
    assert out1 != q             # changed something
    assert abs(len(out1) - len(q)) <= 3   # light edit only


def test_make_incomplete_is_strict_prefix():
    q = "Siapa dekan Fakultas Psikologi Universitas Mercu Buana"
    out = a.make_incomplete(q, _rng(3))
    assert out is not None
    words = q.split()
    assert out.split() == words[: len(out.split())]   # prefix of the original
    assert 2 <= len(out.split()) < len(words)


def test_make_incomplete_none_when_too_short():
    assert a.make_incomplete("Halo", _rng(1)) is None
    assert a.make_incomplete("Dua kata", _rng(1)) is None


def test_make_mixed_lang_replaces_known_token():
    out = a.make_mixed_lang("Siapa dekan fakultas Psikologi", _rng(2))
    assert out is not None
    assert out.lower() != "siapa dekan fakultas psikologi"
    assert any(w in out.lower() for w in ("who", "faculty"))


def test_make_mixed_lang_none_when_no_known_token():
    assert a.make_mixed_lang("xyz qrs tuv", _rng(1)) is None


def test_make_ambiguous_is_shorter_and_generic():
    q = "Siapa dekan Fakultas Psikologi Universitas Mercu Buana?"
    out = a.make_ambiguous(q, _rng(5))
    assert out is not None
    assert len(out) < len(q)


def test_perturb_tags_carries_base_and_is_deterministic():
    base = "Siapa dekan Fakultas Psikologi UMB"
    rows = a.perturb(base, base_id="q1", intent="faculty", seed=42)
    assert {r["perturbation_type"] for r in rows} <= {"typo", "incomplete", "mixed_lang", "ambiguous"}
    assert all(r["base_id"] == "q1" and r["intent"] == "faculty" for r in rows)
    assert all(r["query"] and r["query"] != base for r in rows)   # no no-op variants
    assert rows == a.perturb(base, base_id="q1", intent="faculty", seed=42)   # deterministic
