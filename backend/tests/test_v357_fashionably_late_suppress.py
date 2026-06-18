"""
test_v357_fashionably_late_suppress.py — Fashionably Late suppression (v357).

Verifies EnhancedBackgroundScanner._check_fashionably_late is DISABLED: it must return
None even for a snapshot/tape that would have triggered the prior 9-EMA>VWAP rule
(above 9-EMA, ema_9 just above VWAP within 0.5%, uptrend, rvol>=1.2).

Rationale: diag_v357 replay (120d / 300-symbol IB intraday) showed the 9-EMA×VWAP cross
is sub-cost negative-EV under EVERY tested geometry — SMB-doctrine measured-move 3:1 best
subset = -0.018 R/trade BEFORE costs (win 54%, avgRR 0.67); the prior live ATR-floored-stop
geometry was the worst variant at -0.27 to -0.53 R/trade (win 13-23%). No quality gate
(vol-convergence / fast-turn / time-window) isolated a tradeable +EV subset. Suppressed to
stop the bleed, exactly like vwap_bounce (v354).

Run on DGX:  pytest backend/tests/test_v357_fashionably_late_suppress.py -q
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.enhanced_scanner import EnhancedBackgroundScanner


def _fake_self():
    return SimpleNamespace(
        technical_service=SimpleNamespace(_get_intraday_bars_from_db=lambda sym, sz, n: []),
        _strategy_stats={},
        _market_regime=SimpleNamespace(value="uptrend"),
        _get_current_time_window=lambda: SimpleNamespace(value="midday"),
        _atr_floored_stop=lambda **kw: 99.0,
    )


def _snap():
    # Would have FIRED the old rule: above 9-EMA, ema_9 0.1% above VWAP, uptrend, rvol 2.0.
    return SimpleNamespace(above_ema9=True, ema_9=100.10, vwap=100.0, trend="uptrend",
                           rvol=2.0, atr=0.50, current_price=100.10, low_of_day=99.0)


def _tape():
    return SimpleNamespace(confirmation_for_long=True, overall_signal=SimpleNamespace(value="buy"))


def _run():
    return asyncio.new_event_loop().run_until_complete(
        EnhancedBackgroundScanner._check_fashionably_late(_fake_self(), "TEST", _snap(), _tape()))


def test_fashionably_late_suppressed():
    assert _run() is None, "fashionably_late must be suppressed (return None) — negative-EV per v357 audit"
