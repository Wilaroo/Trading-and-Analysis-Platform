"""
test_eod_order_safety_v19_34_6.py — pin the v19.34.6 EOD safety pair:

  POST /api/trading-bot/eod-validate-overnight-orders  — sweep & cancel
       orphan / wrong-TIF overnight legs (item g)
  POST /api/trading-bot/cancel-orders-for-symbol      — EOD pre-cancel
       guard for a single symbol (item f)

Both close the runtime + EOD edges of the GTC-zombie bug that v19.34.5
fixed at *placement* time. They give the operator and the EOD close
path a way to neutralize bracket legs that would otherwise survive
market close and randomly fire overnight.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _bracket_order(**overrides):
    base = {
        "order_id": "ord-bracket-1",
        "symbol": "STX",
        "order_type": "bracket",
        "status": "pending",
        "trade_id": "trade-1",
        "queued_at": "2026-05-05T13:30:00+00:00",
        "parent": {"action": "BUY", "time_in_force": "DAY"},
        "stop":   {"action": "SELL", "time_in_force": "GTC", "outside_rth": True},
        "target": {"action": "SELL", "time_in_force": "GTC", "outside_rth": True},
    }
    base.update(overrides)
    return base


def _flat_day_order(**overrides):
    base = {
        "order_id": "ord-flat-1",
        "symbol": "HOOD",
        "order_type": "MKT",
        "status": "pending",
        "trade_id": "trade-2",
        "queued_at": "2026-05-05T13:30:00+00:00",
        "time_in_force": "DAY",
        "outside_rth": False,
    }
    base.update(overrides)
    return base


def _patch_queue_with(active_rows, parent_trades_by_id=None, captured=None):
    """Mock get_order_queue_service + the bot's _db.bot_trades cursor."""
    fake_collection = MagicMock()
    fake_collection.find = MagicMock(return_value=active_rows)
    cancel_attempts = []

    def _cancel(order_id):
        cancel_attempts.append(order_id)
        if captured is not None:
            captured.setdefault("cancelled", []).append(order_id)
        return True

    fake_service = MagicMock()
    fake_service._initialized = True
    fake_service._collection = fake_collection
    fake_service.initialize = MagicMock()
    fake_service.cancel_order = _cancel
    fake_service.cancel_attempts = cancel_attempts

    return fake_service, parent_trades_by_id or {}


# --------------------------------------------------------------------------
# Tests — eod_validate_overnight_orders
# --------------------------------------------------------------------------

class TestEodValidateOvernightOrdersV19_34_6:

    @pytest.mark.asyncio
    async def test_dry_run_classifies_overnight_legs_correctly(self):
        from routers import trading_bot as tb

        # Setup:
        #   ord-1: bracket with GTC stop legs, parent IS swing → ok
        #   ord-2: bracket with GTC stop legs, parent IS intraday → wrong_tif
        #   ord-3: bracket with GTC stop legs, NO parent → orphan
        #   ord-4: flat DAY order — never overnight → not in rows
        active = [
            _bracket_order(order_id="ord-1", trade_id="t-swing", symbol="MELI"),
            _bracket_order(order_id="ord-2", trade_id="t-intraday", symbol="HOOD"),
            _bracket_order(order_id="ord-3", trade_id="t-missing", symbol="STX"),
            _flat_day_order(order_id="ord-4", trade_id="t-flat"),
        ]
        # bot_trades parents
        parents = [
            {"id": "t-swing",    "trade_style": "multi_day",  "timeframe": "swing",
             "symbol": "MELI", "status": "open", "direction": "long"},
            {"id": "t-intraday", "trade_style": "intraday",   "timeframe": "intraday",
             "symbol": "HOOD", "status": "open", "direction": "long"},
            # t-missing intentionally absent
        ]
        fake_service, _ = _patch_queue_with(active)

        # Fake bot._db.bot_trades.find()
        fake_db = MagicMock()
        fake_db.bot_trades.find = MagicMock(return_value=parents)
        fake_bot = MagicMock()
        fake_bot._db = fake_db

        original_bot = tb._trading_bot
        tb._trading_bot = fake_bot

        try:
            with patch("services.order_queue_service.get_order_queue_service",
                       return_value=fake_service):
                resp = await tb.eod_validate_overnight_orders({"dry_run": True})
        finally:
            tb._trading_bot = original_bot

        assert resp["success"] is True
        assert resp["summary"]["total_active"] == 4
        assert resp["summary"]["overnight_legs"] == 3  # ord-1/2/3
        assert resp["summary"]["ok"] == 1  # ord-1
        assert resp["summary"]["wrong_tif"] == 1  # ord-2
        assert resp["summary"]["orphans"] == 1  # ord-3
        assert resp["summary"]["cancelled_count"] == 0  # dry_run

        # No actual cancellations
        assert fake_service.cancel_attempts == []

    @pytest.mark.asyncio
    async def test_actually_cancels_when_confirm_token_passed(self):
        from routers import trading_bot as tb

        active = [
            _bracket_order(order_id="ord-orphan", trade_id="t-missing", symbol="STX"),
            _bracket_order(order_id="ord-wrong",  trade_id="t-intraday", symbol="HOOD"),
            _bracket_order(order_id="ord-ok",     trade_id="t-swing", symbol="MELI"),
        ]
        parents = [
            {"id": "t-swing",    "trade_style": "multi_day", "timeframe": "swing",
             "symbol": "MELI", "status": "open", "direction": "long"},
            {"id": "t-intraday", "trade_style": "intraday",  "timeframe": "intraday",
             "symbol": "HOOD", "status": "open", "direction": "long"},
        ]
        fake_service, _ = _patch_queue_with(active)
        fake_db = MagicMock()
        fake_db.bot_trades.find = MagicMock(return_value=parents)
        fake_bot = MagicMock()
        fake_bot._db = fake_db

        original_bot = tb._trading_bot
        tb._trading_bot = fake_bot
        try:
            with patch("services.order_queue_service.get_order_queue_service",
                       return_value=fake_service):
                resp = await tb.eod_validate_overnight_orders({
                    "confirm": "CANCEL_ORPHANS",
                    "dry_run": False,
                })
        finally:
            tb._trading_bot = original_bot

        assert resp["success"] is True
        # Both orphan + wrong-tif rows cancelled, ok row left alone
        assert resp["summary"]["cancelled_count"] == 2
        assert sorted(fake_service.cancel_attempts) == ["ord-orphan", "ord-wrong"]

    @pytest.mark.asyncio
    async def test_no_active_orders_returns_clean_summary(self):
        from routers import trading_bot as tb

        fake_service, _ = _patch_queue_with([])
        fake_db = MagicMock()
        fake_db.bot_trades.find = MagicMock(return_value=[])
        fake_bot = MagicMock()
        fake_bot._db = fake_db

        original_bot = tb._trading_bot
        tb._trading_bot = fake_bot
        try:
            with patch("services.order_queue_service.get_order_queue_service",
                       return_value=fake_service):
                resp = await tb.eod_validate_overnight_orders({})
        finally:
            tb._trading_bot = original_bot

        assert resp["success"] is True
        assert resp["summary"]["total_active"] == 0
        assert resp["summary"]["overnight_legs"] == 0
        assert resp["summary"]["cancelled_count"] == 0
        assert resp["rows"] == []

    @pytest.mark.asyncio
    async def test_dry_run_default_is_safe(self):
        """Empty payload → MUST default to dry_run=True. Operator
        clicking the button without thinking should NEVER cancel."""
        from routers import trading_bot as tb

        active = [_bracket_order(order_id="ord-orphan", trade_id="t-missing")]
        fake_service, _ = _patch_queue_with(active)
        fake_db = MagicMock()
        fake_db.bot_trades.find = MagicMock(return_value=[])
        fake_bot = MagicMock()
        fake_bot._db = fake_db

        original_bot = tb._trading_bot
        tb._trading_bot = fake_bot
        try:
            with patch("services.order_queue_service.get_order_queue_service",
                       return_value=fake_service):
                # NO confirm, NO dry_run flag
                resp = await tb.eod_validate_overnight_orders(None)
        finally:
            tb._trading_bot = original_bot

        assert resp["success"] is True
        assert resp["dry_run"] is True
        assert resp["summary"]["cancelled_count"] == 0
        assert fake_service.cancel_attempts == []

    @pytest.mark.asyncio
    async def test_confirm_without_dry_run_false_still_dry_run(self):
        """`confirm=CANCEL_ORPHANS` alone is NOT enough — must also
        pass `dry_run=False`. Two-step safety to avoid one-keystroke
        cancellation of overnight protection."""
        from routers import trading_bot as tb

        active = [_bracket_order(order_id="ord-orphan", trade_id="t-missing")]
        fake_service, _ = _patch_queue_with(active)
        fake_db = MagicMock()
        fake_db.bot_trades.find = MagicMock(return_value=[])
        fake_bot = MagicMock()
        fake_bot._db = fake_db

        original_bot = tb._trading_bot
        tb._trading_bot = fake_bot
        try:
            with patch("services.order_queue_service.get_order_queue_service",
                       return_value=fake_service):
                resp = await tb.eod_validate_overnight_orders({
                    "confirm": "CANCEL_ORPHANS",
                    # dry_run defaults to True
                })
        finally:
            tb._trading_bot = original_bot

        assert resp["dry_run"] is True
        assert fake_service.cancel_attempts == []


# --------------------------------------------------------------------------
# Tests — cancel_orders_for_symbol
# --------------------------------------------------------------------------

class TestCancelOrdersForSymbolV19_34_6:

    @pytest.mark.asyncio
    async def test_cancels_active_orders_for_symbol(self):
        from routers import trading_bot as tb
        from fastapi import HTTPException

        active = [
            _bracket_order(order_id="ord-1", symbol="STX"),
            _bracket_order(order_id="ord-2", symbol="STX", status="claimed"),
        ]
        fake_service, _ = _patch_queue_with(active)
        with patch("services.order_queue_service.get_order_queue_service",
                   return_value=fake_service):
            resp = await tb.cancel_orders_for_symbol({
                "symbol": "STX",
                "confirm": "CANCEL_FOR_SYMBOL",
            })

        assert resp["success"] is True
        assert resp["symbol"] == "STX"
        assert resp["matched"] == 2
        assert resp["cancelled_count"] == 2
        assert sorted(fake_service.cancel_attempts) == ["ord-1", "ord-2"]

    @pytest.mark.asyncio
    async def test_dry_run_skips_cancel(self):
        from routers import trading_bot as tb
        active = [_bracket_order(order_id="ord-1", symbol="STX")]
        fake_service, _ = _patch_queue_with(active)
        with patch("services.order_queue_service.get_order_queue_service",
                   return_value=fake_service):
            resp = await tb.cancel_orders_for_symbol({
                "symbol": "STX",
                "confirm": "CANCEL_FOR_SYMBOL",
                "dry_run": True,
            })

        assert resp["matched"] == 1
        assert resp["cancelled_count"] == 0
        assert fake_service.cancel_attempts == []

    @pytest.mark.asyncio
    async def test_missing_confirm_token_raises_400(self):
        from routers import trading_bot as tb
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await tb.cancel_orders_for_symbol({"symbol": "STX"})
        assert exc.value.status_code == 400
        assert "CANCEL_FOR_SYMBOL" in exc.value.detail

    @pytest.mark.asyncio
    async def test_missing_symbol_raises_400(self):
        from routers import trading_bot as tb
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await tb.cancel_orders_for_symbol({
                "confirm": "CANCEL_FOR_SYMBOL",
            })
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_symbol_uppercased_for_query(self):
        from routers import trading_bot as tb
        captured = {}

        # Build a custom service that captures the find query
        fake_collection = MagicMock()
        def _find(q, projection=None):
            captured["q"] = q
            return []
        fake_collection.find = _find
        fake_service = MagicMock()
        fake_service._initialized = True
        fake_service._collection = fake_collection
        fake_service.cancel_order = MagicMock(return_value=True)

        with patch("services.order_queue_service.get_order_queue_service",
                   return_value=fake_service):
            await tb.cancel_orders_for_symbol({
                "symbol": "stx",
                "confirm": "CANCEL_FOR_SYMBOL",
            })

        assert captured["q"]["symbol"] == "STX"

    @pytest.mark.asyncio
    async def test_no_active_orders_returns_empty(self):
        from routers import trading_bot as tb
        fake_service, _ = _patch_queue_with([])
        with patch("services.order_queue_service.get_order_queue_service",
                   return_value=fake_service):
            resp = await tb.cancel_orders_for_symbol({
                "symbol": "STX",
                "confirm": "CANCEL_FOR_SYMBOL",
            })

        assert resp["success"] is True
        assert resp["matched"] == 0
        assert resp["cancelled_count"] == 0
        assert resp["rows"] == []


# --------------------------------------------------------------------------
# Tests — _is_overnight_leg helper
# --------------------------------------------------------------------------

class TestIsOvernightLegHelper:

    def test_bracket_with_gtc_stop_is_overnight(self):
        from routers.trading_bot import _is_overnight_leg
        order = _bracket_order()
        assert _is_overnight_leg(order) is True

    def test_bracket_with_day_only_is_intraday(self):
        from routers.trading_bot import _is_overnight_leg
        order = _bracket_order(
            parent={"time_in_force": "DAY", "outside_rth": False},
            stop={"time_in_force": "DAY", "outside_rth": False},
            target={"time_in_force": "DAY", "outside_rth": False},
        )
        assert _is_overnight_leg(order) is False

    def test_flat_day_order_is_intraday(self):
        from routers.trading_bot import _is_overnight_leg
        order = _flat_day_order()
        assert _is_overnight_leg(order) is False

    def test_flat_gtc_order_is_overnight(self):
        from routers.trading_bot import _is_overnight_leg
        order = _flat_day_order(time_in_force="GTC")
        assert _is_overnight_leg(order) is True

    def test_outside_rth_true_alone_is_overnight(self):
        """outside_rth=True is a flag in itself: this is a stop that
        will fire pre-market or after-hours, which is overnight by
        every reasonable definition. Must be flagged."""
        from routers.trading_bot import _is_overnight_leg
        order = _flat_day_order(time_in_force="DAY", outside_rth=True)
        assert _is_overnight_leg(order) is True
