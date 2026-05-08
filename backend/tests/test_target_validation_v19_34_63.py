"""
v19.34.63 — Target validation now uses current_price (not entry).

Mirrors the v19.34.62 stop fix. Pre-fix, `bracket_reissue_service.py`
rejected:
  • Long target ≤ entry (even if above current — drawdown-trim case)
  • Short target ≥ entry (even if below current)
And missed the genuine danger:
  • Long target between entry and current on a profitable position
    (would fire immediately at the next IB ack, instant fill at current)
The right rule is: target must be on the profit side of CURRENT price.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.bracket_reissue_service import compute_reissue_params


class _RiskParams:
    reconciled_default_stop_pct = 2.0


def _trade(direction: str, entry: float, current: float, shares: int = 100):
    return SimpleNamespace(
        id="t-1",
        symbol="MU",
        direction=SimpleNamespace(value=direction),
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
# THE BUG: drawdown trim should be allowed
# ────────────────────────────────────────────────────────────────────


def test_long_drawdown_trim_target_below_entry_above_current_accepted():
    """Long entry $100, current $95 (down $5). Operator wants to scale
    out at $98 (still down but cuts the bleed). $98 < entry but
    $98 > current → would not fire immediately → must be accepted."""
    trade = _trade("long", entry=100.0, current=95.0)
    plan = compute_reissue_params(
        trade=trade, risk_params=_RiskParams(), reason="drawdown_trim",
        operator_target_prices=[98.0],
    )
    assert 98.0 in plan.target_price_levels


def test_short_drawdown_trim_target_above_entry_below_current_accepted():
    """Short entry $100, current $105 (up $5 against us). Operator wants
    to cover a third at $102 (still down but limits damage)."""
    trade = _trade("short", entry=100.0, current=105.0, shares=300)
    plan = compute_reissue_params(
        trade=trade, risk_params=_RiskParams(), reason="drawdown_trim",
        operator_target_prices=[102.0],
    )
    assert 102.0 in plan.target_price_levels


# ────────────────────────────────────────────────────────────────────
# Genuine immediate-fire cases must still be rejected
# ────────────────────────────────────────────────────────────────────


def test_long_target_below_current_on_profitable_position_rejected():
    """Long entry $100, current $110. Operator moves target to $105 →
    would fire at current $110 → REJECT."""
    trade = _trade("long", entry=100.0, current=110.0)
    with pytest.raises(ValueError, match="at/below long current"):
        compute_reissue_params(
            trade=trade, risk_params=_RiskParams(), reason="x",
            operator_target_prices=[105.0],
        )


def test_long_target_at_current_rejected():
    trade = _trade("long", entry=100.0, current=110.0)
    with pytest.raises(ValueError, match="at/below long current"):
        compute_reissue_params(
            trade=trade, risk_params=_RiskParams(), reason="x",
            operator_target_prices=[110.0],
        )


def test_short_target_above_current_on_profitable_position_rejected():
    """Short entry $100, current $90. Operator moves target to $95 →
    would fire at current $90 → REJECT."""
    trade = _trade("short", entry=100.0, current=90.0)
    with pytest.raises(ValueError, match="at/above short current"):
        compute_reissue_params(
            trade=trade, risk_params=_RiskParams(), reason="x",
            operator_target_prices=[95.0],
        )


def test_short_target_at_current_rejected():
    trade = _trade("short", entry=100.0, current=90.0)
    with pytest.raises(ValueError, match="at/above short current"):
        compute_reissue_params(
            trade=trade, risk_params=_RiskParams(), reason="x",
            operator_target_prices=[90.0],
        )


# ────────────────────────────────────────────────────────────────────
# Original happy paths preserved
# ────────────────────────────────────────────────────────────────────


def test_long_normal_target_above_current_accepted():
    """Standard case: long, current $110, target $120. Above current → OK."""
    trade = _trade("long", entry=100.0, current=110.0)
    plan = compute_reissue_params(
        trade=trade, risk_params=_RiskParams(), reason="extend",
        operator_target_prices=[120.0],
    )
    assert 120.0 in plan.target_price_levels


def test_short_normal_target_below_current_accepted():
    trade = _trade("short", entry=100.0, current=90.0)
    plan = compute_reissue_params(
        trade=trade, risk_params=_RiskParams(), reason="extend",
        operator_target_prices=[80.0],
    )
    assert 80.0 in plan.target_price_levels


def test_multi_level_targets_validated_individually():
    """If ANY level fails the validation, the whole call rejects."""
    trade = _trade("long", entry=100.0, current=110.0)
    # First level OK ($115 > current), second level bad ($108 < current).
    with pytest.raises(ValueError, match="at/below long current"):
        compute_reissue_params(
            trade=trade, risk_params=_RiskParams(), reason="x",
            operator_target_prices=[115.0, 108.0],
        )


def test_multi_level_targets_all_valid_accepted():
    trade = _trade("long", entry=100.0, current=110.0)
    plan = compute_reissue_params(
        trade=trade, risk_params=_RiskParams(), reason="ladder",
        operator_target_prices=[115.0, 120.0, 125.0],
    )
    assert plan.target_price_levels == [115.0, 120.0, 125.0]


def test_negative_target_rejected():
    trade = _trade("long", entry=100.0, current=110.0)
    with pytest.raises(ValueError, match="non-positive"):
        compute_reissue_params(
            trade=trade, risk_params=_RiskParams(), reason="x",
            operator_target_prices=[-5.0],
        )
