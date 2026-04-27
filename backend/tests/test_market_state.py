"""
Regression tests for the canonical market-state module.

`services/market_state.py` is the single source of truth that replaces
the duplicated ET-hour math previously scattered across:
    * services/live_bar_cache.py
    * services/backfill_readiness_service.py
    * services/enhanced_scanner.py
    * services/account_guard.py (consumer of "is the market closed?")

These tests pin the exact bucket boundaries so future refactors can't
silently drift the logic away from what `live_bar_cache` TTLs and the
trading-bot guard depend on.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.market_state import (
    classify_market_state,
    is_weekend,
    is_market_open,
    is_market_closed,
    get_snapshot,
    STATE_RTH,
    STATE_EXTENDED,
    STATE_OVERNIGHT,
    STATE_WEEKEND,
)


# ──────────────────────────────────────────────────────────────────────
# Bucket boundary tests — pinned to America/New_York wall clock.
# All UTC inputs are computed assuming standard time (UTC-5). DST days
# would shift labels by an hour, but the implementation handles that
# via zoneinfo so RTH at 14:30 UTC in winter == RTH at 13:30 UTC in
# summer; we test the winter case for stability.
# ──────────────────────────────────────────────────────────────────────


def _utc(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_weekend_saturday_is_weekend():
    sat = _utc(2026, 1, 24, 14, 0)  # Sat 09:00 ET
    assert classify_market_state(sat) == STATE_WEEKEND
    assert is_weekend(sat) is True
    assert is_market_open(sat) is False
    assert is_market_closed(sat) is True


def test_weekend_sunday_is_weekend():
    sun = _utc(2026, 1, 25, 20, 0)  # Sun 15:00 ET
    assert classify_market_state(sun) == STATE_WEEKEND


def test_rth_open_inclusive():
    # Mon Jan 26 2026 09:30 ET == 14:30 UTC (winter)
    open_bell = _utc(2026, 1, 26, 14, 30)
    assert classify_market_state(open_bell) == STATE_RTH
    assert is_market_open(open_bell) is True
    assert is_market_closed(open_bell) is False


def test_rth_close_exclusive():
    # 16:00 ET == 21:00 UTC — rolls into "extended", not RTH.
    close_bell = _utc(2026, 1, 26, 21, 0)
    assert classify_market_state(close_bell) == STATE_EXTENDED


def test_premarket_is_extended():
    # 04:00 ET == 09:00 UTC — start of pre-market.
    pre = _utc(2026, 1, 26, 9, 0)
    assert classify_market_state(pre) == STATE_EXTENDED
    # 09:29 ET == 14:29 UTC — last minute of pre-market.
    pre_end = _utc(2026, 1, 26, 14, 29)
    assert classify_market_state(pre_end) == STATE_EXTENDED


def test_post_market_is_extended():
    # 19:59 ET == 00:59 UTC next day.
    post = _utc(2026, 1, 27, 0, 59)
    assert classify_market_state(post) == STATE_EXTENDED


def test_overnight_after_post_close():
    # Mon 21:00 ET == Tue 02:00 UTC — overnight.
    overnight = _utc(2026, 1, 27, 2, 0)
    assert classify_market_state(overnight) == STATE_OVERNIGHT
    assert is_market_open(overnight) is False
    assert is_market_closed(overnight) is True
    assert is_weekend(overnight) is False


def test_extended_does_not_count_as_market_closed():
    """Critical for the trading bot — the user can opt into extended
    hours execution. is_market_closed() must NOT trip during pre/post."""
    pre = _utc(2026, 1, 26, 9, 0)
    assert is_market_closed(pre) is False
    post = _utc(2026, 1, 27, 0, 59)
    assert is_market_closed(post) is False


# ──────────────────────────────────────────────────────────────────────
# /api/market-state response shape — frontend banner depends on these
# exact keys, so they're locked in.
# ──────────────────────────────────────────────────────────────────────


def test_get_snapshot_keys_stable():
    snap = get_snapshot(_utc(2026, 1, 24, 14, 0))  # Sat
    expected_keys = {
        "state", "label", "is_weekend", "is_market_open",
        "is_market_closed", "buffers_active",
        "now_utc", "now_et", "et_weekday", "et_hhmm", "tz",
    }
    assert set(snap.keys()) == expected_keys


def test_get_snapshot_weekend_payload():
    sat = _utc(2026, 1, 24, 14, 0)
    snap = get_snapshot(sat)
    assert snap["state"] == "weekend"
    assert snap["is_weekend"] is True
    assert snap["is_market_open"] is False
    assert snap["is_market_closed"] is True
    assert snap["buffers_active"] is True
    assert snap["tz"] == "America/New_York"


def test_get_snapshot_rth_payload():
    open_bell = _utc(2026, 1, 26, 14, 30)
    snap = get_snapshot(open_bell)
    assert snap["state"] == "rth"
    assert snap["is_market_open"] is True
    assert snap["buffers_active"] is False
    # ET time for the snapshot should be 09:30 in standard time.
    assert snap["et_hhmm"] == 9 * 60 + 30


def test_get_snapshot_overnight_payload():
    overnight = _utc(2026, 1, 27, 4, 0)  # Tue 23:00 prev day ET? Actually 23:00 Mon ET
    # Mon Jan 26 2026 → 04:00 UTC Tue 27 → 23:00 ET Mon 26 → overnight.
    snap = get_snapshot(overnight)
    assert snap["state"] == "overnight"
    assert snap["buffers_active"] is True
    assert snap["is_market_closed"] is True


# ──────────────────────────────────────────────────────────────────────
# Re-export contract: live_bar_cache.classify_market_state must return
# the same answer as the canonical implementation. Locks in the
# back-compat wrapper added during the 2026-02 promotion.
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("when", [
    _utc(2026, 1, 24, 14, 0),   # Sat
    _utc(2026, 1, 26, 14, 30),  # Mon RTH open
    _utc(2026, 1, 26, 18, 0),   # Mon mid-RTH
    _utc(2026, 1, 26, 21, 0),   # Mon close → extended
    _utc(2026, 1, 27, 4, 0),    # Mon overnight (UTC Tue 04:00)
])
def test_live_bar_cache_reexport_matches_canonical(when):
    from services.live_bar_cache import classify_market_state as legacy
    assert legacy(when) == classify_market_state(when)
