from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.trust.recrawl import prioritize_recrawl, recrawl_priority

_NOW = datetime(2026, 6, 7, tzinfo=timezone.utc)


def _src(title, fetched_at):
    return SimpleNamespace(title=title, path=None, url=None, fetched_at=fetched_at)


def test_volatile_stale_source_recrawls_before_stable_stale():
    volatile_stale = _src("Biaya Pendaftaran UKT", _NOW - timedelta(days=60))
    stable_stale = _src("Visi dan Misi", _NOW - timedelta(days=60))
    ordered = prioritize_recrawl([stable_stale, volatile_stale], now=_NOW)
    assert ordered[0] is volatile_stale


def test_fresh_volatile_source_is_lowest_priority():
    volatile_fresh = _src("Biaya Pendaftaran UKT", _NOW - timedelta(hours=1))
    volatile_stale = _src("Biaya Pendaftaran UKT", _NOW - timedelta(days=60))
    ordered = prioritize_recrawl([volatile_fresh, volatile_stale], now=_NOW)
    assert ordered[0] is volatile_stale
    assert ordered[-1] is volatile_fresh


def test_recrawl_priority_increases_with_staleness():
    older = recrawl_priority(title="Biaya UKT", fetched_at=_NOW - timedelta(days=60), now=_NOW)
    newer = recrawl_priority(title="Biaya UKT", fetched_at=_NOW - timedelta(hours=1), now=_NOW)
    assert older > newer
