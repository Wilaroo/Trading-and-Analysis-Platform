"""
test_v352_backside.py — Back$ide cheat-sheet-faithful scalp (v19.34.352).

Drives EnhancedBackgroundScanner._check_backside with a fabricated `self`, 1-min bars,
snapshot, tape. Verifies the SMB Back$ide doctrine:
  • FIRES a LONG with TIGHT stop = .02 below the most-recent HIGHER LOW and target == VWAP.
  • DOES NOT fire outside the 10:00-13:30 ET window (TimeWindow gate).
  • DOES NOT fire when there is no higher low (recent low <= session LOD).
  • DOES NOT fire when entry is not below VWAP, or recovery < halfway between LOD and VWAP.
  • One-and-done: caps at 1 fire/day/symbol.

Run on DGX:  pytest backend/tests/test_v352_backside.py -q
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.enhanced_scanner import EnhancedBackgroundScanner, TimeWindow


def _bar(o, h, l, c, v=10000):
    return {"date": "2026-06-01T14:30:00+00:00", "open": o, "high": h, "low": l, "close": c, "volume": v}


def _fake_self(bars, tw=TimeWindow.MORNING_SESSION):
    return SimpleNamespace(
        technical_service=SimpleNamespace(_get_intraday_bars_from_db=lambda sym, sz, n: bars),
        _strategy_stats={},
        _backside_daily_caps={},
        _market_regime=SimpleNamespace(value="uptrend"),
        _get_current_time_window=lambda: tw,
    )


def _snap(vwap, ema9, current, above_ema9=True):
    return SimpleNamespace(vwap=vwap, ema_9=ema9, current_price=current, above_ema9=above_ema9)


def _tape(conf_long=True):
    return SimpleNamespace(confirmation_for_long=conf_long,
                           overall_signal=SimpleNamespace(value="buy"))


def _run(slf, snap, tape):
    return asyncio.new_event_loop().run_until_complete(
        EnhancedBackgroundScanner._check_backside(slf, "TEST", snap, tape))


# LOD=9.80 (bar0). Recent 5-bar low (bars4-8) = 10.20 > LOD = a HIGHER LOW.
# entry = max(prior-2 highs) = 10.38 (<VWAP 10.65, >halfway 10.225). stop = 10.18 -> RR ~1.35.
FIRE_BARS = [
    _bar(9.95, 9.98, 9.80, 9.85),    # LOD flush
    _bar(9.85, 10.00, 9.84, 9.98),
    _bar(9.98, 10.10, 9.96, 10.08),
    _bar(10.08, 10.18, 10.05, 10.15),
    _bar(10.15, 10.25, 10.20, 10.24),
    _bar(10.24, 10.30, 10.22, 10.28),
    _bar(10.28, 10.33, 10.26, 10.30),
    _bar(10.30, 10.35, 10.28, 10.32),
    _bar(10.32, 10.38, 10.30, 10.34),
    _bar(10.34, 10.46, 10.33, 10.45),  # last: green, clears 10.38, accel
]


def test_fires_higher_low_stop():
    a = _run(_fake_self(FIRE_BARS), _snap(10.65, 10.10, 10.45), _tape())
    assert a is not None, "expected a cheat-sheet backside long"
    assert a.setup_type == "backside" and a.direction == "long"
    assert abs(a.target - 10.65) < 0.001, "target must be VWAP"
    assert abs(a.stop_loss - 10.18) < 0.001, "stop must be .02 below the recent higher low (10.20)"
    assert a.risk_reward >= 1.0


def test_no_fire_outside_window():
    a = _run(_fake_self(FIRE_BARS, tw=TimeWindow.AFTERNOON), _snap(10.65, 10.10, 10.45), _tape())
    assert a is None, "must not fire outside 10:00-13:30 ET"


def test_no_fire_without_higher_low():
    # Drop a bar inside the recent window below the LOD -> no higher low.
    bars = [dict(b) for b in FIRE_BARS]
    bars[5]["low"] = 9.70   # new session LOD sits inside the recent 5-bar window
    a = _run(_fake_self(bars), _snap(10.65, 10.10, 10.45), _tape())
    assert a is None, "no higher low (recent low <= LOD) must not fire"


def test_no_fire_entry_above_vwap():
    a = _run(_fake_self(FIRE_BARS), _snap(10.30, 10.10, 10.28), _tape())
    assert a is None, "entry not below VWAP must not fire"


def test_no_fire_below_halfway():
    a = _run(_fake_self(FIRE_BARS), _snap(12.00, 10.10, 10.45), _tape())
    assert a is None, "recovery < halfway between LOD and VWAP must not fire"


def test_one_and_done():
    slf = _fake_self(FIRE_BARS)
    slf._backside_daily_caps = {}
    snap, tape = _snap(10.65, 10.10, 10.45), _tape()
    first = _run(slf, snap, tape)
    second = _run(slf, snap, tape)
    assert first is not None
    assert second is None, "one-and-done: second fire same symbol/day must be capped"
