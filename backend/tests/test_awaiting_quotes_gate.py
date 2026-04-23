"""
P1 regression: awaiting-quotes gate in trading_bot_service._execute_trade.

Before this fix:
  - `_daily_stats.realized_pnl` / `.unrealized_pnl` don't exist on DailyStats
    → the guardrail check silently AttributeError'd and fail-closed blocked
    every trade.
  - Even if fields existed, positions loaded from the broker BEFORE IB
    pushes the first quote have `current_price == 0`, which makes the
    per-trade unrealized PnL = -(fill_price * shares), producing a fake
    multi-million-dollar loss that trips the daily-loss kill-switch.

The fix adds `_compute_live_unrealized_pnl()` which:
  - Sums `trade.unrealized_pnl` across all open trades
  - Returns `awaiting_quotes=True` if ANY open trade is missing a quote
    (current_price or fill_price <= 0) and suppresses the PnL total
  - The caller passes 0 into the guardrail in that case
"""
import pytest

from services.trading_bot_service import (
    TradingBotService,
    BotTrade,
    TradeDirection,
    TradeStatus,
    DailyStats,
)


def _make_trade(symbol, direction, fill_price, current_price, shares=100,
                entry_price=100.0, stop_price=95.0, unrealized_pnl=0.0):
    return BotTrade(
        id=f"t_{symbol}",
        symbol=symbol,
        direction=direction,
        status=TradeStatus.OPEN,
        setup_type="orb",
        timeframe="5m",
        quality_score=70.0,
        quality_grade="B",
        entry_price=entry_price,
        current_price=current_price,
        stop_price=stop_price,
        target_prices=[105.0, 110.0, 115.0],
        shares=shares,
        risk_amount=100.0,
        potential_reward=200.0,
        risk_reward_ratio=2.0,
        fill_price=fill_price,
        unrealized_pnl=unrealized_pnl,
    )


@pytest.fixture
def bot():
    b = TradingBotService()
    b._open_trades = {}
    b._daily_stats = DailyStats(date="2026-04-22")
    return b


def test_awaiting_quotes_no_positions_returns_ok(bot):
    pnl, awaiting = bot._compute_live_unrealized_pnl()
    assert pnl == 0.0
    assert awaiting is False


def test_awaiting_quotes_all_have_quotes_returns_sum(bot):
    t1 = _make_trade("AAPL", TradeDirection.LONG, fill_price=150.0,
                     current_price=152.0, unrealized_pnl=200.0)
    t2 = _make_trade("MSFT", TradeDirection.LONG, fill_price=300.0,
                     current_price=298.0, unrealized_pnl=-200.0)
    bot._open_trades = {t1.id: t1, t2.id: t2}
    pnl, awaiting = bot._compute_live_unrealized_pnl()
    assert awaiting is False
    assert pnl == pytest.approx(0.0)  # 200 - 200


def test_awaiting_quotes_zero_current_price_triggers_gate(bot):
    """The phantom -$1.2M scenario: quote hasn't arrived, current_price=0."""
    t = _make_trade("AAPL", TradeDirection.LONG, fill_price=1200.0,
                    current_price=0.0, shares=1000,
                    unrealized_pnl=-1_200_000.0)  # phantom huge loss
    bot._open_trades = {t.id: t}
    pnl, awaiting = bot._compute_live_unrealized_pnl()
    assert awaiting is True
    assert pnl == 0.0  # MUST suppress garbage — would otherwise trip kill-switch


def test_awaiting_quotes_zero_fill_price_triggers_gate(bot):
    t = _make_trade("AAPL", TradeDirection.LONG, fill_price=0.0,
                    current_price=150.0, unrealized_pnl=1000.0)
    bot._open_trades = {t.id: t}
    pnl, awaiting = bot._compute_live_unrealized_pnl()
    assert awaiting is True
    assert pnl == 0.0


def test_awaiting_quotes_partial_readiness_still_blocks_sum(bot):
    """Mixed: one trade has a quote, another doesn't → gate engages."""
    good = _make_trade("AAPL", TradeDirection.LONG, fill_price=150.0,
                       current_price=152.0, unrealized_pnl=200.0)
    bad = _make_trade("NVDA", TradeDirection.LONG, fill_price=900.0,
                      current_price=0.0, unrealized_pnl=-900_000.0)
    bot._open_trades = {good.id: good, bad.id: bad}
    pnl, awaiting = bot._compute_live_unrealized_pnl()
    assert awaiting is True
    assert pnl == 0.0


def test_awaiting_quotes_negative_live_pnl_propagates_when_safe(bot):
    """Once all quotes are in, real losses SHOULD feed into the guardrail."""
    t = _make_trade("AAPL", TradeDirection.LONG, fill_price=150.0,
                    current_price=140.0, shares=100,
                    unrealized_pnl=-1000.0)
    bot._open_trades = {t.id: t}
    pnl, awaiting = bot._compute_live_unrealized_pnl()
    assert awaiting is False
    assert pnl == pytest.approx(-1000.0)


def test_daily_stats_has_no_unrealized_pnl_field():
    """Lock: confirm DailyStats does NOT have a field of this name.
    The previous code read `_daily_stats.unrealized_pnl` directly,
    AttributeError'ing at runtime and fail-closed-blocking every trade.
    Fix now uses _compute_live_unrealized_pnl() instead.
    """
    ds = DailyStats(date="2026-04-22")
    assert not hasattr(ds, "unrealized_pnl")
    assert not hasattr(ds, "realized_pnl")
    # The field the fix now reads instead:
    assert hasattr(ds, "net_pnl")
