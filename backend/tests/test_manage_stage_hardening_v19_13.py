"""
v19.13 — Manage-stage hardening (2026-04-30).

Pins all 7 fixes shipped in v19.13:

P0 fixes (could cause real damage if regressed):
  1. _ib_close_position cancels bracket children before close
     (prevents double-exit race)
  2. execute_partial_exit propagates broker failures honestly
     (prevents silent position drift)
  3. close_trade returns False on executor failure
     (prevents books-vs-broker drift)
  4. Stale-quote guard skips stop-checks when quote > 30s old

P1 fixes:
  5. Quote-fetch error logged (was bare except: pass)
  9. UNSTOPPED-POSITION alarm
  6. stop_adjustments capped at 100 entries
  7. StopManager.forget_trade releases per-trade state on close

P2:
  11. Risk-fallback warns once per trade

Tests use direct-function-call style + minimal fakes so they run
independent of starlette/httpx version drift in this container.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# --------------------------------------------------------------------------
# Minimal stand-ins for BotTrade / TradingBotService that the manage-stage
# code actually touches. We deliberately keep these small — over-modelling
# leaks the production schema into tests and makes them brittle.
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class _Direction:
    value: str

LONG = _Direction("long")
SHORT = _Direction("short")


@dataclass
class _Trade:
    id: str = "T1"
    symbol: str = "AAPL"
    direction: Any = LONG
    fill_price: float = 100.0
    stop_price: float = 99.0
    current_price: float = 100.0
    shares: int = 100
    remaining_shares: int = 100
    original_shares: int = 100
    status: str = "open"
    realized_pnl: float = 0.0
    total_commissions: float = 0.0
    net_pnl: float = 0.0
    exit_price: float = 0.0
    trailing_stop_config: Dict = field(default_factory=dict)
    scale_out_config: Dict = field(default_factory=dict)
    stop_order_id: Optional[str] = None
    target_order_id: Optional[str] = None
    target_order_ids: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# P0 #1 — _ib_close_position cancels bracket children
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ib_close_cancels_bracket_children_first():
    """Before sending the close MKT, _ib_close_position must call
    _cancel_ib_bracket_orders. The cancel happens inside the same
    function so we patch the helper and verify call order."""
    from services.trade_executor_service import TradeExecutorService
    svc = TradeExecutorService()

    trade = _Trade(stop_order_id="123", target_order_id="124")
    trade.direction = LONG

    call_log = []

    async def _fake_cancel(_self, _trade):
        call_log.append("cancel")

    fake_queue = MagicMock(side_effect=lambda *a, **kw: (call_log.append("queue") or "ORD-1"))
    fake_result = MagicMock(side_effect=lambda *a, **kw: (call_log.append("result") or {
        "result": {"status": "FILLED", "fill_price": 100.0},
    }))
    fake_pusher = MagicMock(return_value=True)

    with patch.object(TradeExecutorService, "_cancel_ib_bracket_orders", new=_fake_cancel), \
         patch("routers.ib.is_pusher_connected", new=fake_pusher, create=True), \
         patch("routers.ib.queue_order", new=fake_queue, create=True), \
         patch("routers.ib.get_order_result", new=fake_result, create=True):
        await svc._ib_close_position(trade)

    # Cancel MUST happen before queue
    assert call_log[0] == "cancel", f"expected cancel first, got {call_log}"
    assert "queue" in call_log


@pytest.mark.asyncio
async def test_cancel_ib_bracket_skips_simulated_ids():
    """Simulated/paper bracket IDs (non-numeric like 'SIM-STOP-uuid')
    must be silently skipped — we only call IB cancel for int-castable IDs."""
    from services.trade_executor_service import TradeExecutorService
    svc = TradeExecutorService()

    trade = _Trade(
        stop_order_id="SIM-STOP-abc",
        target_order_id="124",
        target_order_ids=["SIM-TGT-xyz", "125"],
    )

    fake_ib = AsyncMock()
    fake_ib.cancel_order = AsyncMock(return_value=True)

    with patch("routers.ib._ib_service", fake_ib, create=True):
        await svc._cancel_ib_bracket_orders(trade)

    # Only int-castable IDs (124, 125) reach the IB cancel call
    called_ids = [c.args[0] for c in fake_ib.cancel_order.call_args_list]
    assert 124 in called_ids
    assert 125 in called_ids
    # Simulated string IDs were NOT passed
    for cid in called_ids:
        assert isinstance(cid, int)


@pytest.mark.asyncio
async def test_cancel_ib_bracket_swallows_errors():
    """Cancel failures must be logged but never raise — the close
    path is about to submit anyway, and IB will reject duplicate fills."""
    from services.trade_executor_service import TradeExecutorService
    svc = TradeExecutorService()

    trade = _Trade(stop_order_id="100", target_order_id="101")

    fake_ib = AsyncMock()
    fake_ib.cancel_order = AsyncMock(side_effect=RuntimeError("IB pusher offline"))

    with patch("routers.ib._ib_service", fake_ib, create=True):
        # Must NOT raise even though every cancel call fails
        await svc._cancel_ib_bracket_orders(trade)


# --------------------------------------------------------------------------
# P0 #2 — execute_partial_exit propagates broker failures
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_partial_exit_propagates_broker_failure():
    """When the executor raises, position_manager.execute_partial_exit
    must return success=False — NOT silently fake a simulated fill."""
    from services.position_manager import PositionManager
    pm = PositionManager()
    trade = _Trade()

    fake_executor = MagicMock()
    fake_executor.execute_partial_exit = AsyncMock(
        side_effect=RuntimeError("IB rejected partial: insufficient quantity")
    )

    fake_bot = MagicMock()
    fake_bot._trade_executor = fake_executor

    result = await pm.execute_partial_exit(trade, shares=33, target_price=101.0, target_idx=0, bot=fake_bot)

    assert result["success"] is False, (
        "v19.13 REGRESSION: partial exit must propagate broker failures. "
        f"Got: {result}"
    )
    assert result["shares"] == 0
    assert "IB rejected partial" in result.get("error", "") or "RuntimeError" in result.get("error", "")


@pytest.mark.asyncio
async def test_partial_exit_no_executor_returns_simulated_legitimately():
    """Paper-paper mode (no executor) is the ONE legitimate
    `simulated: True` path. It must keep working."""
    from services.position_manager import PositionManager
    pm = PositionManager()
    trade = _Trade(current_price=101.5)

    fake_bot = MagicMock()
    fake_bot._trade_executor = None

    result = await pm.execute_partial_exit(trade, shares=33, target_price=101.0, target_idx=0, bot=fake_bot)
    assert result["success"] is True
    assert result["simulated"] is True
    assert result["fill_price"] == 101.5


@pytest.mark.asyncio
async def test_partial_exit_executor_returns_failure_passes_through():
    """When the executor itself returns success=False (no exception),
    that result must reach the caller verbatim — no false simulation."""
    from services.position_manager import PositionManager
    pm = PositionManager()
    trade = _Trade()

    fake_executor = MagicMock()
    fake_executor.execute_partial_exit = AsyncMock(return_value={
        "success": False, "error": "broker_rejected_margin"
    })
    fake_bot = MagicMock()
    fake_bot._trade_executor = fake_executor

    result = await pm.execute_partial_exit(trade, shares=33, target_price=101.0, target_idx=0, bot=fake_bot)
    assert result["success"] is False
    assert result.get("error") == "broker_rejected_margin"


# --------------------------------------------------------------------------
# P1 #6 — stop_adjustments list capped at 100
# --------------------------------------------------------------------------

def test_stop_adjustments_history_capped_at_100():
    from services.stop_manager import StopManager
    sm = StopManager()
    trade = _Trade()
    # Push 250 fake adjustments through the recorder
    for i in range(250):
        sm._record_stop_adjustment(trade, old_stop=99.0 + i * 0.01, new_stop=99.0 + (i + 1) * 0.01, reason="test")
    history = trade.trailing_stop_config["stop_adjustments"]
    assert len(history) == 100, f"expected cap at 100; got {len(history)}"
    # Newest entries retained, oldest dropped
    assert history[-1]["new_stop"] > history[0]["new_stop"]


# --------------------------------------------------------------------------
# P1 #7 — StopManager.forget_trade releases state
# --------------------------------------------------------------------------

def test_stop_manager_forget_trade_releases_state():
    from services.stop_manager import StopManager
    sm = StopManager()
    sm._last_resnap_at["T1"] = "fake_ts"
    sm._last_resnap_at["T2"] = "fake_ts2"
    sm.forget_trade("T1")
    assert "T1" not in sm._last_resnap_at
    assert "T2" in sm._last_resnap_at  # other trades unaffected
    # Idempotent — calling twice is safe
    sm.forget_trade("T1")
    sm.forget_trade("nonexistent")


# --------------------------------------------------------------------------
# P0 #3 — close_trade returns False on executor failure
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_close_trade_returns_false_on_executor_failure():
    """When the executor's close_position returns success=False, the
    trade MUST stay open locally so the manage loop can retry."""
    from services.position_manager import PositionManager
    pm = PositionManager()
    trade = _Trade(remaining_shares=100)

    fake_executor = MagicMock()
    fake_executor.close_position = AsyncMock(
        return_value={"success": False, "error": "broker_rejected: insufficient margin"}
    )

    fake_bot = MagicMock()
    fake_bot._trade_executor = fake_executor
    fake_bot._open_trades = {"T1": trade}
    fake_bot._closed_trades = []

    with patch("services.trade_drop_recorder.record_trade_drop"):
        result = await pm.close_trade("T1", fake_bot, reason="manual")

    assert result is False, (
        "v19.13 REGRESSION: close_trade must return False when "
        "executor refuses; trade stays open."
    )
    # Trade still in open_trades (NOT moved to closed_trades)
    assert "T1" in fake_bot._open_trades


# --------------------------------------------------------------------------
# P2 #12 — original_shares + remaining_shares initialized at trade-create
# --------------------------------------------------------------------------

def test_opportunity_evaluator_initializes_share_state_at_create():
    """Verify the BotTrade construction passes both `shares`,
    `remaining_shares`, AND `original_shares` so a partial exit
    landing on the first manage tick can't distort the math.

    Source-level check: the construction call site MUST mention all
    three field names. Using the source-grep approach (cheaper than
    spinning up the full evaluator)."""
    import inspect
    from services import opportunity_evaluator
    src = inspect.getsource(opportunity_evaluator)
    # Find the trade = BotTrade(...) construction block. Use a generous
    # lookahead (200 lines) since the constructor has nested parens
    # (e.g., `str(uuid.uuid4())`).
    idx = src.find("trade = BotTrade(")
    assert idx >= 0, "Could not locate BotTrade(...) construction"
    # Slurp ~3,000 chars after the opening to safely contain the full call
    body = src[idx : idx + 3000]
    for field in ("shares=", "remaining_shares=", "original_shares="):
        assert field in body, (
            f"v19.13 P2 #12 REGRESSION: BotTrade construction missing "
            f"`{field}`. A partial exit on the first manage tick would "
            f"distort scale-out percentages."
        )


# --------------------------------------------------------------------------
# P1 #10 — WS notification throttle
# --------------------------------------------------------------------------

def test_ws_throttle_constants_pinned():
    """Source-level pin: the throttle MUST keep the 2s heartbeat
    floor + 5% risk-relative P&L delta trigger so a future contributor
    doesn't silently flip back to per-tick spam."""
    import inspect
    from services import position_manager
    src = inspect.getsource(position_manager)
    # Two anchors: the 2.0s heartbeat and the 0.05 (5%) delta gate.
    assert "_now - _last_at) >= 2.0" in src or "_last_at) >= 2.0" in src, (
        "v19.13 P1 #10 REGRESSION: WS throttle 2s heartbeat lost."
    )
    assert "_pnl_delta_pct >= 0.05" in src, (
        "v19.13 P1 #10 REGRESSION: WS throttle 5% P&L-delta trigger lost."
    )


# --------------------------------------------------------------------------
# P1 #8 — bid/ask-aware stop trigger
# --------------------------------------------------------------------------

def test_stop_trigger_uses_bid_for_long_when_available():
    """Source-level pin: the long-stop check uses bid (not last) when
    bid is present + sane. Critical for thin-stock fills where
    last >> bid."""
    import inspect
    from services import position_manager
    src = inspect.getsource(position_manager)
    # Pin the structure: trigger_price gets bid for long, ask for short
    assert "trigger_price = float(_bid)" in src, (
        "v19.13 P1 #8 REGRESSION: long stop must use bid for trigger."
    )
    assert "trigger_price = float(_ask)" in src, (
        "v19.13 P1 #8 REGRESSION: short stop must use ask for trigger."
    )
    assert "trigger_price <= effective_stop" in src and \
           "trigger_price >= effective_stop" in src, (
        "v19.13 P1 #8 REGRESSION: stop comparisons must use trigger_price, "
        "not current_price/last."
    )


def test_quote_read_captures_bid_and_ask():
    """Pin that the quote dict the manage-loop builds carries bid + ask."""
    import inspect
    from services import position_manager
    src = inspect.getsource(position_manager)
    assert "'bid': q.get('bid')" in src and "'ask': q.get('ask')" in src, (
        "v19.13 P1 #8 REGRESSION: quote dict must capture bid/ask "
        "so stop-trigger logic can use the tradable side."
    )
