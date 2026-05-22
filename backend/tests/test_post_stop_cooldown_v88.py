"""
test_post_stop_cooldown_v88.py — v19.34.88 regression tests.

Exercises the post-stop cooldown registry's writer/reader contract
without touching Mongo or the live bot. The registry is module-level
singleton state, so each test resets it via clear().
"""
import os
import time
from unittest.mock import patch

import pytest

from services.post_stop_cooldown import (
    PostStopCooldownRegistry,
    _base,
    get_registry,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Each test gets a clean registry."""
    reg = get_registry()
    reg.clear()
    yield
    reg.clear()


# ── _base() normalisation ────────────────────────────────────────────

def test_base_drops_long_suffix():
    assert _base("vwap_fade_long") == "vwap_fade"


def test_base_drops_short_suffix():
    assert _base("vwap_fade_short") == "vwap_fade"


def test_base_unchanged_when_no_suffix():
    assert _base("squeeze") == "squeeze"


def test_base_handles_none():
    assert _base(None) == ""


def test_base_handles_empty_string():
    assert _base("") == ""


def test_base_strips_underscore_l():
    assert _base("vwap_fade_l") == "vwap_fade"


def test_base_lowercases():
    assert _base("Vwap_Fade_LONG") == "vwap_fade"


# ── writer / reader contract ─────────────────────────────────────────

def test_no_cooldown_when_no_stops_recorded():
    reg = get_registry()
    assert reg.is_in_cooldown("ETHU", "daily_squeeze") is False
    assert reg.seconds_remaining("ETHU", "daily_squeeze") is None


def test_record_stop_creates_cooldown():
    reg = get_registry()
    reg.record_stop("ETHU", "daily_squeeze", stop_ts=1000.0)
    assert reg.is_in_cooldown("ETHU", "daily_squeeze", now_ts=1060.0) is True


def test_long_and_short_share_same_bucket():
    """vwap_fade_long stop should block vwap_fade_short entry."""
    reg = get_registry()
    reg.record_stop("UAL", "vwap_fade_long", stop_ts=1000.0)
    assert reg.is_in_cooldown("UAL", "vwap_fade_short", now_ts=1060.0) is True


def test_different_setup_does_not_share_bucket():
    """Stop on squeeze should NOT block a fresh vwap_fade entry."""
    reg = get_registry()
    reg.record_stop("UAL", "squeeze", stop_ts=1000.0)
    assert reg.is_in_cooldown("UAL", "vwap_fade", now_ts=1060.0) is False


def test_symbol_is_case_insensitive():
    reg = get_registry()
    reg.record_stop("ethu", "daily_squeeze", stop_ts=1000.0)
    assert reg.is_in_cooldown("ETHU", "daily_squeeze", now_ts=1060.0) is True
    assert reg.is_in_cooldown("Ethu", "daily_squeeze", now_ts=1060.0) is True


def test_cooldown_expires_after_window():
    """Default window is 30 min = 1800s. Past that, gate releases."""
    reg = get_registry()
    reg.record_stop("CHWY", "accumulation_entry", stop_ts=1000.0)
    # 1801s later → cooldown ended
    assert reg.is_in_cooldown(
        "CHWY", "accumulation_entry", now_ts=2801.0,
    ) is False


def test_seconds_remaining_within_window():
    reg = get_registry()
    reg.record_stop("BALL", "accumulation_entry", stop_ts=1000.0)
    rem = reg.seconds_remaining(
        "BALL", "accumulation_entry", now_ts=1300.0,
    )
    assert rem is not None
    # 300s elapsed of 1800s window → 1500s left
    assert 1499.0 < rem < 1501.0


def test_record_stop_with_none_symbol_is_noop():
    reg = get_registry()
    reg.record_stop(None, "vwap_fade", stop_ts=1000.0)
    snap = reg.snapshot()
    assert snap == {}


def test_unknown_setup_still_traps_re_entry():
    """If setup_type is None, the cooldown should still bind to the
    symbol so any follow-up trade is paused."""
    reg = get_registry()
    reg.record_stop("XYZ", None, stop_ts=1000.0)
    # Re-entry attempt with same None setup → blocked
    assert reg.is_in_cooldown("XYZ", None, now_ts=1060.0) is True


def test_env_disable_returns_no_cooldown():
    reg = get_registry()
    reg.record_stop("UAL", "squeeze", stop_ts=1000.0)
    with patch.dict(os.environ, {"POST_STOP_COOLDOWN_ENABLED": "false"}):
        assert reg.is_in_cooldown("UAL", "squeeze", now_ts=1060.0) is False
        assert reg.seconds_remaining("UAL", "squeeze", now_ts=1060.0) is None


def test_env_zero_minutes_returns_no_cooldown():
    reg = get_registry()
    reg.record_stop("UAL", "squeeze", stop_ts=1000.0)
    with patch.dict(os.environ, {"POST_STOP_COOLDOWN_MINUTES": "0"}):
        assert reg.seconds_remaining("UAL", "squeeze", now_ts=1060.0) is None


def test_env_custom_minutes():
    reg = get_registry()
    reg.record_stop("UAL", "squeeze", stop_ts=1000.0)
    with patch.dict(os.environ, {"POST_STOP_COOLDOWN_MINUTES": "5"}):
        # 5min = 300s. After 200s: still in cooldown.
        assert reg.is_in_cooldown("UAL", "squeeze", now_ts=1200.0) is True
        # After 350s: released.
        assert reg.is_in_cooldown("UAL", "squeeze", now_ts=1350.0) is False


# ── snapshot diagnostic ─────────────────────────────────────────────

def test_snapshot_lists_active_cooldowns():
    reg = get_registry()
    now = time.time()
    reg.record_stop("ETHU", "daily_squeeze", stop_ts=now)
    reg.record_stop("CHWY", "accumulation_entry_long", stop_ts=now)
    snap = reg.snapshot()
    assert "ETHU/daily_squeeze" in snap
    assert "CHWY/accumulation_entry" in snap
    assert snap["ETHU/daily_squeeze"]["in_cooldown"] is True
    assert snap["CHWY/accumulation_entry"]["in_cooldown"] is True


# ── ETHU re-entry scenario from 2026-05-14 ──────────────────────────

def test_ethu_2026_05_14_scenario_blocks_4_of_5_stops():
    """Replays the actual 2026-05-14 ETHU pattern:
      stop 1 at 12:30:37  → first hit, no prior cooldown
      stop 2 at 12:35:43  → SHOULD be blocked (5min after stop 1)
      stop 3 at 12:41:11  → SHOULD be blocked
      stop 4 at 12:46:37  → SHOULD be blocked
      stop 5 at 12:52:10  → SHOULD be blocked

    With v88's 30-min cooldown, stops 2-5 should never have been
    entered → -1.20R losses prevented = ~$4.8k saved on this symbol.
    """
    from datetime import datetime
    reg = get_registry()
    stops = [
        "2026-05-14T12:30:37+00:00",
        "2026-05-14T12:35:43+00:00",
        "2026-05-14T12:41:11+00:00",
        "2026-05-14T12:46:37+00:00",
        "2026-05-14T12:52:10+00:00",
    ]
    epochs = [
        datetime.fromisoformat(s).timestamp() for s in stops
    ]
    blocked = 0
    for ts in epochs:
        if reg.is_in_cooldown("ETHU", "daily_squeeze", now_ts=ts):
            blocked += 1
        else:
            reg.record_stop("ETHU", "daily_squeeze", stop_ts=ts)
    assert blocked == 4, (
        f"Expected 4 re-entries blocked, got {blocked}. "
        f"Cooldown window must be < 22min (full span)."
    )
