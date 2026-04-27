"""
Tests for `TradingBotService._get_account_value` IB-first resolution.

2026-04-28 fix: bot was always returning $100k after Phase 4 Alpaca
retirement because `_get_account_value` only checked Alpaca (now
None). Now reads NetLiquidation from `routers.ib._pushed_ib_data`
first.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def bot():
    from services.trading_bot_service import TradingBotService

    b = TradingBotService()
    b._alpaca_service = None  # Phase 4 default
    return b


@pytest.mark.asyncio
async def test_account_value_reads_ib_pushed_net_liquidation(bot):
    """When IB pusher has pushed NetLiquidation, it must be used."""
    fake_account = {
        "NetLiquidation": "247500.00",
        "BuyingPower": "100000.00",
    }
    with patch.dict(
        "routers.ib._pushed_ib_data",
        {"account": fake_account},
        clear=False,
    ):
        with patch(
            "routers.ib._extract_account_value",
            side_effect=lambda acc, key, default: float(acc.get(key, default) or default),
        ):
            v = await bot._get_account_value()
    assert v == 247500.0
    # Side-effect: starting_capital should sync with the live value.
    assert bot.risk_params.starting_capital == 247500.0


@pytest.mark.asyncio
async def test_account_value_falls_back_to_starting_capital_when_no_ib(bot):
    """No IB push + no Alpaca → fall back to risk_params.starting_capital."""
    bot.risk_params.starting_capital = 50_000
    with patch.dict("routers.ib._pushed_ib_data", {"account": {}}, clear=False):
        v = await bot._get_account_value()
    assert v == 50_000


@pytest.mark.asyncio
async def test_account_value_falls_back_to_100k_when_starting_capital_unset(bot):
    """Last-resort: 100k when nothing else is configured."""
    bot.risk_params.starting_capital = 0
    with patch.dict("routers.ib._pushed_ib_data", {"account": {}}, clear=False):
        v = await bot._get_account_value()
    assert v == 100_000


@pytest.mark.asyncio
async def test_account_value_does_not_trust_zero_net_liquidation(bot):
    """IB sometimes reports NetLiquidation=0 momentarily during reconnect.
    Must NOT overwrite starting_capital with zero — fall through."""
    bot.risk_params.starting_capital = 50_000
    fake_account = {"NetLiquidation": "0.00"}
    with patch.dict(
        "routers.ib._pushed_ib_data",
        {"account": fake_account},
        clear=False,
    ):
        with patch(
            "routers.ib._extract_account_value",
            side_effect=lambda acc, key, default: 0.0,
        ):
            v = await bot._get_account_value()
    assert v == 50_000  # not 0
    assert bot.risk_params.starting_capital == 50_000


@pytest.mark.asyncio
async def test_account_value_alpaca_used_only_if_explicitly_enabled(bot):
    """If operator manually re-enables Alpaca AND IB has nothing, use it."""
    # Mock Alpaca returning 75k.
    fake_alpaca = MagicMock()
    async def _get_account():
        return {"portfolio_value": 75_000}
    fake_alpaca.get_account = _get_account
    bot._alpaca_service = fake_alpaca

    with patch.dict("routers.ib._pushed_ib_data", {"account": {}}, clear=False):
        v = await bot._get_account_value()
    assert v == 75_000
