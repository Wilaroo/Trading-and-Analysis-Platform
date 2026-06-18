"""
test_v360_first_move_suppress.py — First Move Up/Down suppression (v360).

Verifies BOTH EnhancedBackgroundScanner._check_first_move_up (SHORT morning-push fade) and
._check_first_move_down (LONG morning-flush fade) return None even for a snapshot/tape that
would have satisfied the prior firing gates.

Rationale: a 180d / 300-sym 5-min intraday replay (diag_v360_first_move_replay.py) proved both
are structurally negative-EV counter-trend morning fades:
  first_move_up   (SHORT): n=2392 win 27% winsorAvg -0.106 R/trade (>50% hit the full stop)
  first_move_down (LONG):  n=2274 win 24% winsorAvg -0.176 R/trade (>50% hit the full stop)
Tightening push/RSI/rvol gates did not help — fading a volume-confirmed fresh-HOD push (or
fresh-LOD flush) fights the same momentum the validated setups trade. Suppressed like
vwap_bounce (v354) / fashionably_late (v357) / squeeze (v359).

Run on DGX:  pytest backend/tests/test_v360_first_move_suppress.py -q
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.enhanced_scanner import EnhancedBackgroundScanner


def _fake_self():
    return SimpleNamespace(
        _get_current_time_window=lambda: SimpleNamespace(value="open"),
        _market_regime=SimpleNamespace(value="neutral"),
    )


def _snap_up():
    # Would have FIRED first_move_up: fresh-HOD push >1.5% from open, at HOD, RSI overbought,
    # extended above VWAP, rvol high.
    return SimpleNamespace(
        high_of_day=103.0, low_of_day=99.0, open=100.0, current_price=102.95,
        atr=1.0, rsi_14=72.0, dist_from_vwap=1.5, rvol=2.0, vwap=100.5,
    )


def _snap_down():
    # Would have FIRED first_move_down: fresh-LOD flush >1.5% from open, at LOD, RSI oversold,
    # extended below VWAP, rvol high.
    return SimpleNamespace(
        high_of_day=101.0, low_of_day=97.0, open=100.0, current_price=97.05,
        atr=1.0, rsi_14=28.0, dist_from_vwap=-1.5, rvol=2.0, vwap=99.5,
    )


def _tape():
    return SimpleNamespace(confirmation_for_long=True, confirmation_for_short=True,
                           overall_signal=SimpleNamespace(value="buy"), tape_score=0.8)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_first_move_up_suppressed():
    res = _run(EnhancedBackgroundScanner._check_first_move_up(_fake_self(), "TEST", _snap_up(), _tape()))
    assert res is None, "first_move_up must be suppressed (return None) — negative-EV morning fade per v360 audit"


def test_first_move_down_suppressed():
    res = _run(EnhancedBackgroundScanner._check_first_move_down(_fake_self(), "TEST", _snap_down(), _tape()))
    assert res is None, "first_move_down must be suppressed (return None) — negative-EV morning fade per v360 audit"
