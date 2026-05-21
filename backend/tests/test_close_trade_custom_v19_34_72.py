"""
v19.34.72 — Operator Close Panel (Market/Limit + partial) test suite.

Validates the new POST /api/trading-bot/trades/{trade_id}/close JSON body
flow without touching the bot's safety-critical 100%-MKT close path
(EOD, stop-loss, scale-out). Uses an in-memory bot stub that mimics
TradingBotService just enough to exercise PositionManager.close_trade_custom.
"""
import asyncio
import types
import uuid
from datetime import datetime, timezone

import pytest


# ─────────────────────────── Test scaffolding ──────────────────────────


class _DummyDailyStats:
    def __init__(self):
        self.date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.trades_executed = 0
        self.trades_won = 0
        self.trades_lost = 0
        self.gross_pnl = 0.0
        self.net_pnl = 0.0
        self.largest_win = 0.0
        self.largest_loss = 0.0
        self.win_rate = 0.0


class _DummyTrade:
    """Mirrors the BotTrade fields close_trade_custom touches."""
    def __init__(self, *, symbol="XLV", direction="long", shares=100,
                 fill_price=100.0, current_price=101.0):
        from services.trading_bot_service import TradeDirection, TradeStatus
        self.id = uuid.uuid4().hex
        self.symbol = symbol
        self.direction = TradeDirection.LONG if direction == "long" else TradeDirection.SHORT
        self.status = TradeStatus.OPEN
        self.shares = shares
        self.remaining_shares = shares
        self.original_shares = shares
        self.fill_price = fill_price
        self.current_price = current_price
        self.exit_price = None
        self.stop_price = fill_price * 0.97
        self.target_prices = [fill_price * 1.05]
        self.realized_pnl = 0.0
        self.unrealized_pnl = 0.0
        self.pnl_pct = 0.0
        self.total_commissions = 0.0
        self.net_pnl = 0.0
        self.commission_per_share = 0.005
        self.commission_min = 1.00
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.executed_at = self.created_at
        self.closed_at = None
        self.close_reason = None
        self.setup_type = "squeeze"
        self.alert_id = None
        self.scale_out_config = {"enabled": True, "targets_hit": [],
                                 "scale_out_pcts": [0.5, 0.5],
                                 "partial_exits": []}
        self.trailing_stop_config = {}
        self.market_regime = "RISK_ON"
        self.regime_score = 50.0
        self.regime_position_multiplier = 1.0
        self.setup_variant = ""
        self.entry_context = {}
        self.mfe_price = 0.0
        self.mfe_pct = 0.0
        self.mfe_r = 0.0
        self.mae_price = 0.0
        self.mae_pct = 0.0
        self.mae_r = 0.0


class _DummyExecutor:
    """Records what close_position_custom is called with and returns a
    canned response."""
    def __init__(self, response):
        self._response = response
        self.calls = []

    async def close_position_custom(self, trade, *, order_type, limit_price=None):
        self.calls.append({
            "trade_id": trade.id,
            "symbol": trade.symbol,
            "shares": int(trade.shares),
            "order_type": order_type,
            "limit_price": limit_price,
        })
        return self._response


class _DummyBot:
    """Tiny stand-in for TradingBotService.close_trade_custom only needs:
    _open_trades, _closed_trades, _daily_stats, _trade_executor,
    _apply_commission, _save_trade, _notify_trade_update,
    _log_trade_to_journal, _log_trade_to_regime_performance, _stop_manager.
    """
    def __init__(self, executor):
        self._open_trades = {}
        self._closed_trades = []
        self._daily_stats = _DummyDailyStats()
        self._trade_executor = executor
        self._stop_manager = types.SimpleNamespace(forget_trade=lambda _tid: None)
        self.saved = []
        self.notified = []
        self.journaled = []
        self.regime_logged = []

    def _apply_commission(self, trade, shares):
        commission = max(trade.commission_min,
                         round(shares * trade.commission_per_share, 2))
        trade.total_commissions = round(trade.total_commissions + commission, 2)
        trade.net_pnl = round(trade.realized_pnl - trade.total_commissions, 2)
        return commission

    async def _save_trade(self, trade):
        self.saved.append(trade.id)

    async def _notify_trade_update(self, trade, event):
        self.notified.append((trade.id, event))

    async def _log_trade_to_journal(self, trade, kind):
        self.journaled.append((trade.id, kind))

    async def _log_trade_to_regime_performance(self, trade):
        self.regime_logged.append(trade.id)


# ─────────────────────────── Tests ──────────────────────────


def _make(executor_response):
    from services.position_manager import PositionManager
    bot = _DummyBot(_DummyExecutor(executor_response))
    # Patch the phantom-share clamp to a no-op so we don't need IB.
    pm = PositionManager()
    async def _noop_clamp(self, trade, shares, reason="manual"):
        return shares
    pm._clamp_shares_to_ib_position = types.MethodType(_noop_clamp, pm)
    return pm, bot


def test_market_full_close_books_pnl_and_removes_trade():
    pm, bot = _make({
        "success": True, "order_id": 9999, "fill_price": 105.0,
        "filled_qty": 100, "remaining_qty": 0, "status": "filled",
    })
    trade = _DummyTrade(shares=100, fill_price=100.0, current_price=105.0)
    bot._open_trades[trade.id] = trade

    result = asyncio.get_event_loop().run_until_complete(
        pm.close_trade_custom(trade.id, bot, percentage=100,
                              order_type="market", reason="test_full_mkt")
    )
    assert result["success"] is True
    assert result["partial"] is False
    assert result["shares_closed"] == 100
    assert result["shares_remaining"] == 0
    # Trade removed from open, added to closed
    assert trade.id not in bot._open_trades
    assert bot._closed_trades and bot._closed_trades[-1].id == trade.id
    # PnL booked: (105 - 100) * 100 = $500, minus $1 commission min
    assert trade.realized_pnl == pytest.approx(500.0)
    assert trade.total_commissions >= 1.00
    # Executor called with order_type=market
    assert bot._trade_executor.calls[-1]["order_type"] == "market"
    assert bot._trade_executor.calls[-1]["shares"] == 100


def test_market_partial_close_keeps_trade_open():
    pm, bot = _make({
        "success": True, "order_id": 9998, "fill_price": 102.0,
        "filled_qty": 50, "remaining_qty": 50, "status": "filled",
    })
    trade = _DummyTrade(shares=100, fill_price=100.0, current_price=102.0)
    bot._open_trades[trade.id] = trade

    result = asyncio.get_event_loop().run_until_complete(
        pm.close_trade_custom(trade.id, bot, percentage=50,
                              order_type="market", reason="test_partial")
    )
    assert result["success"] is True
    assert result["partial"] is True
    assert result["shares_closed"] == 50
    assert result["shares_remaining"] == 50
    # Trade STILL OPEN, not in closed
    assert trade.id in bot._open_trades
    assert not bot._closed_trades
    # Realized PnL on the 50-share slice: (102 - 100) * 50 = $100
    assert trade.realized_pnl == pytest.approx(100.0)
    # partial_exits ledger populated
    assert len(trade.scale_out_config["partial_exits"]) == 1
    pe = trade.scale_out_config["partial_exits"][0]
    assert pe["source"] == "v19_34_72_operator_panel"
    assert pe["shares_sold"] == 50
    assert pe["order_type"] == "market"


def test_limit_close_requires_limit_price():
    pm, bot = _make({"success": False, "error": "should_not_be_called"})
    trade = _DummyTrade(shares=100)
    bot._open_trades[trade.id] = trade

    result = asyncio.get_event_loop().run_until_complete(
        pm.close_trade_custom(trade.id, bot, percentage=100,
                              order_type="limit", limit_price=None)
    )
    assert result["success"] is False
    assert "limit_price required" in result["error"]
    # Executor not called
    assert bot._trade_executor.calls == []


def test_limit_close_passes_price_to_executor():
    pm, bot = _make({
        "success": True, "order_id": 1234, "fill_price": 102.5,
        "filled_qty": 100, "remaining_qty": 0, "status": "filled",
        "order_type": "limit",
    })
    trade = _DummyTrade(shares=100, fill_price=100.0, current_price=102.0)
    bot._open_trades[trade.id] = trade

    result = asyncio.get_event_loop().run_until_complete(
        pm.close_trade_custom(trade.id, bot, percentage=100,
                              order_type="limit", limit_price=102.5)
    )
    assert result["success"] is True
    assert result["fill_price"] == 102.5
    call = bot._trade_executor.calls[-1]
    assert call["order_type"] == "limit"
    assert call["limit_price"] == 102.5


def test_limit_resting_at_ib_keeps_trade_open_no_pnl_booked():
    """LMT may legitimately return success+working with no fill yet."""
    pm, bot = _make({
        "success": True, "order_id": 5555, "fill_price": None,
        "filled_qty": 0, "remaining_qty": 100, "status": "working",
        "order_type": "limit",
    })
    trade = _DummyTrade(shares=100, fill_price=100.0, current_price=101.0)
    bot._open_trades[trade.id] = trade

    result = asyncio.get_event_loop().run_until_complete(
        pm.close_trade_custom(trade.id, bot, percentage=100,
                              order_type="limit", limit_price=120.0)
    )
    assert result["success"] is True
    assert result["status"] == "working"
    assert result["fill_price"] is None
    # Trade still open, no PnL booked
    assert trade.id in bot._open_trades
    assert trade.realized_pnl == 0.0


def test_unknown_trade_id_returns_error():
    pm, bot = _make({"success": False})
    result = asyncio.get_event_loop().run_until_complete(
        pm.close_trade_custom("does-not-exist", bot, percentage=100,
                              order_type="market")
    )
    assert result["success"] is False
    assert result["error"] == "trade_not_open"


def test_bad_percentage_rejected():
    pm, bot = _make({"success": False})
    trade = _DummyTrade(shares=100)
    bot._open_trades[trade.id] = trade

    for bad in (0, -5, 150, "abc"):
        result = asyncio.get_event_loop().run_until_complete(
            pm.close_trade_custom(trade.id, bot, percentage=bad,
                                  order_type="market")
        )
        assert result["success"] is False
        assert "percentage" in (result.get("error") or "").lower()
        assert bot._trade_executor.calls == []


def test_bad_order_type_rejected():
    pm, bot = _make({"success": False})
    trade = _DummyTrade(shares=100)
    bot._open_trades[trade.id] = trade

    result = asyncio.get_event_loop().run_until_complete(
        pm.close_trade_custom(trade.id, bot, percentage=100,
                              order_type="STOP_LIMIT")
    )
    assert result["success"] is False
    assert "order_type" in result["error"].lower()


def test_executor_failure_keeps_trade_open_and_stamps_error():
    pm, bot = _make({"success": False, "error": "ib_direct_not_connected"})
    trade = _DummyTrade(shares=100)
    bot._open_trades[trade.id] = trade

    result = asyncio.get_event_loop().run_until_complete(
        pm.close_trade_custom(trade.id, bot, percentage=100,
                              order_type="market")
    )
    assert result["success"] is False
    assert "ib_direct" in result["error"]
    # Trade still open, error stamped
    assert trade.id in bot._open_trades
    assert getattr(trade, "_last_close_error", "") == "ib_direct_not_connected"


def test_short_position_close_books_pnl_correctly():
    pm, bot = _make({
        "success": True, "order_id": 7777, "fill_price": 95.0,
        "filled_qty": 100, "remaining_qty": 0, "status": "filled",
    })
    trade = _DummyTrade(shares=100, direction="short",
                        fill_price=100.0, current_price=95.0)
    bot._open_trades[trade.id] = trade

    result = asyncio.get_event_loop().run_until_complete(
        pm.close_trade_custom(trade.id, bot, percentage=100,
                              order_type="market")
    )
    assert result["success"] is True
    # Short PnL: (100 - 95) * 100 = $500
    assert trade.realized_pnl == pytest.approx(500.0)


def test_router_endpoint_accepts_body_and_dispatches_custom():
    """Smoke-test the FastAPI router signature: it must accept an
    optional JSON body and call close_trade_custom on the bot when
    provided."""
    from routers import trading_bot as router_mod

    # Stub a bot whose close_trade_custom is awaitable
    captured = {}

    class _StubBot:
        async def close_trade_custom(self, trade_id, *, percentage,
                                     order_type, limit_price, reason):
            captured.update({
                "trade_id": trade_id, "percentage": percentage,
                "order_type": order_type, "limit_price": limit_price,
                "reason": reason,
            })
            return {"success": True, "trade_id": trade_id, "shares_closed": 50,
                    "shares_remaining": 50, "order_type": order_type,
                    "limit_price": limit_price, "fill_price": 102.5,
                    "order_id": 12345, "status": "filled", "partial": True}

        async def close_trade(self, *a, **kw):  # legacy fallback
            return True

        def get_trade(self, tid):
            return None

    # Patch module-global
    prev = router_mod._trading_bot
    router_mod._trading_bot = _StubBot()
    try:
        body = router_mod.CloseTradeRequest(
            percentage=50, order_type="limit", limit_price=102.5,
            reason="v5_operator_close_panel",
        )
        result = asyncio.get_event_loop().run_until_complete(
            router_mod.close_trade("trade-abc", reason="manual", body=body)
        )
        assert result["success"] is True
        assert result["partial"] is True
        assert captured["trade_id"] == "trade-abc"
        assert captured["percentage"] == 50
        assert captured["order_type"] == "limit"
        assert captured["limit_price"] == 102.5
        assert captured["reason"] == "v5_operator_close_panel"
    finally:
        router_mod._trading_bot = prev


def test_router_endpoint_no_body_uses_legacy_path():
    """When called without body, must use the legacy 100%-MKT close_trade."""
    from routers import trading_bot as router_mod

    legacy_called = {"count": 0}

    class _StubBot:
        async def close_trade(self, trade_id, reason="manual"):
            legacy_called["count"] += 1
            return True

        async def close_trade_custom(self, *a, **kw):
            raise AssertionError("custom must NOT be called when body is None")

        def get_trade(self, tid):
            return {"id": tid, "status": "closed"}

    prev = router_mod._trading_bot
    router_mod._trading_bot = _StubBot()
    try:
        result = asyncio.get_event_loop().run_until_complete(
            router_mod.close_trade("trade-xyz", reason="manual", body=None)
        )
        assert result["success"] is True
        assert legacy_called["count"] == 1
    finally:
        router_mod._trading_bot = prev
