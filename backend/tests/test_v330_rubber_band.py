"""v19.34.322 (v330) — rubber_band SMB snapback detector regression.

Run on the DGX AFTER applying patch_v330_rubber_band_snapback.py:
    PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/test_v330_rubber_band.py -q

Drives the real _check_rubber_band via a lightweight fake `self` (no full __init__),
stubbing technical_service to return synthetic 1-min bars. Validates the TRIGGER
semantics (event, not state), the long/short double-bar-break, RVOL gate, and the
2/day cap.
"""
import asyncio
from types import SimpleNamespace

import pytest

from services.enhanced_scanner import EnhancedScanner, AlertPriority  # noqa: F401


def _bar(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c, "volume": 10000}


# Open 100; flush to 97.9 (=2.1% below open) at idx3 with an accel range; then a
# green bar at idx5 clears the prior-2 highs => LONG snapback, +2 bars from LOD.
LONG_BARS = [
    _bar(100.0, 100.10, 99.80, 99.90),   # 0 session open
    _bar(99.90, 99.95, 99.30, 99.40),    # 1
    _bar(99.40, 99.50, 98.60, 98.70),    # 2
    _bar(98.70, 98.80, 97.90, 98.00),    # 3 LOD (flush, big range)
    _bar(98.00, 98.60, 97.95, 98.50),    # 4 green, high 98.60 (does not clear 98.80)
    _bar(98.50, 99.00, 98.40, 98.95),    # 5 green, high 99.00 > max(98.60, 98.80) -> CLEARS
]

# Open 100; spike to 102.1 (=2.1% above open) at idx3; red bar at idx5 breaks the
# prior-2 lows => SHORT snapback.
SHORT_BARS = [
    _bar(100.0, 100.20, 99.90, 100.10),  # 0 open
    _bar(100.10, 100.70, 100.05, 100.60),  # 1
    _bar(100.60, 101.40, 100.50, 101.30),  # 2
    _bar(101.30, 102.10, 101.20, 102.00),  # 3 HOD (spike, big range)
    _bar(102.00, 102.05, 101.40, 101.50),  # 4 red, low 101.40 (does not break 101.20)
    _bar(101.50, 101.60, 101.00, 101.05),  # 5 red, low 101.00 < min(101.40, 101.20) -> BREAKS
]


def _fake_self(bars):
    return SimpleNamespace(
        technical_service=SimpleNamespace(
            _get_intraday_bars_from_db=lambda sym, bs, n: list(bars)),
        _strategy_stats={},
        _get_current_time_window=lambda: SimpleNamespace(value="midday"),
        _market_regime=SimpleNamespace(value="range_bound"),
    )


def _snapshot(direction):
    # current_price = last close; ema_9 set so the mean-revert target is on the
    # correct side of entry (above for long, below for short).
    if direction == "long":
        return SimpleNamespace(open=100.0, current_price=98.95, ema_9=99.40,
                               support=97.50, resistance=101.0, atr=1.0, rvol=2.0,
                               low_of_day=97.90, high_of_day=100.10, dist_from_ema9=-0.5)
    return SimpleNamespace(open=100.0, current_price=101.05, ema_9=100.60,
                           support=99.0, resistance=102.5, atr=1.0, rvol=2.0,
                           low_of_day=99.90, high_of_day=102.10, dist_from_ema9=0.5)


def _tape():
    return SimpleNamespace(confirmation_for_long=True, confirmation_for_short=True,
                           overall_signal=SimpleNamespace(value="neutral"))


def _run(fself, snap):
    return asyncio.get_event_loop().run_until_complete(
        EnhancedScanner._check_rubber_band(fself, "TEST", snap, _tape()))


def test_long_snapback_fires():
    a = _run(_fake_self(LONG_BARS), _snapshot("long"))
    assert a is not None and a.setup_type == "rubber_band_long" and a.direction == "long"


def test_short_snapback_fires():
    a = _run(_fake_self(SHORT_BARS), _snapshot("short"))
    assert a is not None and a.setup_type == "rubber_band_short" and a.direction == "short"


def test_rvol_gate_blocks():
    snap = _snapshot("long"); snap.rvol = 1.0  # below MIN_RVOL 1.5
    assert _run(_fake_self(LONG_BARS), snap) is None


def test_no_trigger_when_no_doublebreak():
    bars = LONG_BARS[:5]  # drop the clearing bar -> no double-bar-break
    assert _run(_fake_self(bars), _snapshot("long")) is None


def test_two_per_day_cap():
    fself = _fake_self(LONG_BARS)
    assert _run(fself, _snapshot("long")) is not None   # fire 1
    assert _run(fself, _snapshot("long")) is not None   # fire 2
    assert _run(fself, _snapshot("long")) is None        # capped at 2/day
