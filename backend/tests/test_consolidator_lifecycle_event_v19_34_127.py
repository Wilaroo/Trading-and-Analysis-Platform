"""v19.34.127 — Consolidator-merge must persist `bracket_lifecycle_events`.

Pre-v127 the consolidator (`PositionConsolidator._consolidate_one_group`)
performed cancel-old + attach-new on the canonical, but never wrote a
row to `bracket_lifecycle_events`. Result: when yesterday's incident
hit RJF/MTB/ARGX/UPS, the operator's
`/api/diagnostic/bracket-lifecycle?symbol=RJF` returned 0 events even
though consolidations DID run. Untraceable.

v127 adds a `phase: "consolidator_merge_reissue"` event for every
merge, schema-compatible with the existing
`bracket_reissue_service._persist_lifecycle_event` writer.

This test locks the contract: success AND failure paths emit the
audit event with the right schema.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, "/app/backend")

from services.position_consolidator import PositionConsolidator  # noqa: E402


class _DummyDirection:
    def __init__(self, val):
        self.value = val


def _mk_trade(*, id, symbol, direction="long", remaining_shares=100,
              entry_time="2026-05-08T10:00:00+00:00", entered_by="squeeze",
              setup_type="squeeze", stop_price=21.36, target=25.59,
              fill_price=22.45):
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


def _mk_bot(trades, *, oca_success=True, oca_error="IB rejected"):
    bot = SimpleNamespace()
    bot._open_trades = {t.id: t for t in trades}
    bot._closed_trades = []
    bot._db = MagicMock()
    bot._db.__getitem__.return_value = MagicMock()
    bot._save_trade = MagicMock(return_value=None)
    bot._persist_trade = MagicMock(return_value=None)
    bot._stop_manager = MagicMock()
    executor = MagicMock()
    executor._cancel_ib_bracket_orders = AsyncMock(return_value=None)
    if oca_success:
        executor.attach_oca_stop_target = AsyncMock(
            return_value={
                "success": True, "stop_order_id": 999,
                "target_order_id": 888, "oca_group": "OCA-MERGE-TEST",
            }
        )
    else:
        executor.attach_oca_stop_target = AsyncMock(
            return_value={"success": False, "error": oca_error}
        )
    bot._trade_executor = executor
    return bot


def _patch_trade_status():
    """Consolidator imports TradeStatus inside the function — patch
    the module attribute the same way the existing v42 tests do."""
    import services.trading_bot_service as tbs_mod
    tbs_mod.TradeStatus = SimpleNamespace(
        CLOSED=SimpleNamespace(value="closed"),
        OPEN=SimpleNamespace(value="open"),
    )


@pytest.mark.asyncio
async def test_consolidator_emits_lifecycle_event_on_success():
    """Merge with successful OCA attach ⇒ event written with success=True
    and the merged share count."""
    _patch_trade_status()
    trades = [
        _mk_trade(id="canon", symbol="RJF", remaining_shares=200,
                  entered_by="momentum", setup_type="momentum"),
        _mk_trade(id="sib1", symbol="RJF", remaining_shares=100,
                  entered_by="reconciled_excess_v19_34_15b",
                  setup_type="reconciled_excess_slice"),
        _mk_trade(id="sib2", symbol="RJF", remaining_shares=78,
                  entered_by="reconciled_excess_v19_34_15b",
                  setup_type="reconciled_excess_slice"),
    ]
    bot = _mk_bot(trades, oca_success=True)

    with patch(
        "services.bracket_reissue_service._persist_lifecycle_event",
        new_callable=AsyncMock,
    ) as persist_mock:
        result = await PositionConsolidator().apply_consolidation(
            bot, symbols=["RJF"], confirm=True,
        )

    assert result["success"] is True
    persist_mock.assert_awaited_once()
    ev = persist_mock.await_args.kwargs["event"]
    assert ev["phase"] == "consolidator_merge_reissue"
    assert ev["success"] is True
    assert ev["trade_id"] == "canon"
    assert ev["symbol"] == "RJF"
    assert ev["new_total_shares"] == 200 + 100 + 78
    assert ev["old_canonical_shares"] == 200
    assert sorted(ev["merged_from_siblings"]) == ["sib1", "sib2"]
    assert ev["oca_group"] == "OCA-MERGE-TEST"
    assert ev["error"] is None


@pytest.mark.asyncio
async def test_consolidator_emits_lifecycle_event_on_naked_failure():
    """Merge with FAILED OCA attach ⇒ event written with success=False
    so the operator's diagnostic surfaces this naked canonical."""
    _patch_trade_status()
    trades = [
        _mk_trade(id="canon", symbol="MTB", remaining_shares=200,
                  entered_by="momentum"),
        _mk_trade(id="sib1", symbol="MTB", remaining_shares=100,
                  entered_by="reconciled_excess_v19_34_15b"),
    ]
    bot = _mk_bot(trades, oca_success=False, oca_error="IB: max orders exceeded")

    with patch(
        "services.bracket_reissue_service._persist_lifecycle_event",
        new_callable=AsyncMock,
    ) as persist_mock:
        await PositionConsolidator().apply_consolidation(
            bot, symbols=["MTB"], confirm=True,
        )

    persist_mock.assert_awaited_once()
    ev = persist_mock.await_args.kwargs["event"]
    assert ev["phase"] == "consolidator_merge_reissue"
    assert ev["success"] is False
    assert "max orders exceeded" in ev["error"]
    assert ev["new_stop_order_id"] is None
