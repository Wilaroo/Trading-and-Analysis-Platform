"""
test_boot_sweep_lifecycle_v19_34_16.py — pins the v19.34.16 wiring
that persists per-trade lifecycle events for boot-zombie-sweep
findings (orphans + wrong-tif rows).

Operator approval (2026-05-06): only log when findings exist
(skip clean sweeps), and add a per-trade lifecycle row when a
specific bracket is flagged.
"""
import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestPersistLifecycleEventCapturesOrphan:

    @pytest.mark.asyncio
    async def test_orphan_row_writes_to_bracket_lifecycle_events(self):
        """Verify `_persist_lifecycle_event` writes the boot-sweep
        row with `phase=boot_zombie_sweep` and the operator-required
        per-trade fields."""
        from services.bracket_reissue_service import _persist_lifecycle_event

        # Mock bot with _db
        coll = MagicMock()
        coll.create_index = MagicMock()
        coll.insert_one = MagicMock()
        db = MagicMock()
        db.__getitem__.return_value = coll
        bot = MagicMock()
        bot._db = db

        await _persist_lifecycle_event(
            bot=bot,
            event={
                "phase": "boot_zombie_sweep",
                "reason": "orphan_no_parent",
                "trade_id": "t-orphan-1",
                "symbol": "UPS",
                "order_id": "ord-123",
                "tif_summary": {"parent": "GTC", "stop": "GTC", "target": "GTC"},
                "detail": "No active bot_trades row for trade_id",
            },
        )

        # insert_one called with the event payload + created_at stamp.
        assert coll.insert_one.called
        doc = coll.insert_one.call_args.args[0]
        assert doc["phase"] == "boot_zombie_sweep"
        assert doc["reason"] == "orphan_no_parent"
        assert doc["trade_id"] == "t-orphan-1"
        assert doc["symbol"] == "UPS"
        assert "created_at" in doc

    @pytest.mark.asyncio
    async def test_wrong_tif_row_writes_with_parent_metadata(self):
        from services.bracket_reissue_service import _persist_lifecycle_event

        coll = MagicMock()
        coll.create_index = MagicMock()
        coll.insert_one = MagicMock()
        db = MagicMock()
        db.__getitem__.return_value = coll
        bot = MagicMock()
        bot._db = db

        await _persist_lifecycle_event(
            bot=bot,
            event={
                "phase": "boot_zombie_sweep",
                "reason": "wrong_tif_intraday_parent",
                "trade_id": "t-wrong-1",
                "symbol": "AAPL",
                "parent_trade_style": "intraday_scalp",
                "parent_timeframe": "5min",
                "tif_summary": {"parent": "GTC"},
                "detail": "Parent trade is intraday — overnight leg would zombify",
            },
        )

        doc = coll.insert_one.call_args.args[0]
        assert doc["reason"] == "wrong_tif_intraday_parent"
        assert doc["parent_trade_style"] == "intraday_scalp"
        assert doc["parent_timeframe"] == "5min"

    @pytest.mark.asyncio
    async def test_persistence_failure_does_not_raise(self):
        """Mongo blip must NEVER wedge the boot-sweep path."""
        from services.bracket_reissue_service import _persist_lifecycle_event

        coll = MagicMock()
        coll.insert_one.side_effect = RuntimeError("mongo down")
        db = MagicMock()
        db.__getitem__.return_value = coll
        bot = MagicMock()
        bot._db = db

        # No exception should propagate.
        await _persist_lifecycle_event(
            bot=bot,
            event={"phase": "boot_zombie_sweep", "reason": "orphan_no_parent",
                   "trade_id": "x"},
        )

    @pytest.mark.asyncio
    async def test_summary_row_has_phase_summary(self):
        from services.bracket_reissue_service import _persist_lifecycle_event

        coll = MagicMock()
        coll.insert_one = MagicMock()
        db = MagicMock()
        db.__getitem__.return_value = coll
        bot = MagicMock()
        bot._db = db

        await _persist_lifecycle_event(
            bot=bot,
            event={
                "phase": "boot_zombie_sweep_summary",
                "reason": "boot_sweep_findings",
                "trade_id": None,
                "symbol": None,
                "summary": {"orphans": 2, "wrong_tif": 1, "total_active": 5, "ok": 2},
                "row_count": 3,
            },
        )

        doc = coll.insert_one.call_args.args[0]
        assert doc["phase"] == "boot_zombie_sweep_summary"
        assert doc["summary"]["orphans"] == 2
        assert doc["row_count"] == 3
