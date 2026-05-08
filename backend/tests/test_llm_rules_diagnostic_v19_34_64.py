"""
v19.34.64 — `/api/trading-bot/llm-rules` diagnostic endpoint.

Verifies the equity-tied formulas the chat-AI enforces (per v19.34.63):
  • risk_per_trade_cap = max(0.01 × equity, $2,500)
  • position_count_cap = max(10, floor(equity / $25K))
  • daily_loss_budget = 0.01 × equity
  • daily_loss_breached when realized_pnl_pct ≤ -1%

These are pure unit tests of the math; they don't hit the live IB
account endpoint or backend bot state.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _patch_account(equity: float, daily_pnl: float, daily_pnl_pct: float):
    """Return a context manager that mocks the requests.get call to
    `/api/ib/account/summary`."""
    fake_resp = MagicMock()
    fake_resp.ok = True
    fake_resp.json.return_value = {
        "net_liquidation": equity,
        "daily_pnl": daily_pnl,
        "daily_pnl_percent": daily_pnl_pct,
    }
    return patch("requests.get", return_value=fake_resp)


def _patch_bot(open_positions_count: int):
    """Replace routers.trading_bot._trading_bot with a mock having
    _open_trades populated to the given count."""
    fake_bot = MagicMock()
    fake_bot._open_trades = {f"t{i}": object() for i in range(open_positions_count)}
    return patch("routers.trading_bot._trading_bot", fake_bot)


@pytest.mark.asyncio
async def test_small_account_uses_2500_floor():
    """At $100K equity, 1% × equity = $1,000 — but floor is $2,500."""
    from routers.trading_bot import llm_rules
    with _patch_account(100_000.0, 0.0, 0.0), _patch_bot(5):
        res = await llm_rules()
    assert res["success"] is True
    assert res["equity"] == 100_000.0
    assert res["risk_per_trade_cap"] == 2500.0  # floor applied
    assert res["position_count_cap"] == max(10, int(100_000 // 25_000))  # = 10
    assert res["daily_loss_budget"] == 1000.0


@pytest.mark.asyncio
async def test_medium_account_237k_matches_operator_state():
    """Operator's actual account today: $237K → risk $2,500 (still floor),
    position cap 10 (237K // 25K = 9, max with 10 = 10), DLP $2,370."""
    from routers.trading_bot import llm_rules
    with _patch_account(237_000.0, -946.71, -0.40), _patch_bot(11):
        res = await llm_rules()
    assert res["risk_per_trade_cap"] == 2500.0  # 1% of 237K = 2370, floor wins
    assert res["position_count_cap"] == 10
    assert res["daily_loss_budget"] == 2370.0
    # 11 positions vs cap 10 → at cap = True
    assert res["live_state"]["at_or_over_position_cap"] is True
    assert res["live_state"]["open_positions_count"] == 11
    # -0.4% daily pnl → not breached (-1% threshold)
    assert res["live_state"]["daily_loss_breached"] is False


@pytest.mark.asyncio
async def test_large_account_scales_up():
    """At $400K, risk = 1% × 400K = $4,000 (above floor); cap = 16 positions."""
    from routers.trading_bot import llm_rules
    with _patch_account(400_000.0, 1500.0, 0.38), _patch_bot(8):
        res = await llm_rules()
    assert res["risk_per_trade_cap"] == 4000.0
    assert res["position_count_cap"] == 16
    assert res["daily_loss_budget"] == 4000.0
    assert res["live_state"]["at_or_over_position_cap"] is False


@pytest.mark.asyncio
async def test_daily_loss_breach_detected():
    """At -1.5% daily pnl on a $200K account → breached flag fires."""
    from routers.trading_bot import llm_rules
    with _patch_account(200_000.0, -3000.0, -1.50), _patch_bot(5):
        res = await llm_rules()
    assert res["live_state"]["daily_loss_breached"] is True
    assert res["live_state"]["today_realized_pnl"] == -3000.0


@pytest.mark.asyncio
async def test_daily_loss_at_exact_threshold():
    """-1.0% exactly → breach fires (`≤ -1%` inclusive)."""
    from routers.trading_bot import llm_rules
    with _patch_account(200_000.0, -2000.0, -1.0), _patch_bot(5):
        res = await llm_rules()
    assert res["live_state"]["daily_loss_breached"] is True


@pytest.mark.asyncio
async def test_zero_equity_falls_back_safely():
    """If equity fetch fails / returns 0, defaults apply, no crash."""
    from routers.trading_bot import llm_rules
    with _patch_account(0.0, 0.0, 0.0), _patch_bot(0):
        res = await llm_rules()
    assert res["success"] is True
    assert res["equity"] == 0.0
    assert res["risk_per_trade_cap"] == 2500.0  # default
    assert res["position_count_cap"] == 10  # default
    assert res["daily_loss_budget"] == 0.0


@pytest.mark.asyncio
async def test_account_fetch_exception_does_not_crash():
    """Network error on account-summary → endpoint still returns a 
    sensible default response."""
    from routers.trading_bot import llm_rules
    with patch("requests.get", side_effect=ConnectionError("boom")), \
         _patch_bot(3):
        res = await llm_rules()
    assert res["success"] is True
    assert res["equity"] == 0.0
    assert res["risk_per_trade_cap"] == 2500.0
    assert res["live_state"]["open_positions_count"] == 3


@pytest.mark.asyncio
async def test_rules_text_includes_all_8_rules():
    """Tooltip shows all 8 rule lines."""
    from routers.trading_bot import llm_rules
    with _patch_account(237_000.0, 0.0, 0.0), _patch_bot(5):
        res = await llm_rules()
    text = res["rules_text"]
    assert isinstance(text, list)
    assert len(text) >= 7  # minimum bar — includes all material rules
    joined = " ".join(text).lower()
    assert "risk" in joined
    assert "position-count cap" in joined
    assert "daily loss budget" in joined
    assert "concentration" in joined
    assert "r:r" in joined
    assert "trail stop" in joined
    assert "drawdown-trim" in joined
