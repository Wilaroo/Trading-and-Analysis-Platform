"""
test_unmatched_short_closes_v19_34_16.py — extends the v19.34.4 audit
tape suite with the new `find_unmatched_short_activity` helper plus
unit-tests the runtime `find_unmatched_short_closes` service.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ─── Audit-script: find_unmatched_short_activity ───────────────────

def _build_audit(*, sym, short_legs_count=0, residual=0, fill_count=2,
                bought_qty=0, sold_qty=0):
    from scripts.audit_ib_fill_tape import SymbolAudit, FifoTrade
    a = SymbolAudit(symbol=sym)
    a.fill_count = fill_count
    a.bought_qty = bought_qty
    a.sold_qty = sold_qty
    a.open_residual_qty = residual
    a.closed_legs = [
        FifoTrade(direction="SHORT", qty=100, open_price=50.0, close_price=49.0,
                  open_time="10:00 AM", close_time="10:30 AM", pnl=100.0)
        for _ in range(short_legs_count)
    ]
    return a


class TestUnmatchedShortActivity:

    def test_no_findings_when_bot_has_short_row(self):
        from scripts.audit_ib_fill_tape import find_unmatched_short_activity
        a = _build_audit(sym="MELI", short_legs_count=1, sold_qty=100, bought_qty=100)
        bts = {"MELI": {"row_count": 1, "total_qty": 100, "directions": ["short"]}}
        findings = find_unmatched_short_activity({"MELI": a}, bts)
        assert findings == []

    def test_flags_short_legs_when_bot_has_only_long_rows(self):
        from scripts.audit_ib_fill_tape import find_unmatched_short_activity
        a = _build_audit(sym="MELI", short_legs_count=2, sold_qty=200, bought_qty=200)
        bts = {"MELI": {"row_count": 5, "total_qty": 500, "directions": ["long"]}}
        findings = find_unmatched_short_activity({"MELI": a}, bts)
        assert len(findings) == 1
        f = findings[0]
        assert f["symbol"] == "MELI"
        assert f["kind"] == "unmatched_short_round_trip"
        assert f["short_leg_count"] == 2
        assert "v19.34.15a" in f["detail"]

    def test_flags_open_short_residual_no_bot_row(self):
        from scripts.audit_ib_fill_tape import find_unmatched_short_activity
        a = _build_audit(sym="UPS", residual=-50, sold_qty=50)
        bts = {"UPS": {"row_count": 1, "total_qty": 425, "directions": ["long"]}}
        findings = find_unmatched_short_activity({"UPS": a}, bts)
        kinds = {f["kind"] for f in findings}
        assert "unmatched_open_short" in kinds

    def test_no_bot_data_marks_short_legs_as_uncheckable(self):
        from scripts.audit_ib_fill_tape import find_unmatched_short_activity
        a = _build_audit(sym="X", short_legs_count=1, sold_qty=100, bought_qty=100)
        findings = find_unmatched_short_activity({"X": a}, bot_trades_summary=None)
        assert len(findings) == 1
        assert findings[0]["kind"] == "unmatched_short_round_trip_no_bot_data"

    def test_bot_directions_csv_string_supported(self):
        from scripts.audit_ib_fill_tape import find_unmatched_short_activity
        a = _build_audit(sym="MELI", short_legs_count=1, sold_qty=100, bought_qty=100)
        # Operator export sometimes ships directions as a CSV string.
        bts = {"MELI": {"row_count": 1, "total_qty": 100, "direction": "short"}}
        findings = find_unmatched_short_activity({"MELI": a}, bts)
        assert findings == []


# ─── Runtime service: find_unmatched_short_closes ─────────────────

class TestRuntimeServiceFifoWalk:

    def test_normalize_side_buy_variants(self):
        from services.unmatched_short_close_service import _normalize_side
        assert _normalize_side("BOT") == "BUY"
        assert _normalize_side("Bot") == "BUY"
        assert _normalize_side("BUY") == "BUY"

    def test_normalize_side_sell_variants(self):
        from services.unmatched_short_close_service import _normalize_side
        assert _normalize_side("SLD") == "SELL"
        assert _normalize_side("Sold") == "SELL"
        assert _normalize_side("SELL") == "SELL"
        assert _normalize_side("Sold Short") == "SELL"

    def test_fifo_walk_short_round_trip(self):
        from services.unmatched_short_close_service import _fifo_walk_short_legs
        execs = [
            {"symbol": "MELI", "side": "SLD", "shares": 100, "price": 1810.0, "time": "10:00"},
            {"symbol": "MELI", "side": "BOT", "shares": 100, "price": 1800.0, "time": "10:30"},
        ]
        legs = _fifo_walk_short_legs(execs)
        assert "MELI" in legs
        assert len(legs["MELI"]) == 1
        assert legs["MELI"][0]["qty"] == 100
        assert legs["MELI"][0]["pnl"] == 1000.0  # (1810 - 1800) * 100

    def test_fifo_walk_residual_short_flagged(self):
        from services.unmatched_short_close_service import _fifo_walk_short_legs
        execs = [{"symbol": "UPS", "side": "SLD", "shares": 100, "price": 50.0, "time": "10:00"}]
        legs = _fifo_walk_short_legs(execs)
        assert legs["UPS"][0]["kind"] == "open_residual_short"
        assert legs["UPS"][0]["qty"] == 100

    def test_fifo_walk_long_round_trip_not_flagged(self):
        from services.unmatched_short_close_service import _fifo_walk_short_legs
        execs = [
            {"symbol": "AAPL", "side": "BOT", "shares": 100, "price": 145.0, "time": "10:00"},
            {"symbol": "AAPL", "side": "SLD", "shares": 100, "price": 146.0, "time": "10:30"},
        ]
        legs = _fifo_walk_short_legs(execs)
        # No SHORT leg should appear (long round-trip).
        assert legs.get("AAPL", []) == []


class TestRuntimeServiceFindUnmatched:

    @pytest.mark.asyncio
    async def test_no_findings_when_no_executions(self):
        from services.unmatched_short_close_service import find_unmatched_short_closes
        db = MagicMock()
        db.__getitem__.return_value.find.return_value = iter([])
        result = await find_unmatched_short_closes(db, days=1)
        assert result["success"] is True
        assert result["findings"] == []
        assert result["summary"]["unmatched_count"] == 0

    @pytest.mark.asyncio
    async def test_flags_when_short_round_trip_but_no_bot_row(self):
        from services.unmatched_short_close_service import find_unmatched_short_closes
        execs = [
            {"symbol": "MELI", "side": "SLD", "shares": 100, "price": 1810.0, "time": "2026-05-06T10:00"},
            {"symbol": "MELI", "side": "BOT", "shares": 100, "price": 1800.0, "time": "2026-05-06T10:30"},
        ]
        db = MagicMock()
        # Two collection accesses: ib_executions + bot_trades.
        def _getitem(name):
            coll = MagicMock()
            if name == "ib_executions":
                coll.find.return_value = list(execs)
            else:  # bot_trades
                coll.find.return_value = []  # no short rows
            return coll
        db.__getitem__.side_effect = _getitem
        result = await find_unmatched_short_closes(db, days=1)
        assert result["success"] is True
        assert result["summary"]["unmatched_count"] == 1
        assert "MELI" in result["summary"]["symbols"]
        f = result["findings"][0]
        assert f["round_trip_count"] == 1
        assert f["realized_pnl"] == 1000.0

    @pytest.mark.asyncio
    async def test_no_flag_when_bot_short_row_exists(self):
        from services.unmatched_short_close_service import find_unmatched_short_closes
        execs = [
            {"symbol": "MELI", "side": "SLD", "shares": 100, "price": 1810.0, "time": "2026-05-06T10:00"},
            {"symbol": "MELI", "side": "BOT", "shares": 100, "price": 1800.0, "time": "2026-05-06T10:30"},
        ]
        db = MagicMock()
        def _getitem(name):
            coll = MagicMock()
            if name == "ib_executions":
                coll.find.return_value = list(execs)
            else:  # bot_trades — short row exists for MELI
                coll.find.return_value = [{"symbol": "MELI", "id": "t-1", "shares": 100}]
            return coll
        db.__getitem__.side_effect = _getitem
        result = await find_unmatched_short_closes(db, days=1)
        assert result["summary"]["unmatched_count"] == 0

    @pytest.mark.asyncio
    async def test_db_none_returns_error(self):
        from services.unmatched_short_close_service import find_unmatched_short_closes
        result = await find_unmatched_short_closes(None, days=1)
        assert result["success"] is False
        assert "database" in result["error"].lower()
