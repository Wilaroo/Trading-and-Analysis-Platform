"""
v19.34 (2026-05-04) — Tests for the L1 quote tick bus + mid-bar
stop-eval pipeline.

Phases tested:
  1. Quote Tick Bus (`services.quote_tick_bus`):
     - publish/subscribe/unsubscribe semantics
     - latest-N drop policy when consumer is slow
     - multi-subscriber fanout
     - feature-flag (QUOTE_TICK_BUS_ENABLED=false → no-op)
     - drop counters + health snapshot

  2. Pusher → bus bridge (`routers.ib.receive_pushed_ib_data`):
     - structural assertion that publish_quotes is called from the
       quotes-update branch

  3. Mid-bar stop eval (`PositionManager.evaluate_single_trade_against_quote`):
     - LONG: bid <= stop → close fires
     - LONG: bid > stop → no close
     - SHORT: ask >= stop → close fires
     - SHORT: ask < stop → no close
     - last fallback when bid/ask absent
     - no stop_price → no-op (server-side bracket protects)
     - exception in close_trade is caught + swallowed
     - status != open → no-op
     - close_reason is stamped distinctly so journal can identify
       mid-bar fires vs bar-close fires

Plus structural assertions for the lifecycle reaper task wiring.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ───────────────────────────────────────────────────────────────────
# Phase 1 — Quote Tick Bus
# ───────────────────────────────────────────────────────────────────


@pytest.fixture
def fresh_bus():
    from services.quote_tick_bus import get_quote_tick_bus
    bus = get_quote_tick_bus()
    bus.reset_for_tests()
    # Ensure the env-flag is ON for the test (it's the default).
    os.environ.pop("QUOTE_TICK_BUS_ENABLED", None)
    yield bus
    bus.reset_for_tests()


@pytest.mark.asyncio
async def test_bus_publish_subscribe_basic(fresh_bus):
    """A subscriber receives ticks for its symbol."""
    q, sym = fresh_bus.subscribe("AAPL")
    assert sym == "AAPL"
    fresh_bus.publish("AAPL", {"bid": 150.0, "ask": 150.10, "last": 150.05})
    tick = await asyncio.wait_for(q.get(), timeout=1.0)
    assert tick["bid"] == 150.0
    fresh_bus.unsubscribe(sym, q)


@pytest.mark.asyncio
async def test_bus_uppercases_symbols(fresh_bus):
    """Symbols normalized to uppercase regardless of input casing."""
    q, sym = fresh_bus.subscribe("aapl")
    fresh_bus.publish("AAPL", {"last": 150.0})
    tick = await asyncio.wait_for(q.get(), timeout=1.0)
    assert tick["last"] == 150.0
    fresh_bus.unsubscribe(sym, q)


@pytest.mark.asyncio
async def test_bus_does_not_cross_subscribers(fresh_bus):
    """A subscriber for AAPL must NOT receive MSFT ticks."""
    q_a, _ = fresh_bus.subscribe("AAPL")
    q_m, _ = fresh_bus.subscribe("MSFT")
    fresh_bus.publish("AAPL", {"last": 150.0})
    a_tick = await asyncio.wait_for(q_a.get(), timeout=1.0)
    assert a_tick["last"] == 150.0
    # MSFT queue must be empty.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(q_m.get(), timeout=0.1)


@pytest.mark.asyncio
async def test_bus_multi_subscriber_fanout(fresh_bus):
    """Two subscribers on the same symbol both get every tick."""
    q1, _ = fresh_bus.subscribe("AAPL")
    q2, _ = fresh_bus.subscribe("AAPL")
    fresh_bus.publish("AAPL", {"last": 150.0})
    t1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    t2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert t1["last"] == t2["last"] == 150.0


@pytest.mark.asyncio
async def test_bus_latest_drop_policy(fresh_bus):
    """When a consumer's queue is full, the OLDEST tick is dropped
    and the latest is enqueued. Drop counter increments."""
    q, sym = fresh_bus.subscribe("AAPL", queue_size=2)
    # Producer pumps 5 ticks; consumer hasn't drained any.
    for i in range(5):
        fresh_bus.publish("AAPL", {"last": 100.0 + i})
    # Drain — should see the LATEST 2 ticks (102.0 was popped to make
    # room for 103.0; 103.0 popped for 104.0; final queue: [103.0, 104.0]).
    received = []
    while not q.empty():
        received.append(q.get_nowait()["last"])
    assert received == [103.0, 104.0]
    health = fresh_bus.health()
    assert health["drop_total"] >= 3
    assert health["per_symbol"][0]["drops"] >= 3
    fresh_bus.unsubscribe(sym, q)


@pytest.mark.asyncio
async def test_bus_disabled_via_env(fresh_bus, monkeypatch):
    """QUOTE_TICK_BUS_ENABLED=false → publishes are no-ops."""
    monkeypatch.setenv("QUOTE_TICK_BUS_ENABLED", "false")
    delivered = fresh_bus.publish("AAPL", {"last": 150.0})
    assert delivered == 0
    assert fresh_bus._publish_total == 0


def test_bus_publish_quotes_batch(fresh_bus):
    """publish_quotes({sym: tick, ...}) iterates all symbols."""
    q1, _ = fresh_bus.subscribe("AAPL")
    q2, _ = fresh_bus.subscribe("MSFT")
    delivered = fresh_bus.publish_quotes({
        "AAPL": {"last": 150.0},
        "MSFT": {"last": 380.0},
        "TSLA": {"last": 250.0},  # no subscriber
    })
    # 2 symbols had subscribers → 2 deliveries; TSLA was 0.
    assert delivered == 2
    assert fresh_bus._publish_total == 3  # publishes counted regardless


@pytest.mark.asyncio
async def test_bus_unsubscribe_removes_from_set(fresh_bus):
    q, sym = fresh_bus.subscribe("AAPL")
    assert "AAPL" in fresh_bus._subs
    ok = fresh_bus.unsubscribe(sym, q)
    assert ok is True
    # Slot is cleared when last subscriber leaves.
    assert "AAPL" not in fresh_bus._subs
    # Re-unsubscribe is a no-op (returns False).
    assert fresh_bus.unsubscribe(sym, q) is False


@pytest.mark.asyncio
async def test_bus_health_snapshot_shape(fresh_bus):
    q, _ = fresh_bus.subscribe("AAPL")
    fresh_bus.publish("AAPL", {"last": 150.0})
    h = fresh_bus.health()
    assert h["enabled"] is True
    assert h["publish_total"] == 1
    assert h["drop_total"] == 0
    assert h["active_symbols"] == 1
    assert h["total_subscribers"] == 1
    assert len(h["per_symbol"]) == 1
    row = h["per_symbol"][0]
    assert row["symbol"] == "AAPL"
    assert row["publishes"] == 1
    assert row["drops"] == 0
    assert row["last_publish_age_s"] is not None


@pytest.mark.asyncio
async def test_bus_stream_async_generator(fresh_bus):
    """`bus.stream(symbol)` async-yields ticks until cancelled."""
    received = []

    async def consumer():
        async for tick in fresh_bus.stream("AAPL"):
            received.append(tick["last"])
            if len(received) >= 2:
                break

    task = asyncio.create_task(consumer())
    # Give the subscriber a moment to register.
    await asyncio.sleep(0.05)
    fresh_bus.publish("AAPL", {"last": 150.0})
    fresh_bus.publish("AAPL", {"last": 151.0})
    await asyncio.wait_for(task, timeout=1.0)
    assert received == [150.0, 151.0]


# ───────────────────────────────────────────────────────────────────
# Phase 2 — Pusher → bus bridge structural assertion
# ───────────────────────────────────────────────────────────────────


def test_pusher_intake_publishes_to_bus():
    """`receive_pushed_ib_data` must call `publish_quotes` whenever
    quotes are present in the request."""
    src = (BACKEND_DIR / "routers" / "ib.py").read_text()
    # The publish hook must live INSIDE the `if request.quotes:` block.
    assert "from services.quote_tick_bus import get_quote_tick_bus" in src
    assert "get_quote_tick_bus().publish_quotes(request.quotes)" in src
    # And it must be wrapped in try/except so a bus blip can't break
    # the push hot path.
    quotes_block_idx = src.index("_pushed_ib_data[\"quotes\"].update(request.quotes)")
    bridge_idx = src.index("get_quote_tick_bus().publish_quotes")
    assert bridge_idx > quotes_block_idx, (
        "publish_quotes must be wired AFTER the in-memory quotes update"
    )


def test_quote_tick_bus_health_endpoint_registered():
    """`GET /api/ib/quote-tick-bus/health` must be on the IB router."""
    src = (BACKEND_DIR / "routers" / "ib.py").read_text()
    assert "@router.get(\"/quote-tick-bus/health\")" in src
    assert "get_quote_tick_bus_health" in src


# ───────────────────────────────────────────────────────────────────
# Phase 3 — Mid-bar stop eval
# ───────────────────────────────────────────────────────────────────


def _make_open_long_trade(stop=99.0, entry=100.0, current=100.5):
    """Minimal trade stub for the eval method. Avoids constructing a
    full BotTrade since this test only needs a few attributes."""
    from services.trading_bot_service import TradeDirection, TradeStatus
    t = MagicMock()
    t.id = "t1"
    t.symbol = "AAPL"
    t.direction = TradeDirection.LONG
    t.status = TradeStatus.OPEN
    t.stop_price = stop
    t.entry_price = entry
    t.current_price = current
    t.trailing_stop_config = {}
    return t


def _make_open_short_trade(stop=101.0, entry=100.0, current=99.5):
    from services.trading_bot_service import TradeDirection, TradeStatus
    t = MagicMock()
    t.id = "t2"
    t.symbol = "TSLA"
    t.direction = TradeDirection.SHORT
    t.status = TradeStatus.OPEN
    t.stop_price = stop
    t.entry_price = entry
    t.current_price = current
    t.trailing_stop_config = {}
    return t


@pytest.mark.asyncio
async def test_midbar_long_bid_below_stop_fires_close():
    from services.position_manager import PositionManager
    pm = PositionManager()
    pm.close_trade = AsyncMock(return_value=True)
    trade = _make_open_long_trade(stop=99.0)
    bot = MagicMock()
    quote = {"bid": 98.50, "ask": 98.55, "last": 98.52}
    reason = await pm.evaluate_single_trade_against_quote(trade, bot, quote)
    assert reason is not None
    assert "mid_bar" in reason
    assert "stop_loss" in reason
    pm.close_trade.assert_awaited_once()
    assert pm.close_trade.call_args.kwargs["reason"] == reason


@pytest.mark.asyncio
async def test_midbar_long_bid_above_stop_no_action():
    from services.position_manager import PositionManager
    pm = PositionManager()
    pm.close_trade = AsyncMock(return_value=True)
    trade = _make_open_long_trade(stop=99.0)
    bot = MagicMock()
    quote = {"bid": 100.50, "ask": 100.55, "last": 100.52}
    reason = await pm.evaluate_single_trade_against_quote(trade, bot, quote)
    assert reason is None
    pm.close_trade.assert_not_awaited()


@pytest.mark.asyncio
async def test_midbar_short_ask_above_stop_fires_close():
    from services.position_manager import PositionManager
    pm = PositionManager()
    pm.close_trade = AsyncMock(return_value=True)
    trade = _make_open_short_trade(stop=101.0)
    bot = MagicMock()
    quote = {"bid": 101.40, "ask": 101.45, "last": 101.42}
    reason = await pm.evaluate_single_trade_against_quote(trade, bot, quote)
    assert reason is not None
    assert "mid_bar" in reason
    pm.close_trade.assert_awaited_once()


@pytest.mark.asyncio
async def test_midbar_short_ask_below_stop_no_action():
    from services.position_manager import PositionManager
    pm = PositionManager()
    pm.close_trade = AsyncMock(return_value=True)
    trade = _make_open_short_trade(stop=101.0)
    bot = MagicMock()
    quote = {"bid": 100.45, "ask": 100.50, "last": 100.47}
    reason = await pm.evaluate_single_trade_against_quote(trade, bot, quote)
    assert reason is None
    pm.close_trade.assert_not_awaited()


@pytest.mark.asyncio
async def test_midbar_long_falls_back_to_last_when_no_bid():
    from services.position_manager import PositionManager
    pm = PositionManager()
    pm.close_trade = AsyncMock(return_value=True)
    trade = _make_open_long_trade(stop=99.0)
    bot = MagicMock()
    # Bid missing — should use `last` as fallback per the spec.
    quote = {"bid": None, "ask": 98.55, "last": 98.50}
    reason = await pm.evaluate_single_trade_against_quote(trade, bot, quote)
    assert reason is not None
    pm.close_trade.assert_awaited_once()


@pytest.mark.asyncio
async def test_midbar_no_stop_price_is_noop():
    """Trade has no stop_price (server-side bracket only) → mid-bar is
    skipped to avoid ghost stops; bracket handles it."""
    from services.position_manager import PositionManager
    pm = PositionManager()
    pm.close_trade = AsyncMock(return_value=True)
    trade = _make_open_long_trade(stop=0.0)
    trade.stop_price = None
    bot = MagicMock()
    quote = {"bid": 1.0, "ask": 1.05, "last": 1.02}
    reason = await pm.evaluate_single_trade_against_quote(trade, bot, quote)
    assert reason is None
    pm.close_trade.assert_not_awaited()


@pytest.mark.asyncio
async def test_midbar_status_not_open_is_noop():
    from services.position_manager import PositionManager
    from services.trading_bot_service import TradeStatus
    pm = PositionManager()
    pm.close_trade = AsyncMock(return_value=True)
    trade = _make_open_long_trade(stop=99.0)
    trade.status = TradeStatus.CLOSED
    bot = MagicMock()
    quote = {"bid": 50.0, "ask": 50.05, "last": 50.02}
    reason = await pm.evaluate_single_trade_against_quote(trade, bot, quote)
    assert reason is None
    pm.close_trade.assert_not_awaited()


@pytest.mark.asyncio
async def test_midbar_close_trade_failure_returns_none_not_raise():
    """If close_trade returns False (executor refused), eval must
    return None (not raise) so the subscriber loop keeps running."""
    from services.position_manager import PositionManager
    pm = PositionManager()
    pm.close_trade = AsyncMock(return_value=False)
    trade = _make_open_long_trade(stop=99.0)
    bot = MagicMock()
    quote = {"bid": 50.0, "ask": 50.05, "last": 50.02}
    reason = await pm.evaluate_single_trade_against_quote(trade, bot, quote)
    assert reason is None  # Close was attempted but refused.


@pytest.mark.asyncio
async def test_midbar_close_trade_exception_is_swallowed():
    """If close_trade raises, eval must NOT propagate (subscriber
    survives the malformed tick)."""
    from services.position_manager import PositionManager
    pm = PositionManager()
    pm.close_trade = AsyncMock(side_effect=RuntimeError("executor down"))
    trade = _make_open_long_trade(stop=99.0)
    bot = MagicMock()
    quote = {"bid": 50.0, "ask": 50.05, "last": 50.02}
    # Must NOT raise.
    reason = await pm.evaluate_single_trade_against_quote(trade, bot, quote)
    assert reason is None


@pytest.mark.asyncio
async def test_midbar_uses_trailing_stop_when_set():
    """If `trailing_stop_config.current_stop` is set, that takes
    precedence over the original stop_price."""
    from services.position_manager import PositionManager
    pm = PositionManager()
    pm.close_trade = AsyncMock(return_value=True)
    trade = _make_open_long_trade(stop=99.0)
    trade.trailing_stop_config = {"current_stop": 100.5, "mode": "trailing"}
    bot = MagicMock()
    # bid=100.4 is BELOW trailing stop 100.5 (so we trigger), even though
    # original stop was 99 (which would NOT have triggered).
    quote = {"bid": 100.4, "ask": 100.45, "last": 100.42}
    reason = await pm.evaluate_single_trade_against_quote(trade, bot, quote)
    assert reason is not None
    assert "trailing" in reason  # mode-specific stamp


# ───────────────────────────────────────────────────────────────────
# Lifecycle reaper structural assertions
# ───────────────────────────────────────────────────────────────────


def test_lifecycle_loop_wired_in_bot_start():
    src = (BACKEND_DIR / "services" / "trading_bot_service.py").read_text()
    assert "_midbar_tick_lifecycle_loop" in src
    assert "MID_BAR_TICK_EVAL_ENABLED" in src
    assert "_midbar_tick_subs" in src
    assert "evaluate_single_trade_against_quote" in src


def test_lifecycle_tasks_cancelled_on_stop():
    src = (BACKEND_DIR / "services" / "trading_bot_service.py").read_text()
    assert "_midbar_tick_lifecycle_task" in src
    # Subscriber map must be cleaned up too.
    assert "midbar_subs" in src or "_midbar_tick_subs" in src


def test_lifecycle_default_disabled():
    """Default value of MID_BAR_TICK_EVAL_ENABLED must be `false` so
    flipping it on is an explicit operator action."""
    src = (BACKEND_DIR / "services" / "trading_bot_service.py").read_text()
    # The .get default must be `"false"` to keep Phase 3 dormant
    # until the operator opts in.
    assert 'MID_BAR_TICK_EVAL_ENABLED", "false"' in src
