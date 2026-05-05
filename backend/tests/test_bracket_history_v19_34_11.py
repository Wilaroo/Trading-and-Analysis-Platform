"""
test_bracket_history_v19_34_11.py — bracket lifecycle event log
+ `GET /api/trading-bot/bracket-history` endpoint.

Pins:
  • `_persist_lifecycle_event` writes to `bracket_lifecycle_events`
    on every reissue path (compute fail / cancel fail / submit fail /
    success).
  • Persistence failure NEVER blocks the broker call path.
  • Endpoint filter contracts: trade_id, symbol, days, limit.
  • Endpoint summary aggregations: total, success_count, failure_count,
    by_reason.
  • Endpoint stamps `created_at_iso` for the frontend.
"""
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _make_db_with_collection(rows):
    """Build a fake `db[<coll>]` that returns `rows` from find()."""
    coll = MagicMock()
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.limit.return_value = iter(rows)
    coll.find = MagicMock(return_value=cursor)
    coll.insert_one = MagicMock()
    coll.create_index = MagicMock()

    db = MagicMock()
    db.__getitem__.return_value = coll
    db._coll = coll
    return db


# ─── _persist_lifecycle_event ─────────────────────────────────────

class TestPersistLifecycleEvent:

    @pytest.mark.asyncio
    async def test_writes_to_bracket_lifecycle_events(self):
        from services.bracket_reissue_service import _persist_lifecycle_event
        # Reset module-level "indexes ready" flag so create_index runs
        import services.bracket_reissue_service as brs
        brs._lifecycle_indexes_ready = False
        bot = MagicMock()
        bot._db = _make_db_with_collection([])
        event = {
            "success": True,
            "phase": "done",
            "trade_id": "abc-123",
            "symbol": "AAPL",
            "reason": "scale_out_t1",
            "plan": {"new_stop_price": 145.5},
        }
        await _persist_lifecycle_event(bot=bot, event=event)
        bot._db._coll.insert_one.assert_called_once()
        doc = bot._db._coll.insert_one.call_args[0][0]
        assert doc["trade_id"] == "abc-123"
        assert doc["symbol"] == "AAPL"
        assert doc["reason"] == "scale_out_t1"
        assert "created_at" in doc
        # Indexes were ensured (TTL + lookups)
        assert bot._db._coll.create_index.called

    @pytest.mark.asyncio
    async def test_persist_failure_is_swallowed(self):
        """Mongo blip MUST NOT propagate — broker call is the priority."""
        from services.bracket_reissue_service import _persist_lifecycle_event
        bot = MagicMock()
        coll = MagicMock()
        coll.create_index = MagicMock()
        coll.insert_one = MagicMock(side_effect=RuntimeError("mongo down"))
        bot._db = MagicMock()
        bot._db.__getitem__.return_value = coll
        # Should NOT raise
        await _persist_lifecycle_event(
            bot=bot, event={"success": True, "trade_id": "x"},
        )

    @pytest.mark.asyncio
    async def test_db_none_skips_silently(self):
        from services.bracket_reissue_service import _persist_lifecycle_event
        bot = MagicMock()
        bot._db = None
        await _persist_lifecycle_event(
            bot=bot, event={"success": True, "trade_id": "x"},
        )  # no raise


# ─── reissue_bracket_for_trade integration ────────────────────────

class TestReissueIntegration:
    """Confirm every return path persists a lifecycle event."""

    @pytest.mark.asyncio
    async def test_compute_failure_persists_event(self):
        """A bad trade (no symbol / no shares) → compute fails, event still logged."""
        from services.bracket_reissue_service import reissue_bracket_for_trade

        bot = MagicMock()
        bot._db = _make_db_with_collection([])
        bot.risk_params = MagicMock()
        bot.risk_params.reconciled_default_stop_pct = 2.0
        bot.risk_params.reconciled_default_rr = 2.0

        bad_trade = MagicMock()
        bad_trade.id = "bad-1"
        bad_trade.symbol = None  # forces compute failure
        bad_trade.remaining_shares = 0
        bad_trade.scale_out_pcts = []
        bad_trade.entry_price = 0
        bad_trade.target_prices = []

        with patch("services.bracket_reissue_service.compute_reissue_params",
                   side_effect=ValueError("symbol missing")):
            result = await reissue_bracket_for_trade(
                trade=bad_trade, bot=bot, reason="manual",
                queue_service=MagicMock(_initialized=True),
                queue_order_fn=MagicMock(),
            )
        assert result["success"] is False
        assert result["phase"] == "compute"
        # Event was persisted on the failure path
        bot._db._coll.insert_one.assert_called_once()
        doc = bot._db._coll.insert_one.call_args[0][0]
        assert doc["success"] is False
        assert doc["phase"] == "compute"


# ─── Endpoint contract: GET /api/trading-bot/bracket-history ──────

class TestBracketHistoryEndpoint:

    @pytest.mark.asyncio
    async def test_503_when_bot_missing(self):
        from routers import trading_bot as tb
        from fastapi import HTTPException
        original = tb._trading_bot
        tb._trading_bot = None
        try:
            with pytest.raises(HTTPException) as exc:
                await tb.get_bracket_history()
            assert exc.value.status_code == 503
        finally:
            tb._trading_bot = original

    @pytest.mark.asyncio
    async def test_returns_filtered_events_with_summary(self):
        from routers import trading_bot as tb
        now = datetime.now(timezone.utc)
        rows = [
            {"trade_id": "t1", "symbol": "AAPL", "reason": "scale_out_t1",
             "success": True, "phase": "done", "created_at": now},
            {"trade_id": "t1", "symbol": "AAPL", "reason": "scale_out_t1",
             "success": False, "phase": "submit", "error": "rejected",
             "created_at": now - timedelta(hours=1)},
            {"trade_id": "t1", "symbol": "AAPL", "reason": "manual",
             "success": True, "phase": "done", "created_at": now - timedelta(hours=2)},
        ]
        bot = MagicMock()
        bot._db = _make_db_with_collection(rows)

        original = tb._trading_bot
        tb._trading_bot = bot
        try:
            resp = await tb.get_bracket_history(trade_id="t1", days=7, limit=100)
        finally:
            tb._trading_bot = original

        assert resp["success"] is True
        assert len(resp["events"]) == 3
        # Timestamps stamped
        for ev in resp["events"]:
            assert "created_at_iso" in ev
        # Summary aggregations
        assert resp["summary"]["total"] == 3
        assert resp["summary"]["success_count"] == 2
        assert resp["summary"]["failure_count"] == 1
        assert resp["summary"]["by_reason"]["scale_out_t1"] == 2
        assert resp["summary"]["by_reason"]["manual"] == 1
        # Filter applied
        assert resp["filters"]["trade_id"] == "t1"

    @pytest.mark.asyncio
    async def test_no_db_returns_clean_error(self):
        from routers import trading_bot as tb
        bot = MagicMock()
        bot._db = None
        original = tb._trading_bot
        tb._trading_bot = bot
        try:
            resp = await tb.get_bracket_history(trade_id="t1")
        finally:
            tb._trading_bot = original
        assert resp["success"] is False
        assert resp["error"] == "no_database"
        assert resp["events"] == []

    @pytest.mark.asyncio
    async def test_symbol_filter_uppercases(self):
        """Symbol filter must uppercase to match Mongo records."""
        from routers import trading_bot as tb
        captured_query = {}
        coll = MagicMock()
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.limit.return_value = iter([])
        def _find(q, projection=None):
            captured_query.update(q)
            return cursor
        coll.find = MagicMock(side_effect=_find)
        bot = MagicMock()
        bot._db = MagicMock()
        bot._db.__getitem__.return_value = coll
        original = tb._trading_bot
        tb._trading_bot = bot
        try:
            await tb.get_bracket_history(symbol="aapl", days=3)
        finally:
            tb._trading_bot = original
        assert captured_query["symbol"] == "AAPL"
