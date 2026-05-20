"""Regression: v19.34.54 — daily_squeeze ATR-floored stop."""

import pytest


def _atr_floored_stop(entry_price, raw_stop, atr, direction, min_atr_mult=0.5):
    if not (entry_price and atr and float(atr) > 0):
        return round(float(raw_stop), 2)
    floor_distance = float(min_atr_mult) * float(atr)
    if str(direction).lower() == "long":
        return round(min(float(raw_stop), float(entry_price) - floor_distance), 2)
    else:
        return round(max(float(raw_stop), float(entry_price) + floor_distance), 2)


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


def test_long_structural_anchor_wider_than_atr_floor_used():
    closes = [100.0] * 20
    closes[-1] = 105.0
    lows   = [95.0] * 20
    highs  = [110.0] * 20
    atr = 2.0
    stop = _compute_stop(closes, lows, highs, "long", atr)
    assert stop == 94.98, f"expected structural anchor 94.98, got {stop}"


def test_long_structural_too_tight_atr_floor_widens():
    closes = [100.0] * 20
    closes[-1] = 105.0
    lows   = [104.0] * 20
    highs  = [106.0] * 20
    atr = 2.0
    stop = _compute_stop(closes, lows, highs, "long", atr)
    assert stop == 102.0, f"expected ATR floor 102.0, got {stop}"


def test_short_structural_anchor_wider_used():
    closes = [100.0] * 20
    closes[-1] = 95.0
    lows   = [90.0] * 20
    highs  = [110.0] * 20
    atr = 2.0
    stop = _compute_stop(closes, lows, highs, "short", atr)
    assert stop == 110.02, f"expected structural 110.02, got {stop}"


def test_short_structural_too_tight_atr_floor_widens():
    closes = [100.0] * 20
    closes[-1] = 95.0
    lows   = [94.0] * 20
    highs  = [96.0] * 20
    atr = 2.0
    stop = _compute_stop(closes, lows, highs, "short", atr)
    assert stop == 98.0, f"expected ATR floor 98.0, got {stop}"


def test_zero_atr_falls_open_to_structural_anchor():
    closes = [100.0] * 20
    closes[-1] = 105.0
    lows   = [99.0] * 20
    highs  = [110.0] * 20
    stop = _compute_stop(closes, lows, highs, "long", atr=0)
    assert stop == 98.98, f"expected structural anchor 98.98, got {stop}"


def test_long_stop_never_more_than_5pct_below_entry():
    closes = [100.0] * 20
    closes[-1] = 100.0
    lows   = [70.0] * 20
    highs  = [110.0] * 20
    atr = 1.0
    stop = _compute_stop(closes, lows, highs, "long", atr)
    assert stop <= 100.0 * 0.95 + 5.0, f"stop {stop} is wider than 5% legacy"


def test_patch_text_present_in_enhanced_scanner():
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "services" / "enhanced_scanner.py"
    text = src.read_text()
    assert "v19.34.54" in text
    assert "current * (0.95 if direction == \"long\" else 1.05)" not in text
    assert "min_atr_mult=1.5" in text
