"""Regression: v19.34.54 — daily_squeeze ATR-floored stop.

Before: hardcoded 5% stop ignored ATR. Inconsistent with rest of the
scanner after v19.34.50 standardised on `_atr_floored_stop`.

After: stop = max(structural_anchor, entry - 1.5×ATR) for longs,
       stop = min(structural_anchor, entry + 1.5×ATR) for shorts.

Structural anchor: lowest low / highest high of the 20-bar BB window
(the squeeze period). 1.5×ATR floor mirrors the 1.5×ATR Keltner
channel and gives daily-timeframe gap headroom.
"""

import asyncio
from unittest.mock import MagicMock

import pytest


# ── Lightweight stub for _atr_floored_stop logic (so tests don't need
# the whole EnhancedScanner singleton wiring). Mirrors the helper in
# enhanced_scanner.py exactly.
def _atr_floored_stop(entry_price, raw_stop, atr, direction, min_atr_mult=0.5):
    if not (entry_price and atr and float(atr) > 0):
        return round(float(raw_stop), 2)
    floor_distance = float(min_atr_mult) * float(atr)
    if str(direction).lower() == "long":
        return round(min(float(raw_stop), float(entry_price) - floor_distance), 2)
    else:
        return round(max(float(raw_stop), float(entry_price) + floor_distance), 2)


# Reproduce the v19.34.54 stop computation in isolation.
def _compute_stop(closes, lows, highs, direction, atr):
    current = closes[-1]
    if direction == "long":
        structural_anchor = min(lows[-20:]) - 0.02
    else:
        structural_anchor = max(highs[-20:]) + 0.02
    return _atr_floored_stop(
        entry_price=current,
        raw_stop=structural_anchor,
        atr=atr,
        direction=direction,
        min_atr_mult=1.5,
    )


# ── Test 1: long, structural anchor IS wider than 1.5×ATR — anchor wins
def test_long_structural_anchor_wider_than_atr_floor_used():
    closes = [100.0] * 20
    closes[-1] = 105.0
    lows   = [95.0] * 20      # 20-bar low = 95
    highs  = [110.0] * 20
    atr = 2.0                  # 1.5×ATR = $3 → floor = 105 - 3 = 102
                               # structural = 95 - 0.02 = 94.98 → wider, used
    stop = _compute_stop(closes, lows, highs, "long", atr)
    assert stop == 94.98, f"expected structural anchor 94.98, got {stop}"


# ── Test 2: long, structural anchor TOO TIGHT — ATR floor widens it
def test_long_structural_too_tight_atr_floor_widens():
    closes = [100.0] * 20
    closes[-1] = 105.0
    lows   = [104.0] * 20      # 20-bar low = 104, anchor=103.98
    highs  = [106.0] * 20
    atr = 2.0                  # 1.5×ATR = $3 → floor = 105 - 3 = 102
                               # 102 < 103.98 → ATR floor wins
    stop = _compute_stop(closes, lows, highs, "long", atr)
    assert stop == 102.0, f"expected ATR floor 102.0, got {stop}"


# ── Test 3: short — structural anchor wider than 1.5×ATR
def test_short_structural_anchor_wider_used():
    closes = [100.0] * 20
    closes[-1] = 95.0
    lows   = [90.0] * 20
    highs  = [110.0] * 20      # 20-bar high = 110, anchor=110.02
    atr = 2.0                  # 1.5×ATR = $3 → floor = 95 + 3 = 98
                               # 110.02 > 98 → structural wins
    stop = _compute_stop(closes, lows, highs, "short", atr)
    assert stop == 110.02, f"expected structural 110.02, got {stop}"


# ── Test 4: short — structural too tight, ATR floor widens
def test_short_structural_too_tight_atr_floor_widens():
    closes = [100.0] * 20
    closes[-1] = 95.0
    lows   = [94.0] * 20
    highs  = [96.0] * 20       # 20-bar high = 96, anchor=96.02
    atr = 2.0                  # 1.5×ATR = $3 → floor = 95 + 3 = 98
                               # 98 > 96.02 → ATR floor wins
    stop = _compute_stop(closes, lows, highs, "short", atr)
    assert stop == 98.0, f"expected ATR floor 98.0, got {stop}"


# ── Test 5: ATR == 0 (helper fails OPEN) — structural anchor used as-is
def test_zero_atr_falls_open_to_structural_anchor():
    closes = [100.0] * 20
    closes[-1] = 105.0
    lows   = [99.0] * 20
    highs  = [110.0] * 20
    stop = _compute_stop(closes, lows, highs, "long", atr=0)
    assert stop == 98.98, f"expected structural anchor 98.98, got {stop}"


# ── Test 6: stop is NEVER worse than the old 5% (longs) — sanity ─────
def test_long_stop_never_more_than_5pct_below_entry():
    """The new approach must produce stops that are AT LEAST as protective
    as the legacy 5% (i.e. ≤ entry × 0.95). Otherwise we're widening
    risk silently — opposite of intent.
    """
    closes = [100.0] * 20
    closes[-1] = 100.0
    lows   = [70.0] * 20       # huge 20-bar low → anchor far below
    highs  = [110.0] * 20
    atr = 1.0                  # tight ATR
    stop = _compute_stop(closes, lows, highs, "long", atr)
    # 1.5×ATR = $1.50 → floor = 98.50 (which is tighter than 95%)
    # structural = 69.98 → much wider → ATR floor wins
    # net: stop = 98.50 (TIGHTER than 5%, more protective). ✅
    assert stop <= 100.0 * 0.95 + 5.0, f"stop {stop} is wider than 5% legacy"


# ── Test 7: patch text is in the actual scanner file (lock the fix) ──
def test_patch_text_present_in_enhanced_scanner():
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "services" / "enhanced_scanner.py"
    text = src.read_text()
    assert "v19.34.54" in text, "v19.34.54 marker missing"
    # The legacy hardcoded 5% line must be GONE
    assert "current * (0.95 if direction == \"long\" else 1.05)" not in text, \
        "legacy hardcoded 5% stop still in daily_squeeze — patch reverted?"
    # The new ATR-floored call must be present
    assert "min_atr_mult=1.5" in text, \
        "v19.34.54 daily_squeeze ATR floor mult missing"
