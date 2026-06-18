"""
test_v363_spencer_scalp_doctrine.py — Spencer Scalp DOCTRINE rewrite (v363, LONG-only).

Verifies the v363 rewrite of EnhancedBackgroundScanner._check_spencer_scalp to the SMB cheat-sheet
structure on 1-min bars:
  • a 20-bar consolidation whose band < 15% of the day's range, located in the UPPER 1/3 of the range,
  • a VOLUME SURGE on the break bar (>=1.3x the consolidation avg),
  • ENTER on the break of the range high, STOP .02 below the range low, fixed 2.0R target.

Rationale: 180d/300-sym 1-min replay (diag_v363_spencer_scalp_doctrine.py): doctrine LONG +0.04..0.06R;
SHORT ~0 (dropped); morning-only was -EV (kept all-day). The prior loose near-HOD code (dist_from_hod<1
+ daily_range<3 + rvol>=1.5, ATR stop, fixed HOD+1.5ATR target) had 0 real fills and modeled none of
the 20-min-range / range-stop / measured-move structure.

Run on DGX:  pytest backend/tests/test_v363_spencer_scalp_doctrine.py -q
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.enhanced_scanner import EnhancedBackgroundScanner


def _bar(o, h, l, c, v):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def _self(bars):
    return SimpleNamespace(
        technical_service=SimpleNamespace(_get_intraday_bars_from_db=lambda s, sz, n: bars),
        _get_current_time_window=lambda: SimpleNamespace(value="morning_session"),
        _market_regime=SimpleNamespace(value="neutral"),
    )


def _tape():
    return SimpleNamespace(confirmation_for_long=True, overall_signal=SimpleNamespace(value="buy"))


def _run(self_obj, snap):
    return asyncio.new_event_loop().run_until_complete(
        EnhancedBackgroundScanner._check_spencer_scalp(self_obj, "TEST", snap, _tape()))


# day range 100-110 (dr=10); upper-1/3 floor = 106.67. consolidation 108.0-108.3 (band 0.3 < 1.5),
# 20 bars vol 1000, then a break bar (high 108.6 > 108.31) with surge vol 2000 (>1.3x).
_LEAD = [_bar(107.0, 107.5, 106.8, 107.2, 3000) for _ in range(3)]
_CONS = [_bar(108.1, 108.3, 108.0, 108.2, 1000) for _ in range(20)]
_BRK = [_bar(108.2, 108.6, 108.15, 108.5, 2000)]
_BARS = _LEAD + _CONS + _BRK


def _snap(**kw):
    base = dict(high_of_day=110.0, low_of_day=100.0, current_price=108.5)
    base.update(kw)
    return SimpleNamespace(**base)


def test_doctrine_fires_long_with_correct_geometry():
    a = _run(_self(_BARS), _snap())
    assert a is not None and a.setup_type == "spencer_scalp" and a.direction == "long"
    assert abs(a.trigger_price - 108.31) < 1e-6, f"entry should be range_high+.01, got {a.trigger_price}"
    assert abs(a.stop_loss - 107.98) < 1e-6, f"stop should be range_low-.02, got {a.stop_loss}"
    assert abs(a.target - (a.trigger_price + 2.0 * (a.trigger_price - a.stop_loss))) < 1e-6
    assert a.risk_reward == 2.0


def test_blocked_when_consolidation_not_in_upper_third():
    low = _LEAD + [_bar(103.0, 103.2, 102.9, 103.1, 1000) for _ in range(20)] + [_bar(103.1, 103.5, 103.0, 103.4, 2000)]
    assert _run(_self(low), _snap()) is None


def test_blocked_when_band_too_wide():
    wide = _LEAD + [_bar(108.5, 109.8, 108.0, 109.0, 1000) for _ in range(20)] + _BRK
    assert _run(_self(wide), _snap()) is None


def test_blocked_without_volume_surge():
    flat = _LEAD + _CONS + [_bar(108.2, 108.6, 108.15, 108.5, 1000)]  # break-bar vol == window avg
    assert _run(_self(flat), _snap()) is None


def test_blocked_when_no_range_break():
    nobrk = _LEAD + _CONS + [_bar(108.1, 108.25, 108.0, 108.1, 2000)]
    assert _run(_self(nobrk), _snap(current_price=108.1)) is None
