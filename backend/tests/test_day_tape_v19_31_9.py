"""
v19.31.9 (2026-05-04) — regression pin for /api/diagnostics/day-tape
and /day-tape.csv.

These tests pin:
  - Multi-day cutoff (rows older than the window are excluded).
  - Direction + setup filters narrow the result set.
  - Summary aggregation: count / wins / losses / scratches,
    win_rate, gross_pnl, avg_r, biggest_winner / biggest_loser,
    by_setup, by_direction.
  - CSV export shape + header order pinned (operator scripts
    parse it).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch, MagicMock

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ─── Fake collection that supports the day-tape query ───────────────


class _FakeColl:
    def __init__(self, docs: List[dict] | None = None):
        self.docs = list(docs or [])

    def _matches(self, doc, query):
        for k, v in query.items():
            if k == "$or":
                if not any(self._matches(doc, sub) for sub in v):
                    return False
                continue
            actual = doc.get(k)
            if isinstance(v, dict):
                if "$gte" in v and not (actual is not None and actual >= v["$gte"]):
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


def _trade(trade_id, symbol, direction="long", realized_pnl=100,
           hours_ago=2, setup_type="vwap_bounce_long",
           r_multiple=2.0, close_reason="target_hit"):
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
        "setup_type": setup_type,
        "setup_variant": "v1",
        "trade_style": "intraday",
    }


# ─── /day-tape endpoint tests ───────────────────────────────────────


@pytest.fixture
def patch_db():
    """Patch routers.diagnostics._db to a fake DB with bot_trades."""
    from routers import diagnostics as diag_router
    fake_coll = _FakeColl()
    fake_db = MagicMock()
    fake_db.__getitem__ = MagicMock(side_effect=lambda k: fake_coll if k == "bot_trades" else MagicMock())
    original = diag_router._db
    diag_router._db = fake_db
    yield fake_coll
    diag_router._db = original


@pytest.mark.asyncio
async def test_day_tape_basic_today_only(patch_db):
    from routers.diagnostics import get_day_tape
    patch_db.docs = [
        _trade("t1", "LITE", "short", realized_pnl=200),
        _trade("t2", "AAPL", "long",  realized_pnl=-50),
        # Outside 1-day window
        _trade("yest", "MSFT", realized_pnl=999, hours_ago=30),
    ]
    res = await get_day_tape(days=1, direction=None, setup=None)
    assert res["success"] is True
    assert res["summary"]["count"] == 2
    syms = [r["symbol"] for r in res["rows"]]
    assert "MSFT" not in syms
    assert res["summary"]["wins"] == 1
    assert res["summary"]["losses"] == 1
    assert res["summary"]["gross_pnl"] == 150.0
    assert res["summary"]["win_rate"] == 50.0


@pytest.mark.asyncio
async def test_day_tape_5day_window_includes_older(patch_db):
    from routers.diagnostics import get_day_tape
    patch_db.docs = [
        _trade("t1", "A", realized_pnl=100, hours_ago=1),
        _trade("t2", "B", realized_pnl=200, hours_ago=80),  # 3.3 days
        _trade("t3", "C", realized_pnl=300, hours_ago=200),  # 8.3 days, OUT
    ]
    res = await get_day_tape(days=5, direction=None, setup=None)
    assert res["summary"]["count"] == 2
    syms = sorted(r["symbol"] for r in res["rows"])
    assert syms == ["A", "B"]


@pytest.mark.asyncio
async def test_day_tape_direction_filter(patch_db):
    from routers.diagnostics import get_day_tape
    patch_db.docs = [
        _trade("t1", "L1", direction="long",  realized_pnl=100),
        _trade("t2", "L2", direction="long",  realized_pnl=-50),
        _trade("t3", "S1", direction="short", realized_pnl=300),
    ]
    res = await get_day_tape(days=1, direction="long", setup=None)
    assert res["summary"]["count"] == 2
    assert all(r["direction"] == "long" for r in res["rows"])


@pytest.mark.asyncio
async def test_day_tape_biggest_winner_loser(patch_db):
    from routers.diagnostics import get_day_tape
    patch_db.docs = [
        _trade("t1", "BIG_W", realized_pnl=500),
        _trade("t2", "SMALL_W", realized_pnl=50),
        _trade("t3", "BIG_L", realized_pnl=-300),
        _trade("t4", "SMALL_L", realized_pnl=-20),
    ]
    res = await get_day_tape(days=1, direction=None, setup=None)
    assert res["summary"]["biggest_winner"]["symbol"] == "BIG_W"
    assert res["summary"]["biggest_winner"]["realized_pnl"] == 500.0
    assert res["summary"]["biggest_loser"]["symbol"] == "BIG_L"
    assert res["summary"]["biggest_loser"]["realized_pnl"] == -300.0


@pytest.mark.asyncio
async def test_day_tape_by_setup_aggregation(patch_db):
    from routers.diagnostics import get_day_tape
    patch_db.docs = [
        _trade("t1", "A", realized_pnl=100, setup_type="vwap_bounce_long"),
        _trade("t2", "B", realized_pnl=200, setup_type="vwap_bounce_long"),
        _trade("t3", "C", realized_pnl=-100, setup_type="vwap_bounce_long"),
        _trade("t4", "D", realized_pnl=50,   setup_type="abcd_short"),
    ]
    res = await get_day_tape(days=1, direction=None, setup=None)
    by_setup = res["summary"]["by_setup"]
    assert by_setup["vwap_bounce_long"]["count"] == 3
    assert by_setup["vwap_bounce_long"]["gross_pnl"] == 200.0
    assert by_setup["vwap_bounce_long"]["wins"] == 2
    assert by_setup["vwap_bounce_long"]["win_rate"] == round(100 * 2 / 3, 1)
    assert by_setup["abcd_short"]["count"] == 1


@pytest.mark.asyncio
async def test_day_tape_csv_pinned_header_order(patch_db):
    """Operator scripts depend on column order. Pin it explicitly.

    v19.31.13 (2026-05-04): added trade_type + account_id_at_fill so
    the operator can spot paper vs live rows in their journaling tools.
    They appear after trade_style and before the audit columns
    (executed_at, trade_id) so existing column slicers that look at
    "first N columns up to setup data" stay stable.
    """
    from routers.diagnostics import get_day_tape_csv
    patch_db.docs = [_trade("t1", "AAPL", realized_pnl=100)]
    csv_text = await get_day_tape_csv(days=1, direction=None, setup=None)
    first_line = csv_text.split("\n")[0]
    expected_cols = (
        "closed_at,symbol,direction,shares,entry_price,exit_price,"
        "realized_pnl,r_multiple,close_reason,setup_type,setup_variant,"
        "trade_style,trade_type,account_id_at_fill,executed_at,trade_id"
    )
    assert first_line == expected_cols


@pytest.mark.asyncio
async def test_day_tape_csv_quotes_commas_in_strings(patch_db):
    from routers.diagnostics import get_day_tape_csv
    bad = _trade("t1", "AAPL", realized_pnl=100)
    bad["close_reason"] = "manual, weird,reason"
    patch_db.docs = [bad]
    csv_text = await get_day_tape_csv(days=1, direction=None, setup=None)
    # The reason should be quoted because it contains commas
    assert '"manual, weird,reason"' in csv_text


@pytest.mark.asyncio
async def test_day_tape_handles_missing_closed_at_via_executed_at(patch_db):
    from routers.diagnostics import get_day_tape
    legacy = _trade("legacy", "X", realized_pnl=10)
    legacy["closed_at"] = None
    patch_db.docs = [legacy]
    res = await get_day_tape(days=1, direction=None, setup=None)
    assert res["summary"]["count"] == 1
    assert res["rows"][0]["symbol"] == "X"


@pytest.mark.asyncio
async def test_day_tape_avg_r_calculation(patch_db):
    from routers.diagnostics import get_day_tape
    patch_db.docs = [
        _trade("t1", "A", realized_pnl=100, r_multiple=2.0),
        _trade("t2", "B", realized_pnl=-50, r_multiple=-0.5),
        _trade("t3", "C", realized_pnl=100, r_multiple=1.5),
    ]
    res = await get_day_tape(days=1, direction=None, setup=None)
    # Average of 2.0, -0.5, 1.5 = 1.0
    assert res["summary"]["avg_r"] == 1.0
