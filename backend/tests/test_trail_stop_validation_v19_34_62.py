"""
v19.34.62 — Trail-stop validation now checks current_price (not entry).

Operator was rejected from chat AI when trying to move MU long stop to
$731 (entry $713.69, current $740.50). The bot's validation enforced
"stop must be < entry", which is correct for an INITIAL stop but wrong
for a trail stop on a profitable position. Now checks current_price.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.bracket_reissue_service import compute_reissue_params


class _RiskParams:
    reconciled_default_stop_pct = 2.0


def _trade(direction: str, entry: float, current: float, shares: int = 100):
    """Build a fake BotTrade-like object."""
    direction_obj = SimpleNamespace(value=direction)
    return SimpleNamespace(
        id="t-1",
        symbol="MU",
        direction=direction_obj,
        entry_price=entry,
        fill_price=entry,
        current_price=current,
        stop_price=entry * 0.98 if direction == "long" else entry * 1.02,
        target_prices=[entry * 1.05] if direction == "long" else [entry * 0.95],
        shares=shares,
        scale_out_config={"scale_out_pcts": [1.0]},
        trade_style="trade_2_hold",
        timeframe="intraday",
    )


# ────────────────────────────────────────────────────────────────────
# THE BUG: long trail stop above entry but below current MUST be allowed
# ────────────────────────────────────────────────────────────────────


def test_long_trail_stop_above_entry_below_current_accepted():
    """MU long: entry $713.69, current $740.50, operator wants stop $731.
    Stop is ABOVE entry (the old buggy rule rejected this) but BELOW
    current (so it would NOT trigger immediately). Must be accepted."""
    trade = _trade("long", entry=713.69, current=740.50, shares=140)
    plan = compute_reissue_params(
        trade=trade, risk_params=_RiskParams(), reason="trail_up",
        operator_stop_price=731.0,
    )
    assert plan.new_stop_price == 731.0


def test_short_trail_stop_below_entry_above_current_accepted():
    trade = _trade("short", entry=100.0, current=90.0, shares=50)
    plan = compute_reissue_params(
        trade=trade, risk_params=_RiskParams(), reason="trail_down",
        operator_stop_price=95.0,
    )
    assert plan.new_stop_price == 95.0


# Sanity: stops that WOULD trigger immediately must still be rejected
def test_long_stop_at_current_rejected():
    trade = _trade("long", entry=713.69, current=740.50, shares=140)
    with pytest.raises(ValueError, match="at/above long current"):
        compute_reissue_params(
            trade=trade, risk_params=_RiskParams(), reason="x",
            operator_stop_price=740.50,
        )


def test_long_stop_above_current_rejected():
    trade = _trade("long", entry=713.69, current=740.50)
    with pytest.raises(ValueError, match="at/above long current"):
        compute_reissue_params(
            trade=trade, risk_params=_RiskParams(), reason="x",
            operator_stop_price=745.00,
        )


def test_short_stop_at_current_rejected():
    trade = _trade("short", entry=100.0, current=90.0)
    with pytest.raises(ValueError, match="at/below short current"):
        compute_reissue_params(
            trade=trade, risk_params=_RiskParams(), reason="x",
            operator_stop_price=90.0,
        )


def test_short_stop_below_current_rejected():
    trade = _trade("short", entry=100.0, current=90.0)
    with pytest.raises(ValueError, match="at/below short current"):
        compute_reissue_params(
            trade=trade, risk_params=_RiskParams(), reason="x",
            operator_stop_price=85.0,
        )


# Original behavior preserved for losing/breakeven positions
def test_long_initial_stop_below_entry_below_current_accepted():
    trade = _trade("long", entry=100.0, current=105.0)
    plan = compute_reissue_params(
        trade=trade, risk_params=_RiskParams(), reason="initial",
        operator_stop_price=98.0,
    )
    assert plan.new_stop_price == 98.0


def test_long_drawdown_stop_below_entry_below_current_accepted():
    """Long is in drawdown. Stop $97 vs entry $100, current $98."""
    trade = _trade("long", entry=100.0, current=98.0)
    plan = compute_reissue_params(
        trade=trade, risk_params=_RiskParams(), reason="initial",
        operator_stop_price=97.0,
    )
    assert plan.new_stop_price == 97.0


def test_negative_stop_rejected():
    trade = _trade("long", entry=100.0, current=105.0)
    with pytest.raises(ValueError, match="must be > 0"):
        compute_reissue_params(
            trade=trade, risk_params=_RiskParams(), reason="x",
            operator_stop_price=-1.0,
        )
