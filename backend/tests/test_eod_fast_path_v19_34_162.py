"""Tests for v19.34.162 EOD fast-path close.

The fast-path bypasses the v19.34.31 Patch B pre-close cancellation
(which queued IB cancels for every bracket child before firing the
MKT close — a sequential 10s-timeout queue that completely blocked
today's 2026-05-26 EOD pass with 24 open positions).

This suite verifies:
  1. The fast-path correctly fires MKT close and skips cancel queue.
  2. Phantom-share clamp still runs (safety-critical).
  3. Direction mismatch (clamp returns 0) marks trade CLOSED locally
     without firing any order.
  4. Executor failure leaves trade OPEN for retry (no false-CLOSED).
  5. The orphan sweep enumerates PreSubmitted/Submitted orders only.
  6. Successful fast-close stamps `close_reason='eod_auto_close_v162'`
     and writes a `bracket_lifecycle_events` row with
     `phase='eod_flatten_v162'`.
  7. Daily stats accumulate correctly (trades_won / trades_lost /
     net_pnl) post-close.

Run:
    cd /app/backend && PYTHONPATH=. python3 -m pytest \
        tests/test_eod_fast_path_v19_34_162.py -v
"""
from __future__ import annotations

import asyncio
import os
import sys
import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)


@pytest.fixture
def position_manager():
    # Force-import the REAL ib_direct_service first so its IBDirectService
    # class remains importable for downstream tests in the same session
    # (mirrors v19.34.158 isolation fix).
    try:
        import services.ib_direct_service  # noqa: F401
    except Exception:
        pass
    from services.position_manager import PositionManager
    pm = PositionManager.__new__(PositionManager)
    return pm


@pytest.fixture
def trade():
    """Long position, 100 shares, intended to be closed at MKT."""
    from services.trading_bot_service import TradeDirection, TradeStatus
    t = types.SimpleNamespace()
    t.id = "trade-test-001"
    t.symbol = "AAPL"
    t.direction = TradeDirection.LONG
    t.status = TradeStatus.OPEN
    t.shares = 100
    t.remaining_shares = 100
    t.fill_price = 150.0
    t.entry_price = 150.0
    t.current_price = 155.0
    t.exit_price = None
    t.realized_pnl = 0.0
    t.net_pnl = 0.0
    t.unrealized_pnl = 500.0
    t.total_commissions = 0.0
    t.close_reason = None
    t.closed_at = None
    t.target_prices = [160.0]
    t.stop_price = 148.0
    return t


@pytest.fixture
def bot(trade):
    """Mock TradingBotService with the bits position_manager touches."""
    bot = MagicMock()
    bot._open_trades = {trade.id: trade}
    bot._closed_trades = []
    bot._daily_stats = types.SimpleNamespace(
        net_pnl=0.0, trades_won=0, trades_lost=0,
        largest_win=0.0, largest_loss=0.0, win_rate=0.0,
    )
    bot._db = None
    bot._apply_commission = MagicMock(return_value=0.0)
    bot._save_trade = AsyncMock()
    bot._trade_executor = MagicMock()
    bot._trade_executor.close_position = AsyncMock(
        return_value={"success": True, "fill_price": 155.10}
    )
    return bot


async def _no_clamp(self, trade, shares, reason=None):
    """Default clamp = no-op (returns the bot-tracked count)."""
    return shares


async def _phantom_clamp(self, trade, shares, reason=None):
    """Phantom-clamp = 0 (IB shows no position)."""
    return 0


# ── tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fast_path_happy_long_marks_closed_and_books_pnl(
    monkeypatch, position_manager, trade, bot
):
    monkeypatch.setattr(
        type(position_manager), "_clamp_shares_to_ib_position",
        _no_clamp, raising=False,
    )

    ok, pnl = await position_manager._eod_close_one_fast(trade.id, trade, bot)

    assert ok is True
    # 100 shares × ($155.10 - $150.00) = $510 realized
    assert pnl == pytest.approx(510.0, abs=0.01)
    assert trade.close_reason == "eod_auto_close_v162"
    from services.trading_bot_service import TradeStatus
    assert trade.status == TradeStatus.CLOSED
    assert trade.id not in bot._open_trades
    assert trade in bot._closed_trades
    # Daily stats
    assert bot._daily_stats.trades_won == 1
    assert bot._daily_stats.trades_lost == 0
    bot._save_trade.assert_awaited_once_with(trade)


@pytest.mark.asyncio
async def test_fast_path_short_pnl_sign_correct(
    monkeypatch, position_manager, trade, bot
):
    from services.trading_bot_service import TradeDirection
    trade.direction = TradeDirection.SHORT
    trade.fill_price = 150.0
    bot._trade_executor.close_position = AsyncMock(
        return_value={"success": True, "fill_price": 145.0}
    )
    monkeypatch.setattr(
        type(position_manager), "_clamp_shares_to_ib_position",
        _no_clamp, raising=False,
    )

    ok, pnl = await position_manager._eod_close_one_fast(trade.id, trade, bot)
    assert ok is True
    # SHORT covered at 145 from entry 150 → +5 × 100 = +$500
    assert pnl == pytest.approx(500.0, abs=0.01)


@pytest.mark.asyncio
async def test_fast_path_phantom_clamp_marks_closed_locally_no_executor_call(
    monkeypatch, position_manager, trade, bot
):
    monkeypatch.setattr(
        type(position_manager), "_clamp_shares_to_ib_position",
        _phantom_clamp, raising=False,
    )

    ok, pnl = await position_manager._eod_close_one_fast(trade.id, trade, bot)
    assert ok is True
    # No MKT close fired — phantom recovery path.
    bot._trade_executor.close_position.assert_not_awaited()
    from services.trading_bot_service import TradeStatus
    assert trade.status == TradeStatus.CLOSED
    assert trade.id not in bot._open_trades


@pytest.mark.asyncio
async def test_fast_path_executor_failure_keeps_trade_open(
    monkeypatch, position_manager, trade, bot
):
    bot._trade_executor.close_position = AsyncMock(
        return_value={"success": False, "error": "ib_timeout"}
    )
    monkeypatch.setattr(
        type(position_manager), "_clamp_shares_to_ib_position",
        _no_clamp, raising=False,
    )

    ok, pnl = await position_manager._eod_close_one_fast(trade.id, trade, bot)
    assert ok is False
    assert pnl == 0.0
    # Trade stays OPEN so the manage loop retries.
    assert trade.id in bot._open_trades
    from services.trading_bot_service import TradeStatus
    assert trade.status != TradeStatus.CLOSED
    # Last-close-error stamp set for operator visibility.
    assert getattr(trade, "_last_close_error", None) == "ib_timeout"


@pytest.mark.asyncio
async def test_fast_path_missing_executor_returns_false(
    monkeypatch, position_manager, trade, bot
):
    bot._trade_executor = None
    monkeypatch.setattr(
        type(position_manager), "_clamp_shares_to_ib_position",
        _no_clamp, raising=False,
    )
    ok, pnl = await position_manager._eod_close_one_fast(trade.id, trade, bot)
    assert ok is False
    assert pnl == 0.0
    assert trade.id in bot._open_trades


@pytest.mark.asyncio
async def test_fast_path_unknown_trade_returns_false_immediately(
    monkeypatch, position_manager, bot
):
    monkeypatch.setattr(
        type(position_manager), "_clamp_shares_to_ib_position",
        _no_clamp, raising=False,
    )
    ok, pnl = await position_manager._eod_close_one_fast("nonexistent", None, bot)
    assert ok is False
    assert pnl == 0.0


@pytest.mark.asyncio
async def test_fast_path_writes_bracket_lifecycle_event(
    monkeypatch, position_manager, trade, bot
):
    inserted = {}
    bot._db = MagicMock()
    bot._db.bracket_lifecycle_events.insert_one = lambda doc: inserted.update(doc)
    monkeypatch.setattr(
        type(position_manager), "_clamp_shares_to_ib_position",
        _no_clamp, raising=False,
    )

    ok, _ = await position_manager._eod_close_one_fast(trade.id, trade, bot)
    assert ok is True
    assert inserted.get("phase") == "eod_flatten_v162"
    assert inserted.get("symbol") == "AAPL"
    assert inserted.get("shares_closed") == 100
    assert inserted.get("success") is True


@pytest.mark.asyncio
async def test_orphan_sweep_queues_only_live_orders(monkeypatch, position_manager, bot):
    """Sweep enumerates _pushed_ib_data['orders'] and queues PreSubmitted /
    Submitted orders only. Filled / Cancelled / unknown are skipped."""
    queued_ids = []

    def fake_queue(ib_order_id, reason, requested_by):
        queued_ids.append(ib_order_id)

    import routers.ib as ib_mod
    monkeypatch.setattr(ib_mod, "_pushed_ib_data", {
        "orders": [
            {"order_id": 100, "status": "PreSubmitted", "symbol": "AAPL"},
            {"order_id": 101, "status": "Submitted",    "symbol": "MSFT"},
            {"order_id": 102, "status": "Filled",       "symbol": "USO"},
            {"order_id": 103, "status": "Cancelled",    "symbol": "BP"},
            {"order_id": 104, "status": "",             "symbol": ""},
        ],
    }, raising=False)
    monkeypatch.setattr(ib_mod, "queue_cancellation", fake_queue, raising=False)

    await position_manager._eod_orphan_cancel_sweep(bot)
    assert set(queued_ids) == {100, 101}
