"""
v19.31.7 (2026-05-04) — regression pin for the CLOSE TODAY = 0 bug +
realized PnL surfacing on /api/sentcom/positions.

The bugs:
  1. HUD's CLOSE TODAY tile read 0 even when the bot demonstrably
     closed positions today. Root cause: /api/sentcom/positions
     returned only OPEN positions, but the HUD filtered
     `status === 'closed'` against THAT array, so it could never
     find anything.
  2. `total_pnl` was unrealized-only (sum of pnl across OPEN
     positions). Operator wanted realized PnL surfaced too — a
     trade that closed for $200 profit was never reflected in the
     dashboard's day-PnL number.

The fix:
  /api/sentcom/positions now also returns:
    - closed_today: [...] — bot_trades with status=closed AND
      closed_at >= today's 00:00 ET. Each row carries
      symbol/direction/realized_pnl/r_multiple/closed_at/etc.
    - closed_today_count, wins_today, losses_today
    - total_realized_pnl: sum of realized_pnl across closed_today
    - total_unrealized_pnl: explicit alias of legacy total_pnl
    - total_pnl_today: realized + unrealized (operator's day-PnL)
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ─── Fake Mongo collection that supports the closed_today query ─────


class _FakeColl:
    def __init__(self, docs: List[dict] | None = None):
        self.docs = list(docs or [])

    def _matches(self, doc, query):
        for k, v in query.items():
            if k == "$or":
                if not any(self._matches(doc, sub) for sub in v):
                    return False
                continue
            if k == "$and":
                if not all(self._matches(doc, sub) for sub in v):
                    return False
                continue
            actual = doc.get(k)
            if isinstance(v, dict):
                if "$gte" in v and not (actual is not None and actual >= v["$gte"]):
                    return False
                if "$lte" in v and not (actual is not None and actual <= v["$lte"]):
                    return False
            elif v is None:
                if actual is not None:
                    return False
            else:
                if actual != v:
                    return False
        return True

    def find(self, query=None, projection=None, sort=None, limit=None):
        rows = [d for d in self.docs if (query is None or self._matches(d, query))]
        if sort:
            for k, direction in reversed(sort):
                rows.sort(key=lambda r: r.get(k) or "", reverse=direction == -1)
        if limit:
            rows = rows[:limit]
        return iter(rows)


class _FakeDB:
    def __init__(self):
        self.bot_trades = _FakeColl()

    def __getitem__(self, name):
        return getattr(self, name)


def _make_closed_trade(trade_id, symbol, direction="long", realized_pnl=100,
                       hours_ago=2, close_reason="target_hit",
                       r_multiple=2.0):
    closed_at = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {
        "id": trade_id,
        "symbol": symbol,
        "direction": direction,
        "shares": 100,
        "fill_price": 50.0,
        "exit_price": 51.0 if realized_pnl > 0 else 49.0,
        "status": "closed",
        "closed_at": closed_at,
        "executed_at": closed_at,
        "realized_pnl": realized_pnl,
        "r_multiple": r_multiple,
        "close_reason": close_reason,
        "setup_type": "vwap_bounce_long",
    }


# ─── /positions tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_positions_endpoint_returns_closed_today_array():
    """v19.31.7 — closed_today must surface in the response."""
    from routers import sentcom as sentcom_router

    fake_db = _FakeDB()
    fake_db.bot_trades.docs = [
        _make_closed_trade("t1", "LITE", "short", realized_pnl=112.66),
        _make_closed_trade("t2", "AAPL", "long", realized_pnl=-50.0),
        # A row from yesterday — must NOT count
        _make_closed_trade("yest", "MSFT", realized_pnl=999, hours_ago=30),
    ]
    fake_service = MagicMock()
    fake_service.get_our_positions = AsyncMock(return_value=[])

    with patch.object(sentcom_router, "_get_service", return_value=fake_service):
        with patch.object(sentcom_router, "logger"):
            with patch.dict(sys.modules, {
                "server": MagicMock(db=fake_db),
            }):
                res = await sentcom_router.get_positions()

    assert res["success"] is True
    assert res["closed_today_count"] == 2  # MSFT excluded by the cutoff
    syms = [c["symbol"] for c in res["closed_today"]]
    assert "LITE" in syms and "AAPL" in syms
    assert "MSFT" not in syms
    assert res["wins_today"] == 1
    assert res["losses_today"] == 1
    assert res["total_realized_pnl"] == round(112.66 - 50.0, 2)


@pytest.mark.asyncio
async def test_positions_endpoint_total_pnl_today_is_realized_plus_unrealized():
    """v19.31.7 — total_pnl_today must equal realized + unrealized."""
    from routers import sentcom as sentcom_router

    fake_db = _FakeDB()
    fake_db.bot_trades.docs = [
        _make_closed_trade("t1", "X", realized_pnl=200),
    ]
    fake_service = MagicMock()
    # Open position with $50 unrealized
    fake_service.get_our_positions = AsyncMock(return_value=[
        {"symbol": "OPEN", "pnl": 50.0, "market_value": 5000, "cost_basis": 4950,
         "today_change": 0, "source": "bot"},
    ])

    with patch.object(sentcom_router, "_get_service", return_value=fake_service):
        with patch.object(sentcom_router, "logger"):
            with patch.dict(sys.modules, {"server": MagicMock(db=fake_db)}):
                res = await sentcom_router.get_positions()

    assert res["total_unrealized_pnl"] == 50.0
    assert res["total_realized_pnl"] == 200.0
    assert res["total_pnl_today"] == 250.0


@pytest.mark.asyncio
async def test_positions_endpoint_legacy_total_pnl_still_unrealized_only():
    """Back-compat: existing consumers reading total_pnl get unrealized
    (same as before v19.31.7) so nothing breaks."""
    from routers import sentcom as sentcom_router

    fake_db = _FakeDB()
    fake_db.bot_trades.docs = [_make_closed_trade("t1", "X", realized_pnl=999)]
    fake_service = MagicMock()
    fake_service.get_our_positions = AsyncMock(return_value=[
        {"symbol": "OPEN", "pnl": 50, "market_value": 0, "cost_basis": 0,
         "today_change": 0, "source": "bot"},
    ])

    with patch.object(sentcom_router, "_get_service", return_value=fake_service):
        with patch.object(sentcom_router, "logger"):
            with patch.dict(sys.modules, {"server": MagicMock(db=fake_db)}):
                res = await sentcom_router.get_positions()

    # Legacy total_pnl == unrealized (NOT realized + unrealized)
    assert res["total_pnl"] == 50.0


@pytest.mark.asyncio
async def test_closed_today_uses_executed_at_when_closed_at_missing():
    """Legacy rows without closed_at fall back to executed_at."""
    from routers import sentcom as sentcom_router

    fake_db = _FakeDB()
    legacy = _make_closed_trade("legacy", "OLD", realized_pnl=10)
    legacy["closed_at"] = None  # legacy row
    fake_db.bot_trades.docs = [legacy]
    fake_service = MagicMock()
    fake_service.get_our_positions = AsyncMock(return_value=[])

    with patch.object(sentcom_router, "_get_service", return_value=fake_service):
        with patch.object(sentcom_router, "logger"):
            with patch.dict(sys.modules, {"server": MagicMock(db=fake_db)}):
                res = await sentcom_router.get_positions()

    assert res["closed_today_count"] == 1
    assert res["closed_today"][0]["symbol"] == "OLD"


@pytest.mark.asyncio
async def test_closed_today_payload_has_required_fields():
    """Each closed_today row must have the exact shape the HUD needs."""
    from routers import sentcom as sentcom_router

    fake_db = _FakeDB()
    fake_db.bot_trades.docs = [_make_closed_trade("t1", "LITE", "short", realized_pnl=112.66)]
    fake_service = MagicMock()
    fake_service.get_our_positions = AsyncMock(return_value=[])

    with patch.object(sentcom_router, "_get_service", return_value=fake_service):
        with patch.object(sentcom_router, "logger"):
            with patch.dict(sys.modules, {"server": MagicMock(db=fake_db)}):
                res = await sentcom_router.get_positions()

    c = res["closed_today"][0]
    for required in ("symbol", "direction", "shares", "entry_price", "exit_price",
                     "realized_pnl", "r_multiple", "executed_at", "closed_at",
                     "close_reason", "setup_type", "trade_id"):
        assert required in c, f"closed_today row missing {required}"


@pytest.mark.asyncio
async def test_realized_pnl_failure_does_not_break_positions():
    """If the closed_today lookup blows up, the endpoint should still
    serve open positions + zero realized fields (operator must NEVER
    lose the live PnL display because of a closed-trade query bug)."""
    from routers import sentcom as sentcom_router

    fake_db = _FakeDB()
    # Make the find() raise
    def _boom(*args, **kwargs):
        raise RuntimeError("simulated mongo failure")
    fake_db.bot_trades.find = _boom
    fake_service = MagicMock()
    fake_service.get_our_positions = AsyncMock(return_value=[
        {"symbol": "OPEN", "pnl": 75, "market_value": 0, "cost_basis": 0,
         "today_change": 0, "source": "bot"},
    ])

    with patch.object(sentcom_router, "_get_service", return_value=fake_service):
        with patch.object(sentcom_router, "logger"):
            with patch.dict(sys.modules, {"server": MagicMock(db=fake_db)}):
                res = await sentcom_router.get_positions()

    # Endpoint succeeded
    assert res["success"] is True
    # Open positions still present
    assert res["count"] == 1
    assert res["total_unrealized_pnl"] == 75.0
    # Realized fell back to 0 — and didn't crash
    assert res["total_realized_pnl"] == 0.0
    assert res["closed_today"] == []
