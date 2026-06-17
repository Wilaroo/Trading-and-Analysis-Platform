"""v19.34.325 (v343) — gap_fade gap-gated SMB snapback regression.

Run on the DGX AFTER applying patch_v343_gap_fade_snapback.py:
    PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/test_v343_gap_fade.py -q

Validates: gap-up failing -> SHORT snapback to VWAP, gap-down recovering -> LONG snapback,
the |gap|>=2% + RVOL>=1.3 gates, the complementarity gate (entry must be WITHIN 1% of VWAP),
the no-trigger block, and the 2/day-per-side cap.
"""
import asyncio
from types import SimpleNamespace

from services.enhanced_scanner import EnhancedBackgroundScanner, AlertPriority  # noqa: F401


def _bar(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c, "volume": 10000}


# Gap UP day. HOD 102.10 at idx3; red bar idx5 breaks prior-2 lows; entry = min(101.40,101.20)
# = 101.20, just above VWAP=100.6 (within 1% -> complementary). -> SHORT snapback.
SHORT_BARS = [
    _bar(101.50, 101.70, 101.30, 101.55),
    _bar(101.55, 101.90, 101.45, 101.80),
    _bar(101.80, 102.00, 101.70, 101.95),
    _bar(101.95, 102.10, 101.30, 102.00),  # HOD (wide-range spike -> accel)
    _bar(102.00, 102.05, 101.40, 101.50),  # red, low 101.40 (no break of 101.30)
    _bar(101.50, 101.55, 101.00, 101.05),  # red, low 101.00 < min(101.40,101.30) -> BREAKS
]

# Gap DOWN day. LOD 98.0 at idx3; green bar idx5 clears prior-2 highs; entry = max(98.60,98.80)
# = 98.80, just below VWAP=99.4 (within 1%). -> LONG snapback.
LONG_BARS = [
    _bar(98.70, 98.90, 98.55, 98.75),
    _bar(98.75, 98.95, 98.35, 98.45),
    _bar(98.45, 98.55, 98.10, 98.20),
    _bar(98.20, 98.80, 97.90, 98.00),    # LOD (flush)
    _bar(98.00, 98.60, 97.95, 98.50),    # green, high 98.60 (no clear of 98.80)
    _bar(98.50, 99.00, 98.40, 98.95),    # green, high 99.00 > max(98.60,98.80) -> CLEARS
]


def _fake_self(bars):
    return SimpleNamespace(
        technical_service=SimpleNamespace(
            _get_intraday_bars_from_db=lambda sym, bs, n: list(bars)),
        _get_current_time_window=lambda: SimpleNamespace(value="midday"),
        _market_regime=SimpleNamespace(value="range_bound"),
    )


def _snap(direction, gap_pct, rvol=2.0, vwap=None):
    if direction == "short":
        return SimpleNamespace(gap_pct=gap_pct, rvol=rvol, vwap=vwap or 100.60,
                               current_price=101.05, atr=1.0, support=100.0, resistance=102.5,
                               high_of_day=102.10, low_of_day=101.0, above_vwap=False, holding_gap=False)
    return SimpleNamespace(gap_pct=gap_pct, rvol=rvol, vwap=vwap or 99.40,
                           current_price=98.95, atr=1.0, support=97.5, resistance=100.0,
                           high_of_day=99.0, low_of_day=97.90, above_vwap=True, holding_gap=True)


def _tape():
    return SimpleNamespace(confirmation_for_long=True, confirmation_for_short=True,
                           overall_signal=SimpleNamespace(value="neutral"))


def _run(fself, snap):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            EnhancedBackgroundScanner._check_gap_fade(fself, "TEST", snap, _tape()))
    finally:
        loop.close()


def test_gap_up_short_fires():
    a = _run(_fake_self(SHORT_BARS), _snap("short", 3.0))
    assert a is not None and a.setup_type == "gap_fade" and a.direction == "short"
    assert a.target == 100.60 and a.stop_loss > a.current_price


def test_gap_down_long_fires():
    a = _run(_fake_self(LONG_BARS), _snap("long", -3.0))
    assert a is not None and a.setup_type == "gap_fade" and a.direction == "long"
    assert a.target == 99.40 and a.stop_loss < a.current_price


def test_small_gap_blocked():
    assert _run(_fake_self(SHORT_BARS), _snap("short", 1.0)) is None


def test_rvol_gate_blocks():
    assert _run(_fake_self(SHORT_BARS), _snap("short", 3.0, rvol=1.0)) is None


def test_complementarity_gate_blocks_high_ext():
    # VWAP far from entry (entry 101.20 vs vwap 99.0 => >2% ext) -> vwap_fade's job, gap_fade defers
    assert _run(_fake_self(SHORT_BARS), _snap("short", 3.0, vwap=99.0)) is None


def test_no_trigger_blocks():
    assert _run(_fake_self(SHORT_BARS[:5]), _snap("short", 3.0)) is None


def test_two_per_day_cap():
    fself = _fake_self(SHORT_BARS)
    snap = _snap("short", 3.0)
    assert _run(fself, snap) is not None
    assert _run(fself, snap) is not None
    assert _run(fself, snap) is None
