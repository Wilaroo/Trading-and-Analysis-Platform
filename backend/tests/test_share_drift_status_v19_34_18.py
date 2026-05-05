"""
test_share_drift_status_v19_34_18.py — pins the read-only diagnostic
endpoint built per operator request 2026-05-06 to investigate why
v19.34.15b drift loop missed the 93sh FDX + 338sh UPS naked drift.
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestEndpointShape:

    @pytest.mark.asyncio
    async def test_returns_loop_block_with_required_fields(self):
        """Response must include `loop.alive`, `diag.tick_count`, etc."""
        from routers import trading_bot as tb_router

        # Build a minimal _trading_bot stand-in.
        bot = MagicMock()
        bot._open_trades = {}
        bot._share_drift_diag = {
            "tick_count": 12, "last_tick_at": "2026-05-06T20:00:00+00:00",
            "last_tick_status": "ok", "last_tick_error": None,
            "last_result_summary": {"detected": 0, "resolved": 0, "skipped": 0, "errors": 0},
            "last_drifts_detected": [], "last_drifts_resolved": [],
            "consecutive_failures": 0, "interval_s": 30,
        }
        # Task that's still running.
        task = MagicMock()
        task.done.return_value = False
        bot._share_drift_task = task

        with patch.object(tb_router, "_trading_bot", bot):
            with patch("routers.ib._pushed_ib_data", {"positions": {}}):
                with patch("routers.ib.is_pusher_connected", return_value=True):
                    result = await tb_router.share_drift_status(symbols=None)

        assert result["success"] is True
        assert result["loop"]["alive"] is True
        assert result["loop"]["task_exception"] is None
        assert result["loop"]["feature_flag"] is True
        assert result["diag"]["tick_count"] == 12
        assert result["pusher_connected"] is True

    @pytest.mark.asyncio
    async def test_drift_detected_when_ib_exceeds_bot(self):
        """93sh FDX + 338sh UPS drift case — endpoint flags both."""
        from routers import trading_bot as tb_router
        from services.trading_bot_service import TradeDirection

        # Bot tracks 276 FDX long + 885 UPS long.
        fdx_t = MagicMock(symbol="FDX", remaining_shares=276, direction=TradeDirection.LONG)
        ups_t = MagicMock(symbol="UPS", remaining_shares=885, direction=TradeDirection.LONG)
        bot = MagicMock()
        bot._open_trades = {"t-fdx": fdx_t, "t-ups": ups_t}
        bot._share_drift_diag = {"tick_count": 0, "last_tick_at": None, "last_tick_status": "never_ran"}
        task = MagicMock(); task.done.return_value = False
        bot._share_drift_task = task

        ib_positions = {
            "FDX": {"position": 369},  # +93 drift
            "UPS": {"position": 1223},  # +338 drift
        }
        with patch.object(tb_router, "_trading_bot", bot):
            with patch("routers.ib._pushed_ib_data", {"positions": ib_positions}):
                with patch("routers.ib.is_pusher_connected", return_value=True):
                    result = await tb_router.share_drift_status(symbols=None)

        rows = {r["symbol"]: r for r in result["per_symbol"]}
        assert rows["FDX"]["bot_qty_signed"] == 276
        assert rows["FDX"]["ib_qty_signed"] == 369
        assert rows["FDX"]["drift"] == 93
        assert rows["FDX"]["would_act"] is True
        assert rows["FDX"]["verdict"] == "drift_detected"
        assert rows["UPS"]["drift"] == 338
        assert rows["UPS"]["would_act"] is True
        assert result["summary"]["drift_detected_count"] == 2
        assert set(result["summary"]["drift_symbols"]) == {"FDX", "UPS"}

    @pytest.mark.asyncio
    async def test_in_sync_when_ib_matches_bot(self):
        from routers import trading_bot as tb_router
        from services.trading_bot_service import TradeDirection

        t = MagicMock(symbol="ADBE", remaining_shares=15, direction=TradeDirection.SHORT)
        bot = MagicMock()
        bot._open_trades = {"t-1": t}
        bot._share_drift_diag = {"tick_count": 0, "last_tick_at": None, "last_tick_status": "never_ran"}
        task = MagicMock(); task.done.return_value = False
        bot._share_drift_task = task

        ib_positions = {"ADBE": {"position": -15}}  # bot tracks 15 short = -15 signed
        with patch.object(tb_router, "_trading_bot", bot):
            with patch("routers.ib._pushed_ib_data", {"positions": ib_positions}):
                with patch("routers.ib.is_pusher_connected", return_value=True):
                    result = await tb_router.share_drift_status(symbols=None)

        rows = {r["symbol"]: r for r in result["per_symbol"]}
        assert rows["ADBE"]["bot_qty_signed"] == -15
        assert rows["ADBE"]["ib_qty_signed"] == -15
        assert rows["ADBE"]["drift"] == 0
        assert rows["ADBE"]["would_act"] is False
        assert rows["ADBE"]["verdict"] == "in_sync"

    @pytest.mark.asyncio
    async def test_symbol_filter_narrows_response(self):
        from routers import trading_bot as tb_router
        from services.trading_bot_service import TradeDirection

        bot = MagicMock()
        bot._open_trades = {
            "t-1": MagicMock(symbol="FDX", remaining_shares=276, direction=TradeDirection.LONG),
            "t-2": MagicMock(symbol="UPS", remaining_shares=885, direction=TradeDirection.LONG),
            "t-3": MagicMock(symbol="ADBE", remaining_shares=15, direction=TradeDirection.SHORT),
        }
        bot._share_drift_diag = {"tick_count": 0, "last_tick_at": None, "last_tick_status": "never_ran"}
        task = MagicMock(); task.done.return_value = False
        bot._share_drift_task = task

        with patch.object(tb_router, "_trading_bot", bot):
            with patch("routers.ib._pushed_ib_data", {"positions": {}}):
                with patch("routers.ib.is_pusher_connected", return_value=True):
                    result = await tb_router.share_drift_status(symbols="FDX,UPS")

        syms = {r["symbol"] for r in result["per_symbol"]}
        assert syms == {"FDX", "UPS"}
        assert "ADBE" not in syms
        assert result["symbol_filter"] == ["FDX", "UPS"]

    @pytest.mark.asyncio
    async def test_loop_dead_surfaces_alive_false_with_exception(self):
        """If the drift loop crashed, endpoint flags it loud."""
        from routers import trading_bot as tb_router

        bot = MagicMock()
        bot._open_trades = {}
        bot._share_drift_diag = {
            "tick_count": 4, "last_tick_at": "2026-05-06T19:50:00+00:00",
            "last_tick_status": "exception", "last_tick_error": "RuntimeError: boom",
            "consecutive_failures": 5,
        }
        task = MagicMock()
        task.done.return_value = True
        task.exception.return_value = RuntimeError("boom")
        bot._share_drift_task = task

        with patch.object(tb_router, "_trading_bot", bot):
            with patch("routers.ib._pushed_ib_data", {"positions": {}}):
                with patch("routers.ib.is_pusher_connected", return_value=True):
                    result = await tb_router.share_drift_status(symbols=None)

        assert result["loop"]["alive"] is False
        assert "boom" in (result["loop"]["task_exception"] or "")
        assert result["diag"]["consecutive_failures"] == 5

    @pytest.mark.asyncio
    async def test_includes_orphan_ib_symbols_not_tracked_by_bot(self):
        """Symbols in IB but not in bot._open_trades show drift = ib_qty - 0."""
        from routers import trading_bot as tb_router

        bot = MagicMock()
        bot._open_trades = {}
        bot._share_drift_diag = {"tick_count": 0, "last_tick_at": None, "last_tick_status": "never_ran"}
        task = MagicMock(); task.done.return_value = False
        bot._share_drift_task = task

        with patch.object(tb_router, "_trading_bot", bot):
            with patch("routers.ib._pushed_ib_data", {"positions": {"GOOG": {"position": 50}}}):
                with patch("routers.ib.is_pusher_connected", return_value=True):
                    result = await tb_router.share_drift_status(symbols=None)

        rows = {r["symbol"]: r for r in result["per_symbol"]}
        assert rows["GOOG"]["bot_qty_signed"] == 0
        assert rows["GOOG"]["ib_qty_signed"] == 50
        assert rows["GOOG"]["drift"] == 50
        assert rows["GOOG"]["would_act"] is True
