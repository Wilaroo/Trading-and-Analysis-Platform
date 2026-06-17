"""
test_v354_vwap_bounce.py — VWAP Bounce audit suppression (v19.34.354).

Verifies EnhancedBackgroundScanner._check_vwap_bounce is DISABLED: it must return None
even for a snapshot/tape that would have triggered the prior near-VWAP rule
(dist_from_vwap in (-0.8%,+0.3%), uptrend, above 9-EMA, rvol>=1.5).
Rationale: 14d native-1min replay (diag_v354) showed the rule is negative-EV (-242R over
2,387 fires) and no doctrine band was +EV, so it is suppressed to stop the bleed.

Run on DGX:  pytest backend/tests/test_v354_vwap_bounce.py -q
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
    )


def _snap():
    # Would have FIRED the old rule: 0.1% above VWAP, uptrend, above 9-EMA, rvol 2.0.
    return SimpleNamespace(dist_from_vwap=0.1, trend="uptrend", above_ema9=True, rvol=2.0,
                           vwap=100.0, atr=0.50, current_price=100.10, high_of_day=101.0)


def _tape():
    return SimpleNamespace(confirmation_for_long=True, overall_signal=SimpleNamespace(value="buy"))


def _run():
    return asyncio.new_event_loop().run_until_complete(
        EnhancedBackgroundScanner._check_vwap_bounce(_fake_self(), "TEST", _snap(), _tape()))


def test_vwap_bounce_suppressed():
    assert _run() is None, "vwap_bounce must be suppressed (return None) — negative-EV per v354 audit"
