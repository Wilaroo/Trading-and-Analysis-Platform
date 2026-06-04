"""test_post_stop_cooldown_v88.py — v19.34.88 regression tests."""
import os, time
from unittest.mock import patch
import pytest

from services.post_stop_cooldown import (
    PostStopCooldownRegistry, _base, get_registry,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reg = get_registry(); reg.clear()
    yield
    reg.clear()


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


def test_no_cooldown_when_no_stops_recorded():
    reg = get_registry()
    assert reg.is_in_cooldown("ETHU", "daily_squeeze") is False
    assert reg.seconds_remaining("ETHU", "daily_squeeze") is None


def test_record_stop_creates_cooldown():
    reg = get_registry()
    reg.record_stop("ETHU", "daily_squeeze", stop_ts=1000.0)
    assert reg.is_in_cooldown("ETHU", "daily_squeeze", now_ts=1060.0) is True


def test_long_and_short_share_same_bucket():
    reg = get_registry()
    reg.record_stop("UAL", "vwap_fade_long", stop_ts=1000.0)
    assert reg.is_in_cooldown("UAL", "vwap_fade_short", now_ts=1060.0) is True


def test_different_setup_does_not_share_bucket():
    reg = get_registry()
    reg.record_stop("UAL", "squeeze", stop_ts=1000.0)
    assert reg.is_in_cooldown("UAL", "vwap_fade", now_ts=1060.0) is False


def test_symbol_is_case_insensitive():
    reg = get_registry()
    reg.record_stop("ethu", "daily_squeeze", stop_ts=1000.0)
    assert reg.is_in_cooldown("ETHU", "daily_squeeze", now_ts=1060.0) is True


def test_cooldown_expires_after_window():
    reg = get_registry()
    reg.record_stop("CHWY", "accumulation_entry", stop_ts=1000.0)
    assert reg.is_in_cooldown("CHWY", "accumulation_entry", now_ts=2801.0) is False


def test_seconds_remaining_within_window():
    reg = get_registry()
    reg.record_stop("BALL", "accumulation_entry", stop_ts=1000.0)
    rem = reg.seconds_remaining("BALL", "accumulation_entry", now_ts=1300.0)
    assert rem is not None and 1499.0 < rem < 1501.0


def test_record_stop_with_none_symbol_is_noop():
    reg = get_registry()
    reg.record_stop(None, "vwap_fade", stop_ts=1000.0)
    assert reg.snapshot() == {}


def test_unknown_setup_still_traps_re_entry():
    reg = get_registry()
    reg.record_stop("XYZ", None, stop_ts=1000.0)
    assert reg.is_in_cooldown("XYZ", None, now_ts=1060.0) is True


def test_env_disable_returns_no_cooldown():
    reg = get_registry()
    reg.record_stop("UAL", "squeeze", stop_ts=1000.0)
    with patch.dict(os.environ, {"POST_STOP_COOLDOWN_ENABLED": "false"}):
        assert reg.is_in_cooldown("UAL", "squeeze", now_ts=1060.0) is False


def test_env_zero_minutes_returns_no_cooldown():
    reg = get_registry()
    reg.record_stop("UAL", "squeeze", stop_ts=1000.0)
    with patch.dict(os.environ, {"POST_STOP_COOLDOWN_MINUTES": "0"}):
        assert reg.seconds_remaining("UAL", "squeeze", now_ts=1060.0) is None


def test_env_custom_minutes():
    reg = get_registry()
    reg.record_stop("UAL", "squeeze", stop_ts=1000.0)
    with patch.dict(os.environ, {"POST_STOP_COOLDOWN_MINUTES": "5"}):
        assert reg.is_in_cooldown("UAL", "squeeze", now_ts=1200.0) is True
        assert reg.is_in_cooldown("UAL", "squeeze", now_ts=1350.0) is False


def test_snapshot_lists_active_cooldowns():
    reg = get_registry()
    now = time.time()
    reg.record_stop("ETHU", "daily_squeeze", stop_ts=now)
    reg.record_stop("CHWY", "accumulation_entry_long", stop_ts=now)
    snap = reg.snapshot()
    assert "ETHU/daily_squeeze" in snap
    assert "CHWY/accumulation_entry" in snap


def test_ethu_2026_05_14_scenario_blocks_4_of_5_stops():
    """Replays the actual ETHU pattern: stops 2-5 must be blocked."""
    from datetime import datetime
    reg = get_registry()
    stops = [
        "2026-05-14T12:30:37+00:00", "2026-05-14T12:35:43+00:00",
        "2026-05-14T12:41:11+00:00", "2026-05-14T12:46:37+00:00",
        "2026-05-14T12:52:10+00:00",
    ]
    epochs = [datetime.fromisoformat(s).timestamp() for s in stops]
    blocked = 0
    for ts in epochs:
        if reg.is_in_cooldown("ETHU", "daily_squeeze", now_ts=ts):
            blocked += 1
        else:
            reg.record_stop("ETHU", "daily_squeeze", stop_ts=ts)
    assert blocked == 4
