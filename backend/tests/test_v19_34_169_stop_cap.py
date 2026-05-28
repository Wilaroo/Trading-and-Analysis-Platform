"""v19.34.169 — Pre-market sizing+EOD observability tests.

Covers:
  1. ATR-based stop is capped at 5% of entry for POSITION (mult>=3.0)
     and INVESTMENT (2.5<=mult<3.0) horizons.
  2. Intraday/scalp setups are UNTOUCHED by the cap.
  3. POSITION-tier cap is configurable via MAX_STOP_PCT_POSITION env.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from services.opportunity_evaluator import OpportunityEvaluator  # noqa: E402


def _make_bot():
    bot = MagicMock()
    bot.risk_params.min_atr_multiplier = 1.0
    bot.risk_params.max_atr_multiplier = 3.0
    bot.risk_params.base_atr_multiplier = 1.5
    return bot


def _make_evaluator():
    ev = OpportunityEvaluator.__new__(OpportunityEvaluator)
    return ev


def _stop(setup, entry, atr, direction="long"):
    """Helper that calls calculate_atr_based_stop and returns stop_distance."""
    from services.trading_bot_service import TradeDirection
    d = TradeDirection.LONG if direction == "long" else TradeDirection.SHORT
    ev = _make_evaluator()
    stop_price = ev.calculate_atr_based_stop(entry, d, atr, setup, _make_bot())
    return abs(entry - stop_price), stop_price


def test_rs_leader_break_alab_capped_at_5pct():
    """ALAB: entry $326, ATR $20 → raw 2.5×20=$50 (15%) → cap at $16.30 (5%)."""
    distance, _ = _stop("rs_leader_break", entry=326.54, atr=20.0)
    assert distance == pytest.approx(326.54 * 0.05, abs=0.01), \
        f"expected ~$16.33 cap, got ${distance:.2f}"


def test_stage_2_breakout_position_horizon_capped():
    """stage_2_breakout uses 3.0× ATR → POSITION horizon → 5% cap."""
    distance, _ = _stop("stage_2_breakout", entry=200.0, atr=15.0)
    # raw = 3.0 × 15 = 45 (22.5%); cap = 200 × 0.05 = 10
    assert distance == pytest.approx(10.0, abs=0.01)


def test_accumulation_entry_investment_horizon_capped():
    """accumulation_entry uses 2.5× ATR → INVESTMENT horizon → 5% cap."""
    distance, _ = _stop("accumulation_entry", entry=100.0, atr=10.0)
    # raw = 2.5 × 10 = 25 (25%); cap = 100 × 0.05 = 5
    assert distance == pytest.approx(5.0, abs=0.01)


def test_intraday_breakout_not_capped():
    """breakout uses 1.5× ATR (intraday) → cap does NOT apply."""
    distance, _ = _stop("breakout", entry=50.0, atr=1.0)
    # raw = 1.5 × 1.0 = 1.5 — well below 5% (=$2.50) and intraday horizon
    # anyway. Stop must remain at the raw ATR distance.
    assert distance == pytest.approx(1.5, abs=0.01)


def test_scalp_setup_not_capped():
    """9_ema_scalp uses 0.4× ATR → scalp horizon → no cap."""
    distance, _ = _stop("9_ema_scalp", entry=50.0, atr=1.0)
    # raw = 0.4 × 1.0 = 0.4
    assert distance == pytest.approx(0.4, abs=0.01)


def test_position_cap_env_override():
    """MAX_STOP_PCT_POSITION env var overrides the default 5%."""
    os.environ["MAX_STOP_PCT_POSITION"] = "0.07"
    try:
        distance, _ = _stop("stage_2_breakout", entry=100.0, atr=10.0)
        # raw = 3.0 × 10 = 30 (30%); cap = 100 × 0.07 = 7
        assert distance == pytest.approx(7.0, abs=0.01)
    finally:
        os.environ.pop("MAX_STOP_PCT_POSITION", None)


def test_cap_does_not_widen_already_tight_stop():
    """If raw stop_distance is already smaller than the cap, leave it."""
    # Entry $326, ATR $1 → raw 2.5×1=$2.50 (0.77%). Cap = 5% = $16.30.
    # Stop must remain at the raw $2.50, NOT be widened to the cap.
    distance, _ = _stop("rs_leader_break", entry=326.54, atr=1.0)
    assert distance == pytest.approx(2.5, abs=0.01)


def test_short_direction_capped_symmetrically():
    """Cap applies to SHORT side the same way."""
    distance, stop_price = _stop("rs_leader_break", entry=100.0, atr=8.0, direction="short")
    # raw = 2.5 × 8 = 20 (20%); cap = 100 × 0.05 = 5; short stop = entry + 5 = 105
    assert distance == pytest.approx(5.0, abs=0.01)
    assert stop_price == pytest.approx(105.0, abs=0.01)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
