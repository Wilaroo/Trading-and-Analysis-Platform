"""
test_v355_orb.py — Opening Range Break cheat-sheet rewrite (v19.34.355).

Drives EnhancedBackgroundScanner._check_orb with a fabricated `self`, synthetic 1-min bars
(UTC; June -> 13:30 UTC = 09:30 ET), snapshot and tape. Verifies the SMB ORB doctrine:
  • FIRES a LONG on the first break above the 15-min opening-range high WITH a volume
    expansion, STOP just below the breakout bar, TARGET = 2x the OR measured move, R:R
    gated [1.5, 2.5], during the morning window.
  • DOES NOT fire without volume expansion / outside the morning window / R:R > 2.5 /
    when an earlier post-OR bar already broke the OR high (not the first breakout).
  • Caps at 1 breakout/day per symbol.

Run on DGX:  pytest backend/tests/test_v355_orb.py -q
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.enhanced_scanner import EnhancedBackgroundScanner, TimeWindow


def _bar(hhmm, o, h, l, c, v):
    return {"date": f"2026-06-16T{hhmm}:00+00:00", "open": o, "high": h, "low": l, "close": c, "volume": v}


# 15-min OR 98.00-100.00 (height 2.0), breakout bar at 09:45 ET closes 100.50 on 3x volume.
# entry 100.50, stop 98.95 (.05% below breakout-bar low 99.00), target 104.00 (OR_high + 2*2.0),
# risk 1.55, reward 3.50 -> R:R 2.26 (inside [1.5, 2.5]).
OR_BARS = [_bar(f"13:{30 + m:02d}", 99.0, 100.0, 98.0, 99.5, 1000) for m in range(15)]
FIRE_BARS = OR_BARS + [_bar("13:45", 99.0, 101.0, 99.0, 100.50, 3000)]


def _fake_self(bars, caps=None, window=TimeWindow.MORNING_MOMENTUM):
    return SimpleNamespace(
        technical_service=SimpleNamespace(_get_intraday_bars_from_db=lambda sym, sz, n: bars),
        _orb_daily_caps={} if caps is None else caps,
        _market_regime=SimpleNamespace(value="momentum"),
        _get_current_time_window=lambda: window,
    )


def _run(slf):
    return asyncio.new_event_loop().run_until_complete(
        EnhancedBackgroundScanner._check_orb(slf, "TEST",
                                             SimpleNamespace(current_price=100.50),
                                             SimpleNamespace(confirmation_for_long=True,
                                                             overall_signal=SimpleNamespace(value="buy"))))


def test_fires_true_opening_range_break():
    a = _run(_fake_self(FIRE_BARS))
    assert a is not None and a.setup_type == "orb_long_confirmed" and a.direction == "long"
    assert abs(a.stop_loss - 98.95) < 0.01, "stop must sit just below the breakout bar"
    assert abs(a.target - 104.0) < 0.01, "target must be 2x the OR measured move"
    assert abs(a.trigger_price - 100.50) < 0.01
    assert 1.5 <= a.risk_reward <= 2.5


def test_no_fire_without_volume_expansion():
    bars = [dict(b) for b in FIRE_BARS]
    bars[-1]["volume"] = 1000
    assert _run(_fake_self(bars)) is None


def test_no_fire_outside_morning_window():
    assert _run(_fake_self(FIRE_BARS, window=SimpleNamespace(value="midday"))) is None


def test_no_fire_rr_above_band():
    # tight OR (height 1.0) + tiny breakout-bar risk -> R:R > 2.5
    bars = [_bar(f"13:{30 + m:02d}", 99.5, 100.0, 99.0, 99.6, 1000) for m in range(15)]
    bars += [_bar("13:45", 99.9, 100.6, 99.95, 100.30, 3000)]
    assert _run(_fake_self(bars)) is None


def test_no_fire_when_not_first_breakout():
    bars = list(FIRE_BARS) + [_bar("13:46", 100.5, 101.2, 100.0, 100.8, 2000)]
    assert _run(_fake_self(bars)) is None


def test_one_breakout_per_day_cap():
    slf = _fake_self(FIRE_BARS)
    first = _run(slf)
    second = _run(slf)
    assert first is not None and second is None, "max 1 ORB breakout/day/symbol"
