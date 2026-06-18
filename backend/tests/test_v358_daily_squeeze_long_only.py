"""
test_v358_daily_squeeze_long_only.py — daily_squeeze LONG-ONLY gate (v358).

Verifies EnhancedBackgroundScanner._check_daily_squeeze:
  • returns a LONG alert for a bullish squeeze (close above SMA20, BB inside Keltner, tight), and
  • returns None for a bearish squeeze (close below SMA20) — the momentum-SHORT branch is gated off.

Rationale: diag_v358 replay (365d / 400-sym daily) showed the short branch is negative-EV in
every config (winsorAvg -0.04..-0.09, totW -0.8k..-1.1k), dragging a solidly +EV long side
(+0.073 R/trade, 51% win) to breakeven. Long-only keeps the edge, kills the bleed.

Run on DGX:  pytest backend/tests/test_v358_daily_squeeze_long_only.py -q
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.enhanced_scanner import EnhancedBackgroundScanner


def _fake_self():
    # ATR-floored stop helper: return a stop a fixed distance from entry in the right direction.
    def _stop(entry_price, raw_stop, atr, direction, min_atr_mult):
        return entry_price - atr * min_atr_mult if direction == "long" else entry_price + atr * min_atr_mult
    return SimpleNamespace(
        _atr_floored_stop=_stop,
        _get_current_time_window=lambda: SimpleNamespace(value="DAILY"),
        _market_regime=SimpleNamespace(value="neutral"),
    )


def _bars(direction):
    """Build a tight daily squeeze (BB inside Keltner) ending with momentum in `direction`.
    20 VOLATILE historical bars (large historical median width) then 20 TIGHT recent bars
    (flat closes, modest intrabar range -> BB collapses inside KC, width << 0.7*median)."""
    b = []
    for i in range(20):
        c = 95.0 if i % 2 == 0 else 105.0
        b.append({"open": c, "high": c + 1.0, "low": c - 1.0, "close": c, "volume": 1_000_000})
    for i in range(20):
        b.append({"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0, "volume": 1_000_000})
    last_c = 100.40 if direction == "long" else 99.60
    b.append({"open": 100.0, "high": last_c + 0.1, "low": last_c - 0.1, "close": last_c, "volume": 1_500_000})
    return b


def _run(direction):
    return asyncio.new_event_loop().run_until_complete(
        EnhancedBackgroundScanner._check_daily_squeeze(_fake_self(), "TEST", _bars(direction)))


def test_daily_squeeze_long_fires():
    alert = _run("long")
    assert alert is not None and alert.direction == "long", "bullish squeeze must still fire LONG"


def test_daily_squeeze_short_suppressed():
    assert _run("short") is None, "bearish (short) daily_squeeze must be suppressed (return None) per v358"
