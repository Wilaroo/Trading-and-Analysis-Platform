"""
test_v359_squeeze_suppress.py — Squeeze suppression (v359).

Verifies EnhancedBackgroundScanner._check_squeeze returns None even for a snapshot/tape that
would have fired the prior rule (squeeze_on=True, rvol>=1.0, squeeze_fire>0, tight bb_width).

Rationale: the "intraday" squeeze is actually a DAILY-bar signal (squeeze_on/bb_width/atr/rvol
all built from daily bars) that fully overlaps daily_squeeze and fires ~46k/yr with no tightness
gate. Ground truth from 473 closed bot_trades is negative-EV on every cut (ALL winsorAvg -0.158,
LONG -0.080 n=285, SHORT -0.277 n=188); its market-order fill geometry replays to -0.475 R/trade.
The genuine daily-compression LONG edge is already captured by daily_squeeze (long-only, v358).
Suppressed to dedupe a high-frequency negative-EV duplicate.

Run on DGX:  pytest backend/tests/test_v359_squeeze_suppress.py -q
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.enhanced_scanner import EnhancedBackgroundScanner


def _fake_self():
    return SimpleNamespace(
        _get_current_time_window=lambda: SimpleNamespace(value="midday"),
        _market_regime=SimpleNamespace(value="neutral"),
    )


def _snap():
    # Would have FIRED: squeeze on, tight band, rvol high, bullish fire.
    return SimpleNamespace(squeeze_on=True, squeeze_fire=1.5, bb_width=2.0, rvol=2.0,
                           bb_upper=101.0, bb_lower=99.0, atr=1.0, current_price=100.5, rsi_14=55.0)


def _tape():
    return SimpleNamespace(confirmation_for_long=True, confirmation_for_short=False,
                           overall_signal=SimpleNamespace(value="buy"), tape_score=0.8)


def _run():
    return asyncio.new_event_loop().run_until_complete(
        EnhancedBackgroundScanner._check_squeeze(_fake_self(), "TEST", _snap(), _tape()))


def test_squeeze_suppressed():
    assert _run() is None, "squeeze must be suppressed (return None) — negative-EV duplicate per v359 audit"
