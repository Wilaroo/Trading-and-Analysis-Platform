"""
Regression tests for the live tick → Mongo bar persister
(services/tick_to_bar_persister.py).

Locks the algorithm so future refactors can't silently break the
"PARTIAL coverage" fix that this service is supposed to deliver.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_singleton():
    from services import tick_to_bar_persister as ttb

    ttb._persister = None
    yield
    ttb._persister = None


def _fake_db():
    db = MagicMock()
    col = MagicMock()
    db.__getitem__.return_value = col
    return db, col


def _make_ts(year=2026, month=4, day=28, hour=14, minute=30, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


def test_first_push_starts_a_bucket_no_finalize_yet():
    from services import tick_to_bar_persister as ttb

    db, col = _fake_db()
    p = ttb.TickToBarPersister(db=db)

    fixed = _make_ts(minute=30, second=5)
    with patch("services.tick_to_bar_persister.datetime") as dt_mock:
        dt_mock.now.return_value = fixed
        dt_mock.fromtimestamp = datetime.fromtimestamp
        finalized = p.on_push({"SPY": {"last": 500.0, "volume": 1_000_000}})

    assert finalized == 0
    # Builders created for each of the 4 bar sizes.
    assert len(p._builders) == 4
    # Nothing upserted yet — we're mid-window for all 4.
    col.update_one.assert_not_called()


def test_window_rollover_finalizes_and_upserts_1min_bar():
    """Push at 14:30:05, then push at 14:31:05 → 1-min bucket boundary
    crossed; a single 1-min bar must be finalized & upserted."""
    from services import tick_to_bar_persister as ttb

    db, col = _fake_db()
    p = ttb.TickToBarPersister(db=db)

    t1 = _make_ts(minute=30, second=5)
    t2 = _make_ts(minute=31, second=5)

    with patch("services.tick_to_bar_persister.datetime") as dt_mock:
        dt_mock.now.return_value = t1
        dt_mock.fromtimestamp = datetime.fromtimestamp
        p.on_push({"SPY": {"last": 500.0, "volume": 1_000_000}})

    with patch("services.tick_to_bar_persister.datetime") as dt_mock:
        dt_mock.now.return_value = t1.replace(second=30)
        dt_mock.fromtimestamp = datetime.fromtimestamp
        p.on_push({"SPY": {"last": 501.5, "volume": 1_000_500}})  # high

    with patch("services.tick_to_bar_persister.datetime") as dt_mock:
        dt_mock.now.return_value = t1.replace(second=45)
        dt_mock.fromtimestamp = datetime.fromtimestamp
        p.on_push({"SPY": {"last": 499.5, "volume": 1_000_700}})  # low

    with patch("services.tick_to_bar_persister.datetime") as dt_mock:
        dt_mock.now.return_value = t2  # crosses 14:31:00 boundary
        dt_mock.fromtimestamp = datetime.fromtimestamp
        finalized = p.on_push({"SPY": {"last": 500.5, "volume": 1_000_900}})

    assert finalized == 1, "exactly one 1-min bar should close on rollover"

    # Verify the upsert payload — collect all upsert calls and find the 1m one.
    one_min_calls = [
        c for c in col.update_one.call_args_list
        if c.args[0].get("bar_size") == "1 min"
    ]
    assert len(one_min_calls) == 1, "exactly one 1-min bar must be upserted"
    set_doc = one_min_calls[0].args[1]["$set"]
    assert set_doc["symbol"] == "SPY"
    assert set_doc["bar_size"] == "1 min"
    assert set_doc["open"] == 500.0
    assert set_doc["high"] == 501.5
    assert set_doc["low"] == 499.5
    assert set_doc["close"] == 499.5  # last close before rollover
    # Volume = end_volume - start_volume within the bucket.
    assert set_doc["volume"] == 700  # 1_000_700 - 1_000_000
    assert set_doc["source"] == "live_tick"
    assert "date" in set_doc


def test_skips_invalid_quotes():
    """last <= 0 (IB sentinel for "no print") and missing data must
    not start a bucket."""
    from services import tick_to_bar_persister as ttb

    db, _col = _fake_db()
    p = ttb.TickToBarPersister(db=db)

    t = _make_ts()
    with patch("services.tick_to_bar_persister.datetime") as dt_mock:
        dt_mock.now.return_value = t
        dt_mock.fromtimestamp = datetime.fromtimestamp
        p.on_push(
            {
                "AAPL": {"last": 0, "volume": 100},      # zero last → skip
                "MSFT": {"last": None, "volume": 200},    # None last → skip
                "GOOG": {"volume": 300},                   # missing last → skip
                "VIX": {"last": 12.5, "volume": 0},       # blacklisted symbol
                "TSLA": "not-a-dict",                      # invalid shape
            }
        )

    assert len(p._builders) == 0, "no builders should be created"


def test_volume_clamps_to_zero_on_negative_delta():
    """If IB ever glitches and reports decreasing cumulative volume
    within a bucket, the computed bar volume must clamp to 0 (not go
    negative)."""
    from services import tick_to_bar_persister as ttb

    db, col = _fake_db()
    p = ttb.TickToBarPersister(db=db)

    t1 = _make_ts(minute=30, second=5)
    t2 = _make_ts(minute=31, second=5)

    with patch("services.tick_to_bar_persister.datetime") as dt_mock:
        dt_mock.now.return_value = t1
        dt_mock.fromtimestamp = datetime.fromtimestamp
        p.on_push({"SPY": {"last": 500.0, "volume": 1_000_500}})

    with patch("services.tick_to_bar_persister.datetime") as dt_mock:
        dt_mock.now.return_value = t1.replace(second=30)
        dt_mock.fromtimestamp = datetime.fromtimestamp
        p.on_push({"SPY": {"last": 500.5, "volume": 999_900}})  # IB glitch

    with patch("services.tick_to_bar_persister.datetime") as dt_mock:
        dt_mock.now.return_value = t2
        dt_mock.fromtimestamp = datetime.fromtimestamp
        p.on_push({"SPY": {"last": 501.0, "volume": 1_001_000}})

    one_min = [
        c for c in col.update_one.call_args_list
        if c.args[0].get("bar_size") == "1 min"
    ]
    assert len(one_min) == 1
    set_doc = one_min[0].args[1]["$set"]
    assert set_doc["volume"] == 0  # clamped, not negative


def test_stats_returns_introspection_dict():
    from services import tick_to_bar_persister as ttb

    db, _col = _fake_db()
    p = ttb.TickToBarPersister(db=db)

    t = _make_ts()
    with patch("services.tick_to_bar_persister.datetime") as dt_mock:
        dt_mock.now.return_value = t
        dt_mock.fromtimestamp = datetime.fromtimestamp
        p.on_push({"SPY": {"last": 500.0, "volume": 1_000_000}})

    stats = p.stats()
    assert stats["active_builders"] == 4  # 1m, 5m, 15m, 1h
    assert stats["bars_persisted_total"] == 0  # nothing finalized yet
    assert stats["ticks_observed_total"] == 1
    assert stats["bar_sizes"] == ["1 min", "5 mins", "15 mins", "1 hour"]


def test_singleton_helpers():
    from services import tick_to_bar_persister as ttb

    p1 = ttb.get_tick_to_bar_persister()
    p2 = ttb.get_tick_to_bar_persister()
    assert p1 is p2

    db, _col = _fake_db()
    p3 = ttb.init_tick_to_bar_persister(db)
    assert p3 is p1
    assert p3._db is db


def test_no_db_handle_does_not_crash():
    """If the persister is invoked before init_tick_to_bar_persister,
    it should silently no-op instead of raising into the push hot path."""
    from services import tick_to_bar_persister as ttb

    p = ttb.TickToBarPersister(db=None)
    t1 = _make_ts(minute=30, second=5)
    t2 = _make_ts(minute=31, second=5)

    with patch("services.tick_to_bar_persister.datetime") as dt_mock:
        dt_mock.now.return_value = t1
        dt_mock.fromtimestamp = datetime.fromtimestamp
        p.on_push({"SPY": {"last": 500.0, "volume": 1_000_000}})
    with patch("services.tick_to_bar_persister.datetime") as dt_mock:
        dt_mock.now.return_value = t2
        dt_mock.fromtimestamp = datetime.fromtimestamp
        finalized = p.on_push({"SPY": {"last": 500.5, "volume": 1_000_500}})

    # Bar finalized in memory but no upsert (db=None) → no exception.
    assert finalized == 1


def test_bucket_open_alignment_to_minute_boundaries():
    """Sanity — the bucket-open helper aligns to minute boundaries so
    1-min bars line up with IB's 9:30:00, 9:31:00, etc."""
    from services.tick_to_bar_persister import _bucket_open

    t = datetime(2026, 4, 28, 14, 30, 47, tzinfo=timezone.utc)
    assert _bucket_open(t, 60) == datetime(2026, 4, 28, 14, 30, 0, tzinfo=timezone.utc)
    assert _bucket_open(t, 5 * 60) == datetime(2026, 4, 28, 14, 30, 0, tzinfo=timezone.utc)
    assert _bucket_open(t, 15 * 60) == datetime(2026, 4, 28, 14, 30, 0, tzinfo=timezone.utc)
    assert _bucket_open(t, 60 * 60) == datetime(2026, 4, 28, 14, 0, 0, tzinfo=timezone.utc)
