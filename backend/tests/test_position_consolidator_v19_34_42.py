"""
v19.34.42 — Position Consolidator + Idempotent Excess-Slice Tests
====================================================================

Covers:
 1. Dry-run reports correct fragment diff for BMNR-style 19-slice pattern.
 2. apply_consolidation requires `confirm=True`.
 3. apply_consolidation collapses N siblings → 1 canonical with summed shares.
 4. Canonical resolution prefers non-reconciled trade.
 5. _spawn_excess_slice grows existing reconciled-excess slice instead of
    creating a new one (prevents BMNR fragmentation regression).
 6. Singleton positions (N=1) are NOT touched.
 7. Auto-consolidate safety rail: skips large fragmentation when
    kill-switch OFF and fragment count > 2.
"""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# Make backend importable.
sys.path.insert(0, "/app/backend")

from services.position_consolidator import PositionConsolidator  # noqa: E402
from services.position_reconciler import PositionReconciler  # noqa: E402


# ─────────────────────────── helpers ────────────────────────────

class _DummyDirection:
    def __init__(self, val: str):
        self.value = val

    def __eq__(self, other):
        if isinstance(other, _DummyDirection):
            return self.value == other.value
        return False


def _mk_trade(
    *, id, symbol, direction="long", remaining_shares=100,
    entry_time="2026-05-08T10:00:00+00:00", entered_by="squeeze",
    setup_type="squeeze", stop_price=21.36, target=25.59, fill_price=22.45,
):
    t = SimpleNamespace()
    t.id = id
    t.symbol = symbol
    t.direction = _DummyDirection(direction)
    t.remaining_shares = remaining_shares
    t.shares = remaining_shares
    t.original_shares = remaining_shares
    t.entry_time = entry_time
    t.executed_at = entry_time
    t.created_at = entry_time
    t.entered_by = entered_by
    t.setup_type = setup_type
    t.stop_price = stop_price
    t.target_prices = [target]
    t.fill_price = fill_price
    t.entry_price = fill_price
    t.notes = ""
    t.unrealized_pnl = 0
    t.realized_pnl = 0
    t.stop_order_id = None
    t.target_order_id = None
    t.target_order_ids = []
    t.oca_group = None
    t.status = SimpleNamespace(value="open")
    t.risk_amount = 0
    return t


def _mk_bot_with_trades(trades):
    bot = SimpleNamespace()
    bot._open_trades = {t.id: t for t in trades}
    bot._closed_trades = []
    bot._db = MagicMock()
    bot._db.__getitem__.return_value = MagicMock()
    # Persist is sync; consolidator handles both sync and coroutine.
    bot._save_trade = MagicMock(return_value=None)
    bot._persist_trade = MagicMock(return_value=None)
    bot._stop_manager = MagicMock()
    # Executor with attach_oca_stop_target returning success.
    executor = MagicMock()
    executor._cancel_ib_bracket_orders = AsyncMock(return_value=None)
    executor.attach_oca_stop_target = AsyncMock(
        return_value={"success": True, "stop_order_id": 999, "target_order_id": 888, "oca_group": "OCA-TEST"}
    )
    bot._trade_executor = executor
    return bot


# ─────────────────────────── tests ────────────────────────────

@pytest.mark.asyncio
async def test_dry_run_detects_bmnr_style_fragmentation():
    trades = [
        _mk_trade(id="orig", symbol="BMNR", remaining_shares=1352,
                  entered_by="squeeze", setup_type="squeeze",
                  fill_price=22.57, stop_price=21.36, target=25.59),
        _mk_trade(id="frag1", symbol="BMNR", remaining_shares=802,
                  entered_by="reconciled_excess_v19_34_15b",
                  setup_type="reconciled_excess_slice",
                  fill_price=22.48, stop_price=22.26, target=22.70),
        _mk_trade(id="frag2", symbol="BMNR", remaining_shares=810,
                  entered_by="reconciled_excess_v19_34_15b",
                  setup_type="reconciled_excess_slice",
                  fill_price=22.45, stop_price=22.23, target=22.67),
    ]
    bot = _mk_bot_with_trades(trades)
    consolidator = PositionConsolidator()
    diff = await consolidator.dry_run_consolidation(bot)
    assert diff["success"] is True
    assert diff["fragmented_groups"] == 1
    g = diff["groups"][0]
    assert g["symbol"] == "BMNR"
    assert g["fragment_count"] == 3
    assert g["current_total_shares"] == 1352 + 802 + 810
    # Canonical must be the non-reconciled "orig" trade.
    assert g["proposed_canonical"]["trade_id"] == "orig"
    assert g["proposed_stop"] == 21.36  # uses canonical's original SL
    assert g["proposed_target"] == 25.59


@pytest.mark.asyncio
async def test_apply_requires_confirm():
    bot = _mk_bot_with_trades([
        _mk_trade(id="a", symbol="LIN", remaining_shares=50),
        _mk_trade(id="b", symbol="LIN", remaining_shares=19,
                  entered_by="reconciled_excess_v19_34_15b",
                  setup_type="reconciled_excess_slice"),
    ])
    consolidator = PositionConsolidator()
    out = await consolidator.apply_consolidation(bot, confirm=False)
    assert out["success"] is False
    assert "confirm" in out["error"].lower()
    # No mutation: both trades still open.
    assert "a" in bot._open_trades
    assert "b" in bot._open_trades


@pytest.mark.asyncio
async def test_apply_collapses_siblings_into_canonical():
    trades = [
        _mk_trade(id="canon", symbol="DDOG", direction="short",
                  remaining_shares=200,
                  entered_by="momentum", setup_type="momentum",
                  fill_price=190.00, stop_price=192.00, target=185.00),
        _mk_trade(id="sib1", symbol="DDOG", direction="short",
                  remaining_shares=100,
                  entered_by="reconciled_excess_v19_34_15b",
                  setup_type="reconciled_excess_slice",
                  fill_price=190.50, stop_price=192.40, target=189.50),
        _mk_trade(id="sib2", symbol="DDOG", direction="short",
                  remaining_shares=78,
                  entered_by="reconciled_excess_v19_34_15b",
                  setup_type="reconciled_excess_slice",
                  fill_price=190.60, stop_price=192.50, target=189.40),
    ]
    bot = _mk_bot_with_trades(trades)
    # Patch TradeStatus import inside consolidator
    import services.trading_bot_service as tbs_mod
    fake_status = SimpleNamespace(CLOSED=SimpleNamespace(value="closed"),
                                  OPEN=SimpleNamespace(value="open"))
    tbs_mod.TradeStatus = fake_status

    consolidator = PositionConsolidator()
    result = await consolidator.apply_consolidation(
        bot, symbols=["DDOG"], confirm=True,
    )
    assert result["success"] is True
    assert len(result["consolidated"]) == 1
    c = result["consolidated"][0]
    assert c["canonical_id"] == "canon"
    assert sorted(c["siblings_closed"]) == ["sib1", "sib2"]
    assert c["total_shares"] == 200 + 100 + 78
    # In-memory: only canonical remains.
    assert "canon" in bot._open_trades
    assert "sib1" not in bot._open_trades
    assert "sib2" not in bot._open_trades
    # Canonical grew.
    canonical = bot._open_trades["canon"]
    assert canonical.remaining_shares == 378
    # Each sibling close had OCA cancel attempted.
    assert bot._trade_executor._cancel_ib_bracket_orders.await_count >= 3
    # Exactly ONE new OCA bracket placed on canonical.
    assert bot._trade_executor.attach_oca_stop_target.await_count == 1


@pytest.mark.asyncio
async def test_canonical_falls_back_to_oldest_when_all_reconciled():
    trades = [
        _mk_trade(id="r1", symbol="LIN", remaining_shares=23,
                  entered_by="reconciled_excess_v19_34_15b",
                  setup_type="reconciled_excess_slice",
                  entry_time="2026-05-08T10:00:00+00:00"),
        _mk_trade(id="r2", symbol="LIN", remaining_shares=46,
                  entered_by="reconciled_excess_v19_34_15b",
                  setup_type="reconciled_excess_slice",
                  entry_time="2026-05-08T10:05:00+00:00"),
    ]
    bot = _mk_bot_with_trades(trades)
    diff = await PositionConsolidator().dry_run_consolidation(bot)
    g = diff["groups"][0]
    assert g["proposed_canonical"]["trade_id"] == "r1"  # oldest


@pytest.mark.asyncio
async def test_singleton_positions_not_touched():
    bot = _mk_bot_with_trades([
        _mk_trade(id="solo", symbol="EBAY", remaining_shares=553,
                  entered_by="squeeze", setup_type="squeeze"),
    ])
    diff = await PositionConsolidator().dry_run_consolidation(bot)
    assert diff["fragmented_groups"] == 0
    assert diff["groups"] == []


@pytest.mark.asyncio
async def test_spawn_excess_slice_grows_existing_instead_of_creating_new(monkeypatch):
    """Regression for BMNR 19-fragment bug: each drift tick must NOT create
    a new reconciled_excess slice when one already exists for the
    (symbol, direction) — it must grow the existing slice instead."""
    # Existing reconciled-excess slice
    existing = _mk_trade(
        id="exist", symbol="BMNR", direction="long", remaining_shares=802,
        entered_by="reconciled_excess_v19_34_15b",
        setup_type="reconciled_excess_slice",
        fill_price=22.48, stop_price=22.26, target=22.70,
    )
    bot = _mk_bot_with_trades([existing])

    # Patch trading_bot_service classes used by _spawn_excess_slice
    import services.trading_bot_service as tbs_mod
    tbs_mod.TradeDirection = SimpleNamespace(
        LONG=_DummyDirection("long"), SHORT=_DummyDirection("short")
    )
    tbs_mod.TradeStatus = SimpleNamespace(
        OPEN=SimpleNamespace(value="open"),
        CLOSED=SimpleNamespace(value="closed"),
    )
    # We don't actually instantiate BotTrade in the grow-path, but pass a stub
    # in case the code falls through.

    class _FakeBotTrade:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    reconciler = PositionReconciler()
    initial_open_count = len(bot._open_trades)

    new_id = await reconciler._spawn_excess_slice(
        bot, "BMNR", ib_qty_signed=4443, bot_q=802,
        ib_meta={"avg_cost": 22.45, "market_price": 21.82},
        ib_quote={"last": 21.82},
        stop_pct=1.0, rr=1.0,
        BotTrade=_FakeBotTrade,
        TradeDirection=tbs_mod.TradeDirection,
        TradeStatus=tbs_mod.TradeStatus,
    )

    # Returned ID is the EXISTING slice, not a new one.
    assert new_id == "exist"
    # No new trade row was added to _open_trades.
    assert len(bot._open_trades) == initial_open_count
    # Existing slice grew to 802 + (4443 - 802) = 4443.
    assert existing.remaining_shares == 4443
    # Old bracket was cancelled and a new one placed.
    assert bot._trade_executor._cancel_ib_bracket_orders.await_count == 1
    assert bot._trade_executor.attach_oca_stop_target.await_count == 1


@pytest.mark.asyncio
async def test_auto_consolidate_safety_rail_blocks_large_when_no_kill_switch():
    """When kill-switch is OFF and fragmentation is large (>2 per group),
    auto_consolidate_if_safe must NOT run."""
    trades = [_mk_trade(id=f"f{i}", symbol="BMNR", remaining_shares=100,
                        entered_by="reconciled_excess_v19_34_15b",
                        setup_type="reconciled_excess_slice")
              for i in range(5)]
    bot = _mk_bot_with_trades(trades)

    consolidator = PositionConsolidator()
    # Force kill-switch to report inactive.
    consolidator._is_kill_switch_active = staticmethod(lambda: False)

    out = await consolidator.auto_consolidate_if_safe(bot)
    assert out["ran"] is False
    assert "rail_blocked" in out["reason"]
    # No mutations.
    assert len(bot._open_trades) == 5


@pytest.mark.asyncio
async def test_auto_consolidate_runs_when_kill_switch_active():
    trades = [_mk_trade(id=f"f{i}", symbol="BMNR", remaining_shares=100,
                        entered_by="reconciled_excess_v19_34_15b",
                        setup_type="reconciled_excess_slice")
              for i in range(5)]
    bot = _mk_bot_with_trades(trades)

    import services.trading_bot_service as tbs_mod
    tbs_mod.TradeStatus = SimpleNamespace(
        OPEN=SimpleNamespace(value="open"),
        CLOSED=SimpleNamespace(value="closed"),
    )

    consolidator = PositionConsolidator()
    consolidator._is_kill_switch_active = staticmethod(lambda: True)

    out = await consolidator.auto_consolidate_if_safe(bot)
    assert out.get("success") is True
    # ran is implied by 'consolidated' key being present
    assert "consolidated" in out
    assert len(out["consolidated"]) == 1
    # 5 fragments → 1 canonical, 4 closed.
    assert len(bot._open_trades) == 1
