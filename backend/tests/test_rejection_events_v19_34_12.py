"""
test_rejection_events_v19_34_12.py — rejection event log + heatmap endpoint.

Pins:
  • `_persist_rejection_event` writes to `rejection_events` on every
    structural rejection (initial + extension paths).
  • Persistence failure NEVER blocks `mark_rejection`.
  • Endpoint contract: filters by symbol, setup_type, days, limit.
  • Endpoint heatmap aggregation: rows sorted by total_rejections desc;
    `by_reason` per cell; `top_reasons` overall; `max_rejections` for
    color scaling.
  • Endpoint stamps `created_at_iso` for the frontend.
"""
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ─── _persist_rejection_event ─────────────────────────────────────

class TestPersistRejectionEvent:

    def test_writes_to_rejection_events_collection(self):
        from services.rejection_cooldown_service import _persist_rejection_event
        import services.rejection_cooldown_service as rcs
        rcs._rejection_events_indexes_ready = False

        coll = MagicMock()
        coll.insert_one = MagicMock()
        coll.create_index = MagicMock()
        db = MagicMock()
        db.__getitem__.return_value = coll

        with patch("database.get_database", return_value=db):
            _persist_rejection_event(
                symbol="xlu", setup_type="ORB",
                reason="max_position_pct",
                rejection_count=1, extended=False,
            )
        coll.insert_one.assert_called_once()
        doc = coll.insert_one.call_args[0][0]
        assert doc["symbol"] == "XLU"      # uppercased
        assert doc["setup_type"] == "orb"  # lowercased
        assert doc["reason"] == "max_position_pct"
        assert doc["rejection_count"] == 1
        assert doc["extended"] is False
        assert "created_at" in doc
        # TTL + lookup indexes ensured
        assert coll.create_index.called

    def test_persist_failure_is_swallowed(self):
        """Mongo blip MUST NOT propagate from inside mark_rejection."""
        from services.rejection_cooldown_service import _persist_rejection_event
        coll = MagicMock()
        coll.create_index = MagicMock()
        coll.insert_one = MagicMock(side_effect=RuntimeError("mongo down"))
        db = MagicMock()
        db.__getitem__.return_value = coll
        with patch("database.get_database", return_value=db):
            # Should NOT raise
            _persist_rejection_event(
                symbol="X", setup_type="y", reason="kill_switch",
                rejection_count=1, extended=False,
            )

    def test_db_none_skips_silently(self):
        from services.rejection_cooldown_service import _persist_rejection_event
        with patch("database.get_database", return_value=None):
            _persist_rejection_event(
                symbol="X", setup_type="y", reason="kill_switch",
                rejection_count=1, extended=False,
            )  # no raise


# ─── mark_rejection integration → persistence ─────────────────────

class TestMarkRejectionPersists:

    def test_first_rejection_persists_event(self):
        from services.rejection_cooldown_service import (
            RejectionCooldown, reset_rejection_cooldown_for_tests,
        )
        reset_rejection_cooldown_for_tests()
        rc = RejectionCooldown(default_cooldown_seconds=300)

        coll = MagicMock()
        coll.insert_one = MagicMock()
        coll.create_index = MagicMock()
        db = MagicMock()
        db.__getitem__.return_value = coll
        with patch("database.get_database", return_value=db):
            entry = rc.mark_rejection(
                "XLU", "orb", reason="max_daily_loss",
            )
        assert entry is not None
        assert coll.insert_one.called
        doc = coll.insert_one.call_args[0][0]
        assert doc["symbol"] == "XLU"
        assert doc["setup_type"] == "orb"
        assert doc["extended"] is False
        assert doc["rejection_count"] == 1

    def test_extended_rejection_persists_with_extended_flag(self):
        from services.rejection_cooldown_service import (
            RejectionCooldown, reset_rejection_cooldown_for_tests,
        )
        reset_rejection_cooldown_for_tests()
        rc = RejectionCooldown(default_cooldown_seconds=300)

        coll = MagicMock()
        coll.insert_one = MagicMock()
        coll.create_index = MagicMock()
        db = MagicMock()
        db.__getitem__.return_value = coll
        with patch("database.get_database", return_value=db):
            rc.mark_rejection("XLU", "orb", reason="kill_switch")
            rc.mark_rejection("XLU", "orb", reason="kill_switch")  # extends
        # Two writes: initial + extension
        assert coll.insert_one.call_count == 2
        first = coll.insert_one.call_args_list[0][0][0]
        second = coll.insert_one.call_args_list[1][0][0]
        assert first["extended"] is False
        assert first["rejection_count"] == 1
        assert second["extended"] is True
        assert second["rejection_count"] == 2

    def test_transient_rejection_does_not_persist(self):
        from services.rejection_cooldown_service import (
            RejectionCooldown, reset_rejection_cooldown_for_tests,
        )
        reset_rejection_cooldown_for_tests()
        rc = RejectionCooldown(default_cooldown_seconds=300)
        coll = MagicMock()
        coll.insert_one = MagicMock()
        db = MagicMock()
        db.__getitem__.return_value = coll
        with patch("database.get_database", return_value=db):
            entry = rc.mark_rejection("XLU", "orb", reason="stale_quote")
        assert entry is None
        coll.insert_one.assert_not_called()


# ─── Endpoint contract: GET /api/trading-bot/rejection-events ─────

def _make_db_with_rows(rows):
    coll = MagicMock()
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.limit.return_value = iter(rows)
    coll.find = MagicMock(return_value=cursor)
    db = MagicMock()
    db.__getitem__.return_value = coll
    db._coll = coll
    return db


class TestRejectionEventsEndpoint:

    @pytest.mark.asyncio
    async def test_503_when_bot_missing(self):
        from routers import trading_bot as tb
        from fastapi import HTTPException
        original = tb._trading_bot
        tb._trading_bot = None
        try:
            with pytest.raises(HTTPException) as exc:
                await tb.get_rejection_events()
            assert exc.value.status_code == 503
        finally:
            tb._trading_bot = original

    @pytest.mark.asyncio
    async def test_heatmap_aggregation(self):
        from routers import trading_bot as tb
        now = datetime.now(timezone.utc)
        rows = [
            # XLU/orb gets 3 max_position_pct rejections + 1 kill_switch
            {"symbol": "XLU", "setup_type": "orb",
             "reason": "max_position_pct", "rejection_count": 1,
             "extended": False, "created_at": now},
            {"symbol": "XLU", "setup_type": "orb",
             "reason": "max_position_pct", "rejection_count": 2,
             "extended": True, "created_at": now - timedelta(minutes=5)},
            {"symbol": "XLU", "setup_type": "orb",
             "reason": "max_position_pct", "rejection_count": 3,
             "extended": True, "created_at": now - timedelta(minutes=10)},
            {"symbol": "XLU", "setup_type": "orb",
             "reason": "kill_switch", "rejection_count": 4,
             "extended": True, "created_at": now - timedelta(minutes=15)},
            # AAPL/breakout gets 1 max_daily_loss
            {"symbol": "AAPL", "setup_type": "breakout",
             "reason": "max_daily_loss", "rejection_count": 1,
             "extended": False, "created_at": now - timedelta(minutes=20)},
        ]
        bot = MagicMock()
        bot._db = _make_db_with_rows(rows)
        original = tb._trading_bot
        tb._trading_bot = bot
        try:
            resp = await tb.get_rejection_events(days=7, limit=100)
        finally:
            tb._trading_bot = original

        assert resp["success"] is True
        # Events normalised
        assert len(resp["events"]) == 5
        for ev in resp["events"]:
            assert "created_at_iso" in ev

        hm = resp["heatmap"]
        # 2 cells: XLU/orb (4 rejections), AAPL/breakout (1)
        assert len(hm["rows"]) == 2
        # Sorted desc by total
        assert hm["rows"][0]["symbol"] == "XLU"
        assert hm["rows"][0]["total_rejections"] == 4
        assert hm["rows"][0]["by_reason"]["max_position_pct"] == 3
        assert hm["rows"][0]["by_reason"]["kill_switch"] == 1
        assert hm["rows"][1]["symbol"] == "AAPL"
        assert hm["rows"][1]["total_rejections"] == 1
        assert set(hm["symbols"]) == {"XLU", "AAPL"}
        assert set(hm["setups"]) == {"orb", "breakout"}
        assert hm["max_rejections"] == 4
        assert hm["total_events"] == 5
        # Top reasons
        top_reason_names = [r["reason"] for r in hm["top_reasons"]]
        assert "max_position_pct" in top_reason_names

    @pytest.mark.asyncio
    async def test_symbol_filter_uppercases(self):
        from routers import trading_bot as tb
        captured = {}
        coll = MagicMock()
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.limit.return_value = iter([])
        def _find(q, projection=None):
            captured.update(q)
            return cursor
        coll.find = MagicMock(side_effect=_find)
        bot = MagicMock()
        bot._db = MagicMock()
        bot._db.__getitem__.return_value = coll
        original = tb._trading_bot
        tb._trading_bot = bot
        try:
            await tb.get_rejection_events(symbol="xlu", setup_type="ORB", days=1)
        finally:
            tb._trading_bot = original
        assert captured["symbol"] == "XLU"
        assert captured["setup_type"] == "orb"

    @pytest.mark.asyncio
    async def test_no_db_returns_clean_error(self):
        from routers import trading_bot as tb
        bot = MagicMock()
        bot._db = None
        original = tb._trading_bot
        tb._trading_bot = bot
        try:
            resp = await tb.get_rejection_events(days=7)
        finally:
            tb._trading_bot = original
        assert resp["success"] is False
        assert resp["events"] == []
        assert resp["heatmap"]["rows"] == []
