"""
Regression tests for the 9 detector functions added 2026-04-29 evening:

  Orphan-setup detectors (previously in `_enabled_setups` but with no
  checker function, surfacing as `orphan_enabled_setups` in the
  `/api/scanner/setup-coverage` diagnostic):
      1. first_move_up      — SHORT (fade first morning push to HOD)
      2. first_move_down    — LONG  (fade first morning flush to LOD)
      3. back_through_open  — SHORT (failed morning push, cross back below open)
      4. up_through_open    — LONG  (recovered morning flush, cross above open)
      5. gap_pick_roll      — LONG  (gap-up holding, riding 9-EMA continuation)
      6. bella_fade         — SHORT (parabolic above-VWAP fade)

  Operator playbook setups (added from 2026-04-29 screenshots):
      7. vwap_continuation  — LONG  (re-entry near VWAP after morning trend)
      8. premarket_high_break — LONG (first-5min OR break with strong gap)
      9. bouncy_ball        — SHORT (failed-bounce support break)

The tests validate three contracts:
  - The detectors are registered in `checkers` dict in `_check_setup`.
  - The detectors are in `REGISTERED_SETUP_TYPES` (so `setup-coverage`
    no longer flags them as orphans).
  - Each detector fires (returns a `LiveAlert`) on a hand-crafted
    snapshot matching its trigger conditions, and returns `None` on a
    snapshot that fails one or more conditions.

These tests do NOT require live IB data — they construct fake
`TechnicalSnapshot` and `TapeReading` objects in-memory.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, "/app/backend")

from services.enhanced_scanner import (  # noqa: E402
    EnhancedBackgroundScanner,
    TapeReading,
    TapeSignal,
    STRATEGY_TIME_WINDOWS,
    TimeWindow,
)
from services.realtime_technical_service import TechnicalSnapshot  # noqa: E402


NEW_SETUPS = [
    "first_move_up", "first_move_down", "back_through_open",
    "up_through_open", "gap_pick_roll", "bella_fade",
    "vwap_continuation", "premarket_high_break", "bouncy_ball",
]


def _snapshot(**overrides) -> TechnicalSnapshot:
    """Build a baseline 'flat-but-valid' TechnicalSnapshot."""
    base = dict(
        symbol="TEST", timestamp="2026-04-29T15:00:00",
        current_price=100.0, open=100.0, high=100.5, low=99.5, prev_close=99.0,
        volume=1_000_000, avg_volume=800_000, rvol=1.0,
        vwap=100.0, ema_9=100.0, ema_20=100.0, ema_50=100.0, sma_200=100.0,
        dist_from_vwap=0.0, dist_from_ema9=0.0, dist_from_ema20=0.0,
        rsi_14=50.0, rsi_trend="neutral",
        atr=1.0, atr_percent=1.0, daily_range_pct=1.0,
        gap_pct=0.0, gap_direction="flat", holding_gap=False,
        resistance=102.0, support=98.0, high_of_day=100.5, low_of_day=99.5,
        above_vwap=True, above_ema9=True, above_ema20=True, trend="sideways",
        extended_from_ema9=False, extension_pct=0.0,
        bb_upper=102.0, bb_middle=100.0, bb_lower=98.0, bb_width=4.0,
        kc_upper=101.5, kc_middle=100.0, kc_lower=98.5,
        squeeze_on=False, squeeze_fire=0.0,
        or_high=100.5, or_low=99.5, or_breakout="inside",
        rs_vs_spy=0.0, bars_used=20, data_quality="real",
    )
    base.update(overrides)
    return TechnicalSnapshot(**base)


def _tape(long_ok: bool = True, short_ok: bool = True) -> TapeReading:
    return TapeReading(
        symbol="TEST", timestamp="2026-04-29T15:00:00",
        bid_price=99.99, ask_price=100.01, spread=0.02, spread_pct=0.02,
        spread_signal=TapeSignal.TIGHT_SPREAD,
        bid_size=100, ask_size=100, imbalance=0.0,
        imbalance_signal=TapeSignal.NEUTRAL,
        price_momentum=0.0, volume_momentum=0.0,
        momentum_signal=TapeSignal.NEUTRAL,
        overall_signal=TapeSignal.NEUTRAL, tape_score=0.0,
        confirmation_for_long=long_ok, confirmation_for_short=short_ok,
    )


def _scanner() -> EnhancedBackgroundScanner:
    s = EnhancedBackgroundScanner(db=None)
    return s


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ──────────────────────────── REGISTRATION ────────────────────────────


def test_all_new_setups_registered_in_checkers_and_frozenset():
    """Every new setup MUST be in both the `checkers` dict in
    `_check_setup` AND the class-level `REGISTERED_SETUP_TYPES`
    frozenset, so `/api/scanner/setup-coverage` reports them as
    `active_detectors` / `silent_detectors` (not `orphan_enabled_setups`)."""
    src = Path("/app/backend/services/enhanced_scanner.py").read_text("utf-8")
    fn_idx = src.index("async def _check_setup(self,")
    body_end = src.index("REGISTERED_SETUP_TYPES", fn_idx)
    body = src[fn_idx:body_end]
    for setup in NEW_SETUPS:
        assert f'"{setup}":' in body, f"`{setup}` missing from checkers dict"
    for setup in NEW_SETUPS:
        assert f'"{setup}"' in src[body_end:body_end + 2000], (
            f"`{setup}` missing from REGISTERED_SETUP_TYPES"
        )


def test_three_playbook_setups_in_enabled_set():
    """The 3 new playbook setups must be in `_enabled_setups` (the 6
    orphans were already there)."""
    s = _scanner()
    for setup in ("vwap_continuation", "premarket_high_break", "bouncy_ball"):
        assert setup in s._enabled_setups, f"`{setup}` not in _enabled_setups"


def test_three_playbook_setups_in_strategy_time_windows():
    """Each new playbook setup must declare a non-empty time-window
    list so `_is_setup_valid_now` doesn't filter it out everywhere."""
    for setup in ("vwap_continuation", "premarket_high_break", "bouncy_ball"):
        windows = STRATEGY_TIME_WINDOWS.get(setup)
        assert windows, f"`{setup}` not in STRATEGY_TIME_WINDOWS"
        assert isinstance(windows, list) and len(windows) >= 1
        assert all(isinstance(w, TimeWindow) for w in windows)


# ──────────────────────────── DETECTOR FIRING ────────────────────────────


def test_first_move_up_short_fires_on_overbought_hod_push():
    s = _scanner()
    snap = _snapshot(
        current_price=102.5, open=100.0, high=103.0, low=100.0,
        high_of_day=103.0, low_of_day=100.0, vwap=101.0, ema_9=102.0,
        dist_from_vwap=1.5, dist_from_ema9=0.5, rsi_14=72,
        rvol=2.0, atr=1.0, above_vwap=True,
    )
    alert = _run(s._check_first_move_up("TEST", snap, _tape(short_ok=True)))
    assert alert is not None
    assert alert.direction == "short"
    assert alert.setup_type == "first_move_up"
    assert alert.stop_loss > snap.high_of_day  # stop above HOD


def test_first_move_up_does_not_fire_when_rsi_neutral():
    s = _scanner()
    snap = _snapshot(
        current_price=102.5, open=100.0, high_of_day=103.0,
        dist_from_vwap=1.5, rsi_14=55, rvol=2.0, atr=1.0,
    )
    assert _run(s._check_first_move_up("TEST", snap, _tape())) is None


def test_first_move_down_long_fires_on_oversold_lod_flush():
    s = _scanner()
    snap = _snapshot(
        current_price=97.3, open=100.0, high=100.0, low=97.0,
        high_of_day=100.0, low_of_day=97.0, vwap=99.0, ema_9=98.0,
        dist_from_vwap=-1.7, rsi_14=28, rvol=2.0, atr=1.0,
        above_vwap=False, above_ema9=False,
    )
    alert = _run(s._check_first_move_down("TEST", snap, _tape(long_ok=True)))
    assert alert is not None
    assert alert.direction == "long"
    assert alert.setup_type == "first_move_down"
    assert alert.stop_loss < snap.low_of_day


def test_back_through_open_short_fires_on_failed_morning_push():
    s = _scanner()
    snap = _snapshot(
        current_price=99.7, open=100.0, high=101.0, low=98.5,
        high_of_day=101.0, low_of_day=98.5, vwap=100.2, ema_9=100.0,
        dist_from_vwap=-0.5, rvol=1.5, atr=1.0,
        above_vwap=False, above_ema9=False,
    )
    alert = _run(s._check_back_through_open("TEST", snap, _tape(short_ok=True)))
    assert alert is not None
    assert alert.direction == "short"
    assert alert.stop_loss > snap.open


def test_back_through_open_does_not_fire_when_no_prior_push():
    s = _scanner()
    snap = _snapshot(
        current_price=99.7, open=100.0, high=100.1, low=99.5,
        high_of_day=100.1, low_of_day=99.5,  # only 0.1% push above open
        rvol=1.5, atr=1.0, above_ema9=False,
    )
    assert _run(s._check_back_through_open("TEST", snap, _tape())) is None


def test_up_through_open_long_fires_on_recovered_flush():
    s = _scanner()
    snap = _snapshot(
        current_price=100.3, open=100.0, high=101.5, low=99.0,
        high_of_day=101.5, low_of_day=99.0, vwap=99.8, ema_9=100.1,
        dist_from_vwap=0.5, rvol=1.5, atr=1.0,
        above_vwap=True, above_ema9=True,
    )
    alert = _run(s._check_up_through_open("TEST", snap, _tape(long_ok=True)))
    assert alert is not None
    assert alert.direction == "long"
    assert alert.stop_loss < snap.open


def test_gap_pick_roll_fires_on_gap_holding_above_ema9():
    s = _scanner()
    snap = _snapshot(
        current_price=102.5, open=102.0, prev_close=100.0,
        high=103.0, low=101.5, high_of_day=103.0, low_of_day=101.5,
        gap_pct=2.0, holding_gap=True, vwap=101.8, ema_9=102.3,
        dist_from_vwap=0.7, dist_from_ema9=0.2, rsi_14=58,
        rvol=2.0, atr=1.0, above_vwap=True, above_ema9=True,
    )
    alert = _run(s._check_gap_pick_roll("TEST", snap, _tape(long_ok=True)))
    assert alert is not None
    assert alert.direction == "long"
    assert alert.setup_type == "gap_pick_roll"


def test_bella_fade_fires_on_parabolic_extension():
    s = _scanner()
    snap = _snapshot(
        current_price=104.0, open=100.0, high=104.5, low=99.5,
        high_of_day=104.5, low_of_day=99.5, vwap=101.5, ema_9=102.0,
        dist_from_vwap=2.5, dist_from_ema9=2.0, rsi_14=78,
        rvol=2.5, atr=1.0, above_vwap=True,
    )
    alert = _run(s._check_bella_fade("TEST", snap, _tape(short_ok=True)))
    assert alert is not None
    assert alert.direction == "short"
    assert alert.setup_type == "bella_fade"


def test_bella_fade_skips_when_not_overextended():
    s = _scanner()
    snap = _snapshot(
        current_price=101.0, dist_from_vwap=1.0, dist_from_ema9=0.5,
        rsi_14=68, rvol=1.5, atr=1.0,
    )
    assert _run(s._check_bella_fade("TEST", snap, _tape())) is None


def test_vwap_continuation_fires_on_pullback_after_morning_strength():
    s = _scanner()
    snap = _snapshot(
        current_price=102.0, open=100.0, high=103.5, low=99.8,
        high_of_day=103.5, low_of_day=99.8, vwap=102.1, ema_9=102.0,
        dist_from_vwap=-0.1, dist_from_ema9=0.0, rsi_14=55,
        rvol=1.5, atr=1.0, above_vwap=True, above_ema9=True,
        trend="uptrend",
    )
    alert = _run(s._check_vwap_continuation("TEST", snap, _tape(long_ok=True)))
    assert alert is not None
    assert alert.direction == "long"
    assert alert.setup_type == "vwap_continuation"


def test_premarket_high_break_fires_in_opening_drive_window(monkeypatch):
    s = _scanner()
    # Pin the time window to OPENING_DRIVE (the only window the check allows)
    monkeypatch.setattr(s, "_get_current_time_window", lambda: TimeWindow.OPENING_DRIVE)
    snap = _snapshot(
        current_price=101.0, open=100.5, prev_close=99.0,
        high=101.0, low=100.4, high_of_day=101.0, low_of_day=100.4,
        gap_pct=1.5, holding_gap=True, or_high=100.8, or_low=100.4,
        or_breakout="above", vwap=100.6, ema_9=100.7,
        dist_from_vwap=0.4, rvol=2.5, atr=1.0,
        above_vwap=True, above_ema9=True,
    )
    alert = _run(s._check_premarket_high_break("TEST", snap, _tape(long_ok=True)))
    assert alert is not None
    assert alert.direction == "long"
    assert alert.setup_type == "premarket_high_break"


def test_premarket_high_break_blocked_outside_opening_window(monkeypatch):
    s = _scanner()
    monkeypatch.setattr(s, "_get_current_time_window", lambda: TimeWindow.MIDDAY)
    snap = _snapshot(
        current_price=101.0, open=100.5, gap_pct=1.5, holding_gap=True,
        or_breakout="above", or_high=100.8, rvol=2.5, atr=1.0,
        above_vwap=True,
    )
    assert _run(s._check_premarket_high_break("TEST", snap, _tape())) is None


def test_bouncy_ball_short_fires_on_failed_bounce_support_break():
    s = _scanner()
    snap = _snapshot(
        current_price=98.0, open=100.0, high=99.5, low=98.0,
        high_of_day=99.5, low_of_day=98.0, vwap=99.5, ema_9=98.5,
        dist_from_vwap=-1.5, rsi_14=42, rvol=1.5, atr=1.0,
        above_vwap=False, above_ema9=False,
    )
    alert = _run(s._check_bouncy_ball("TEST", snap, _tape(short_ok=True)))
    assert alert is not None
    assert alert.direction == "short"
    assert alert.setup_type == "bouncy_ball"


def test_bouncy_ball_skips_when_overextended_from_vwap():
    """Operator playbook: avoid this trade if the opening drop is
    overextended from VWAP — encoded as the −3% lower bound."""
    s = _scanner()
    snap = _snapshot(
        current_price=95.0, open=100.0, low_of_day=95.0,
        dist_from_vwap=-5.0, rsi_14=42, rvol=1.5, atr=1.0,
        above_vwap=False, above_ema9=False,
    )
    assert _run(s._check_bouncy_ball("TEST", snap, _tape())) is None
