"""
test_v362_gap_give_go_doctrine.py — Gap Give & Go DOCTRINE rewrite (v362).

Verifies the v362 rewrite of EnhancedBackgroundScanner._check_gap_give_go to the SMB cheat-sheet
structure on 1-min bars:
  • Opening-drive window only (OPENING_AUCTION / OPENING_DRIVE).
  • gap-up, a "give" that holds above prior close and fills <=50% of the gap.
  • a 3-7 bar mini-consolidation (band <= 0.6% of price) on declining volume.
  • ENTER on break of the consolidation high, STOP .02 below the consolidation low, fixed 2.0R target.

Rationale: 180d/300-sym 1-min replay (diag_v362b_gap_give_go_doctrine.py): the doctrine 2.0R cut is
n=492 win 47% winsorAvg +0.233R vs the prior loose VWAP-pullback code ~+0.07R (breakeven). The old
code modeled none of the give/consolidation/range-break structure (VWAP stop + fixed HOD target).

Run on DGX:  pytest backend/tests/test_v362_gap_give_go_doctrine.py -q
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.enhanced_scanner import EnhancedBackgroundScanner, TimeWindow


def _bar(o, h, l, c, v):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def _self(bars, window=TimeWindow.OPENING_DRIVE):
    return SimpleNamespace(
        technical_service=SimpleNamespace(_get_intraday_bars_from_db=lambda s, sz, n: bars),
        _get_current_time_window=lambda: window,
        _market_regime=SimpleNamespace(value="neutral"),
    )


def _tape():
    return SimpleNamespace(confirmation_for_long=True, overall_signal=SimpleNamespace(value="buy"))


def _run(self_obj, snap):
    return asyncio.new_event_loop().run_until_complete(
        EnhancedBackgroundScanner._check_gap_give_go(self_obj, "TEST", snap, _tape()))


# gap up to 103 (from prev_close 100), give to 101.5 (holds >100, <50% fill),
# 5-bar consolidation 101.6-101.9 on declining volume, then a break bar (high 102.3 > 101.91)
_GIVE = [_bar(103, 103.2, 101.5, 101.6, 5000) for _ in range(4)]
_CONS = [_bar(101.7, 101.9, 101.6, 101.75, 1500) for _ in range(5)]
_BRK = [_bar(101.8, 102.3, 101.78, 102.2, 4000)]
_BARS = _GIVE + _CONS + _BRK


def _snap(**kw):
    base = dict(gap_pct=3.0, prev_close=100.0, open=103.0, current_price=102.2, high_of_day=103.2)
    base.update(kw)
    return SimpleNamespace(**base)


def test_doctrine_fires_with_correct_geometry():
    a = _run(_self(_BARS), _snap())
    assert a is not None and a.setup_type == "gap_give_go" and a.direction == "long"
    assert abs(a.trigger_price - 101.91) < 1e-6, f"entry should be cons_high+.01, got {a.trigger_price}"
    assert abs(a.stop_loss - 101.58) < 1e-6, f"stop should be cons_low-.02, got {a.stop_loss}"
    assert abs(a.target - (a.trigger_price + 2.0 * (a.trigger_price - a.stop_loss))) < 1e-6
    assert a.risk_reward == 2.0


def test_blocked_outside_opening_drive():
    assert _run(_self(_BARS, TimeWindow.MORNING_MOMENTUM), _snap()) is None


def test_blocked_when_gap_too_small():
    assert _run(_self(_BARS), _snap(gap_pct=0.5, open=100.4)) is None


def test_blocked_when_no_range_break():
    nobrk = _GIVE + _CONS + [_bar(101.7, 101.85, 101.6, 101.7, 1500)]
    assert _run(_self(nobrk), _snap(current_price=101.7)) is None


def test_blocked_when_consolidation_band_too_wide():
    wide = [_bar(101, 103, 100.5, 102, 2000) for _ in range(5)]
    assert _run(_self(_GIVE + wide + _BRK), _snap()) is None


def test_blocked_when_give_fills_more_than_half_the_gap():
    deep = [_bar(103, 103.2, 100.9, 101.0, 5000) for _ in range(4)]  # give_low 100.9 -> ~70% fill
    assert _run(_self(deep + _CONS + _BRK), _snap()) is None
