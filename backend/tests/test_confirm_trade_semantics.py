"""Regression test for `TradeExecution.confirm_trade` success-semantics fix.

Bug (pre-2026-04-23): the method returned `trade.status == TradeStatus.OPEN`
only, so correctly-filtered trades (SIMULATED by phase gate, VETOED by
guardrail, PAPER by phase gate) reported as API failures (400). The fix
treats every legitimately-handled terminal status as success. The router
then distinguishes the outcomes in the HTTP response.

These tests mock out the dependent `execute_trade` call so they run natively
without a broker, MongoDB, or event loop surprises.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace
from datetime import datetime, timezone

from services.trade_execution import TradeExecution
from services.trading_bot_service import TradeStatus


def _mk_trade(status: TradeStatus, symbol: str = "AAPL") -> SimpleNamespace:
    """Minimal trade stub — confirm_trade only needs a handful of attrs."""
    return SimpleNamespace(
        id="tid-test",
        symbol=symbol,
        timeframe="day",
        setup_type="rubber_band_long",
        created_at=datetime.now(timezone.utc).isoformat(),
        entry_price=100.0,
        stop_price=98.0,
        shares=10,
        remaining_shares=10,
        original_shares=10,
        scale_out_config={"target_prices": [104.0]},
        notes="",
        status=status,
    )


def _mk_bot(trade) -> MagicMock:
    bot = MagicMock()
    bot._pending_trades = {trade.id: trade}
    bot._alpaca_service = None
    bot._notify_trade_update = AsyncMock()
    bot._save_trade = AsyncMock()
    bot.risk_params = SimpleNamespace(max_risk_per_trade=100.0)
    return bot


def _run_confirm(trade):
    """Run confirm_trade with execute_trade stubbed to leave status unchanged.

    Since execute_trade is responsible for setting final status, we replace
    it with a no-op that preserves whatever status the test pre-sets on the
    trade object — that lets us unit-test every branch of confirm_trade's
    success-semantics deterministically.
    """
    exec_svc = TradeExecution()
    # Stub execute_trade so the terminal status is whatever we pre-set
    exec_svc.execute_trade = AsyncMock()
    bot = _mk_bot(trade)
    return asyncio.run(exec_svc.confirm_trade(trade.id, bot))


def test_confirm_returns_true_when_trade_opens():
    """Happy path — trade executed and position opened."""
    trade = _mk_trade(TradeStatus.OPEN)
    assert _run_confirm(trade) is True


def test_confirm_returns_true_for_simulated_phase_gate():
    """REGRESSION: SIMULATED strategies were returning False and 400-ing the UI."""
    trade = _mk_trade(TradeStatus.SIMULATED)
    assert _run_confirm(trade) is True, \
        "SIMULATED status must be treated as correctly-handled, not as failure"


def test_confirm_returns_true_for_paper_phase_gate():
    """REGRESSION: PAPER strategies were returning False and 400-ing the UI."""
    trade = _mk_trade(TradeStatus.PAPER)
    assert _run_confirm(trade) is True, \
        "PAPER status must be treated as correctly-handled, not as failure"


def test_confirm_returns_true_for_vetoed_guardrail():
    """REGRESSION: VETOED (pre-trade guardrail) must be success, not 400."""
    trade = _mk_trade(TradeStatus.VETOED)
    assert _run_confirm(trade) is True, \
        "VETOED status must be treated as correctly-handled, not as failure"


def test_confirm_returns_true_for_partial_fill():
    """Partial fills are a legitimate broker outcome — not a failure."""
    trade = _mk_trade(TradeStatus.PARTIAL)
    assert _run_confirm(trade) is True


def test_confirm_returns_false_for_rejected():
    """Genuine broker/system rejection should still surface as failure."""
    trade = _mk_trade(TradeStatus.REJECTED)
    assert _run_confirm(trade) is False


def test_confirm_returns_false_for_missing_trade():
    """Unknown trade_id → False so the router can raise 404."""
    exec_svc = TradeExecution()
    bot = MagicMock()
    bot._pending_trades = {}
    result = asyncio.run(exec_svc.confirm_trade("nonexistent-id", bot))
    assert result is False


def test_confirm_returns_false_for_stale_alert():
    """Expired alerts remain a legitimate 'no' — kept as False by design."""
    trade = _mk_trade(TradeStatus.PENDING)
    # Force the alert to look ancient (30 min old, past day-timeframe 10 min cap)
    old_ts = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
    trade.created_at = old_ts

    exec_svc = TradeExecution()
    exec_svc.execute_trade = AsyncMock()
    bot = _mk_bot(trade)
    result = asyncio.run(exec_svc.confirm_trade(trade.id, bot))

    assert result is False
    # Trade was moved to REJECTED and dropped from pending
    assert trade.status == TradeStatus.REJECTED
    # execute_trade was NOT called — we short-circuited on stale
    exec_svc.execute_trade.assert_not_called()
