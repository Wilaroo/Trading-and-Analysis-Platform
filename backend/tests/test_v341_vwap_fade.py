"""v19.34.324 (v341) — vwap_fade VWAP-anchored SMB snapback regression.

Run on the DGX AFTER applying patch_v341_vwap_fade_snapback.py:
    PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/test_v341_vwap_fade.py -q

Drives the real _check_vwap_fade via a lightweight fake `self` (no full __init__),
stubbing technical_service to return synthetic 1-min bars. Validates TRIGGER
semantics (event not state), long/short double-bar-break vs VWAP, the [1,3)% band
ceiling, the RVOL gate, the no-trigger block, and the 2/day-per-side cap.
"""
import asyncio
from types import SimpleNamespace

from services.enhanced_scanner import EnhancedBackgroundScanner, AlertPriority  # noqa: F401


def _bar(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c, "volume": 10000}


# VWAP≈100. LOD 97.90 = 2.1% below VWAP at idx3 (flush/accel); green bar idx5 clears
# prior-2 highs => LONG snapback +2 bars from LOD.
LONG_BARS = [
    _bar(100.0, 100.10, 99.80, 99.90),
    _bar(99.90, 99.95, 99.30, 99.40),
    _bar(99.40, 99.50, 98.60, 98.70),
    _bar(98.70, 98.80, 97.90, 98.00),    # LOD (big range)
    _bar(98.00, 98.60, 97.95, 98.50),    # green, does NOT clear 98.80
    _bar(98.50, 99.00, 98.40, 98.95),    # green, 99.00 > max(98.60,98.80) -> CLEARS
]

# VWAP≈100. HOD 102.10 = 2.1% above VWAP at idx3; red bar idx5 breaks prior-2 lows => SHORT.
SHORT_BARS = [
    _bar(100.0, 100.20, 99.90, 100.10),
    _bar(100.10, 100.70, 100.05, 100.60),
    _bar(100.60, 101.40, 100.50, 101.30),
    _bar(101.30, 102.10, 101.20, 102.00),  # HOD (spike)
    _bar(102.00, 102.05, 101.40, 101.50),  # red, does NOT break 101.20
    _bar(101.50, 101.60, 101.00, 101.05),  # red, 101.00 < min(101.40,101.20) -> BREAKS
]


def _fake_self(bars):
    return SimpleNamespace(
        technical_service=SimpleNamespace(
            _get_intraday_bars_from_db=lambda sym, bs, n: list(bars)),
        _strategy_stats={},
        _get_current_time_window=lambda: SimpleNamespace(value="midday"),
        _market_regime=SimpleNamespace(value="range_bound"),
    )


def _snap(direction, rvol=2.0, vwap=100.0):
    if direction == "long":
        return SimpleNamespace(current_price=98.95, vwap=vwap, ema_9=99.40,
                               support=97.50, resistance=101.0, atr=1.0, rvol=rvol,
                               low_of_day=97.90, high_of_day=100.10, dist_from_vwap=-1.05)
    return SimpleNamespace(current_price=101.05, vwap=vwap, ema_9=100.60,
                           support=99.0, resistance=102.5, atr=1.0, rvol=rvol,
                           low_of_day=99.90, high_of_day=102.10, dist_from_vwap=1.05)


def _tape():
    return SimpleNamespace(confirmation_for_long=True, confirmation_for_short=True,
                           overall_signal=SimpleNamespace(value="neutral"))


def _run(fself, snap):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            EnhancedBackgroundScanner._check_vwap_fade(fself, "TEST", snap, _tape()))
    finally:
        loop.close()


def test_long_snapback_fires():
    a = _run(_fake_self(LONG_BARS), _snap("long"))
    assert a is not None and a.setup_type == "vwap_fade_long" and a.direction == "long"
    assert a.target == 100.0 and a.stop_loss < a.current_price


def test_short_snapback_fires():
    a = _run(_fake_self(SHORT_BARS), _snap("short"))
    assert a is not None and a.setup_type == "vwap_fade_short" and a.direction == "short"
    assert a.target == 100.0 and a.stop_loss > a.current_price


def test_rvol_gate_blocks():
    assert _run(_fake_self(LONG_BARS), _snap("long", rvol=1.0)) is None


def test_extension_ceiling_blocks_runaway():
    # vwap=101 makes ext_long = (101-97.90)/101 = 3.07% >= 3.0% ceiling -> no fade
    assert _run(_fake_self(LONG_BARS), _snap("long", vwap=101.0)) is None


def test_no_double_break_blocks():
    # drop the clearing bar (idx5) -> last bar (idx4) does not clear prior-2 highs
    assert _run(_fake_self(LONG_BARS[:5]), _snap("long")) is None


def test_two_per_day_cap():
    fself = _fake_self(LONG_BARS)
    snap = _snap("long")
    assert _run(fself, snap) is not None
    assert _run(fself, snap) is not None
    assert _run(fself, snap) is None  # 3rd fire same (symbol, day, side) capped
