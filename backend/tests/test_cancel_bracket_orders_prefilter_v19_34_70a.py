"""v19.34.70 PATCH A — Pre-filter stale orderIds out of bracket-cancel
wait path.

Bug fixed (2026-05-21 incident): `_cancel_ib_bracket_orders` issued
cancels + waited 4s for terminal confirmation on every orderId held in
the bot's `trade.stop_order_id` / `trade.target_order_id(s)` fields,
regardless of whether IB still knew about them. When pusher silently
failed to report cancel results (10147 not_found), the v19.34.65b
poll-count guard correctly stale-dropped the cancel-queue entries —
but `_cancel_ib_bracket_orders` (which uses the in-process ib_direct
path, not the pusher queue) had no signal that IB had cleaned the
orders up. During the flap window where IB was bouncing the orders
between PendingCancel ↔ Submitted, `wait_for_orders_terminal` saw them
in cache as non-terminal → timeout → close aborted with
`bracket_cancel_timeout_race_risk`. This blocked every one of 21
manual EOD closes on 2026-05-21.

The patch: before issuing any cancel, snapshot IB's live `trades()`
cache. OrderIds NOT in cache are already-terminal-safe (IB has moved
on); they get recorded in `unknown` (existing safe-bucket contract)
and skipped from the cancel/wait path. OrderIds still in cache get
the normal cancel + 4s terminal wait — full OCA-race protection
preserved.

These tests use a fake `ib_direct` to drive the new pre-filter path
deterministically. They lock in:
  - Stale-only IDs → all land in `unknown`, no cancel issued, no wait.
  - Live-only IDs → behave exactly as pre-v19.34.70 (cancel + wait).
  - Mixed → stale go to `unknown`, live proceed to cancel + wait.
  - ib_direct unavailable → falls back to legacy path (no regression).
"""
import asyncio
import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock


# --- Build a fake `ib_direct` that exposes only what Patch A touches ----
class _FakeOrder:
    def __init__(self, orderId):
        self.orderId = orderId


class _FakeTrade:
    def __init__(self, orderId, status="Submitted"):
        self.order = _FakeOrder(orderId)
        # orderStatus is consumed elsewhere; not needed for Patch A pre-filter
        self.orderStatus = types.SimpleNamespace(status=status, whyHeld="")


class _FakeIB:
    def __init__(self, live_order_ids):
        self._live = [_FakeTrade(oid) for oid in live_order_ids]

    def trades(self):
        return self._live


class _FakeIBDirect:
    """Minimal stand-in for the singleton ib_direct service. We override
    `wait_for_orders_terminal` to capture what `ordered` looks like
    AFTER the patch's pre-filter — that's the contract we test."""

    def __init__(self, live_order_ids, available=True):
        self._available = available
        self._ib = _FakeIB(live_order_ids)
        self.waited_for_ids = None  # ← captured by the spy below

    async def ensure_connected(self):
        return self._available

    async def wait_for_orders_terminal(self, order_ids, timeout_s=4.0, poll_iv_s=0.1):
        # Capture what made it past the pre-filter
        self.waited_for_ids = list(order_ids)
        # Pretend everything left reached `cancelled` terminal — the
        # pre-filter is what we're testing here, not the wait itself.
        return {
            "cancelled": list(order_ids),
            "filled": [], "other_terminal": [],
            "timeout": [], "unknown": [],
        }


class _FakeIBService:
    """Captures cancel_order calls so we can assert cancellations only
    fire for live orderIds, not stale ones."""

    def __init__(self):
        self.cancelled_oids = []

    async def cancel_order(self, oid):
        self.cancelled_oids.append(int(oid))
        return True


class _FakeBotTrade:
    def __init__(self, symbol="CF", stop_oid=None, target_oid=None,
                 target_oids=None):
        self.symbol = symbol
        self.stop_order_id = stop_oid
        self.target_order_id = target_oid
        self.target_order_ids = target_oids or []


# --- Test harness: patch the singletons that _cancel_ib_bracket_orders pulls in ---
@pytest.fixture
def patched_executor(monkeypatch):
    """Build the executor and wire fake ib_direct + _ib_service into it.

    Returns (executor, fake_ibd, fake_ibs) so each test can assert
    against the spies.
    """
    from services.trade_executor_service import TradeExecutorService

    def _make(live_order_ids, ib_direct_available=True):
        fake_ibs = _FakeIBService()
        fake_ibd = _FakeIBDirect(live_order_ids, available=ib_direct_available)

        # Patch ib_direct singleton accessor BEFORE building the executor.
        import services.ib_direct_service as _ibd_mod
        monkeypatch.setattr(_ibd_mod, "get_ib_direct_service", lambda: fake_ibd)

        # Patch _ib_service used inside the per-oid cancel loop.
        import routers.ib as _ib_router
        monkeypatch.setattr(_ib_router, "_ib_service", fake_ibs)

        executor = TradeExecutorService.__new__(TradeExecutorService)
        return executor, fake_ibd, fake_ibs

    return _make


# -----------------------------------------------------------------
# 1. Stale-only IDs → unknown, no cancel issued, no wait
# -----------------------------------------------------------------
def test_all_stale_ids_skip_cancel_and_wait(patched_executor):
    """The exact 2026-05-21 scenario: bot tracks 4729/4730 but IB cache
    has neither. Pre-fix: cancel both, wait 4s, both land in timeout →
    close aborts. Post-fix: both land in `unknown`, no cancel issued."""
    executor, fake_ibd, fake_ibs = patched_executor(live_order_ids=[])
    trade = _FakeBotTrade(symbol="CF", stop_oid=4729, target_oid=4730)

    result = asyncio.run(executor._cancel_ib_bracket_orders(trade))

    assert sorted(result["unknown"]) == [4729, 4730]
    assert result["timeout"] == []
    assert result["filled"] == []
    assert result["issued"] == [], "no cancel should have been issued for stale ids"
    assert fake_ibs.cancelled_oids == [], "ib_service.cancel_order must NOT be called"
    assert fake_ibd.waited_for_ids is None, "wait_for_orders_terminal must NOT be called"


# -----------------------------------------------------------------
# 2. Live-only IDs → behave exactly as pre-v19.34.70
# -----------------------------------------------------------------
def test_live_ids_get_cancel_and_wait(patched_executor):
    """When IB still has the orders in its cache, behavior is unchanged:
    cancels are issued, wait_for_orders_terminal is called with the
    live ids, no premature unknown bucket population."""
    executor, fake_ibd, fake_ibs = patched_executor(live_order_ids=[100, 200])
    trade = _FakeBotTrade(stop_oid=100, target_oid=200)

    result = asyncio.run(executor._cancel_ib_bracket_orders(trade))

    assert sorted(fake_ibs.cancelled_oids) == [100, 200]
    assert sorted(fake_ibd.waited_for_ids) == [100, 200]
    # Our fake wait returns everything as cancelled
    assert sorted(result["cancelled"]) == [100, 200]
    assert result["unknown"] == []
    assert result["timeout"] == []


# -----------------------------------------------------------------
# 3. Mixed: stale ids → unknown, live ids → cancel + wait
# -----------------------------------------------------------------
def test_mixed_stale_and_live_partition_correctly(patched_executor):
    """Realistic recovery scenario: stop_order_id is stale (gone from
    IB) but target_order_id is still live. We should skip the stale
    one and only cancel + wait on the live one."""
    executor, fake_ibd, fake_ibs = patched_executor(live_order_ids=[200])
    trade = _FakeBotTrade(stop_oid=100, target_oid=200)  # 100 stale, 200 live

    result = asyncio.run(executor._cancel_ib_bracket_orders(trade))

    assert result["unknown"] == [100]
    assert fake_ibs.cancelled_oids == [200], "only the live id should have a cancel issued"
    assert fake_ibd.waited_for_ids == [200], "only the live id should be in the wait"
    assert result["cancelled"] == [200]


# -----------------------------------------------------------------
# 4. ib_direct unavailable → falls back to legacy path
# -----------------------------------------------------------------
def test_ib_direct_unavailable_falls_back_to_legacy(patched_executor):
    """If ib_direct's ensure_connected returns False, the pre-filter
    must silently fall through to the legacy cancel-everything path —
    no regression from pre-v19.34.70 behavior. (The `wait_for_orders_terminal`
    block at the bottom of the method ALSO checks ensure_connected and
    skips itself if unavailable, so the cancel still fires but no wait
    happens — see lines 2167-2199 of the source.)"""
    executor, fake_ibd, fake_ibs = patched_executor(
        live_order_ids=[],   # irrelevant — pre-filter is bypassed
        ib_direct_available=False,
    )
    trade = _FakeBotTrade(stop_oid=4729, target_oid=4730)

    result = asyncio.run(executor._cancel_ib_bracket_orders(trade))

    # Pre-filter was bypassed (ib_direct unavailable), so both cancels fire
    assert sorted(fake_ibs.cancelled_oids) == [4729, 4730]
    # Wait was also bypassed (same ensure_connected check), so no
    # cancelled/timeout classification — but result.unknown stays empty
    # because pre-filter didn't run.
    assert result["unknown"] == []


# -----------------------------------------------------------------
# 5. Sim-mode / non-int orderIds still skipped (pre-existing behavior)
# -----------------------------------------------------------------
def test_sim_order_ids_are_filtered_before_pre_filter(patched_executor):
    """SIM-* string IDs from paper mode should still be silently
    dropped — this happened pre-v19.34.70 in the candidate-collection
    loop and the patch must not regress it."""
    executor, fake_ibd, fake_ibs = patched_executor(live_order_ids=[100])
    trade = _FakeBotTrade()
    trade.stop_order_id = "SIM-STOP-abc123"      # sim → dropped early
    trade.target_order_id = 100                  # live → processed
    trade.target_order_ids = ["SIM-TGT-xyz"]     # sim → dropped early

    result = asyncio.run(executor._cancel_ib_bracket_orders(trade))

    assert fake_ibs.cancelled_oids == [100]
    assert fake_ibd.waited_for_ids == [100]
    # SIM ids never reach the unknown bucket either — they're filtered
    # in the int-cast loop before pre-filter sees them.
    assert result["unknown"] == []


# -----------------------------------------------------------------
# 6. Empty trade (no order ids at all) → no-op (unchanged)
# -----------------------------------------------------------------
def test_no_order_ids_returns_immediately(patched_executor):
    """Defensive: a freshly-spawned trade with no brackets yet must
    short-circuit cleanly with no IB calls."""
    executor, fake_ibd, fake_ibs = patched_executor(live_order_ids=[100])
    trade = _FakeBotTrade()  # all None

    result = asyncio.run(executor._cancel_ib_bracket_orders(trade))

    assert result == {
        "issued": [], "cancelled": [], "filled": [],
        "other_terminal": [], "timeout": [], "unknown": [],
        "ib_direct_called": False,
    }
    assert fake_ibs.cancelled_oids == []
    assert fake_ibd.waited_for_ids is None
