"""
v19.31.12 (2026-05-04) — regression pin for the realized-PnL recalc
endpoint + sweep-time PnL claim.

Two interlocked fixes:
  (a) Going-forward: when a phantom sweep (v19.27 leftover or v19.31
      OCA-closed) marks a trade closed, claim the IB realizedPNL onto
      bot.realized_pnl. Pre-fix, every swept trade ended at $0
      realized → Trade Forensics flagged them all as drift.
  (b) Retroactive: POST /api/diagnostics/recalc-realized-pnl/{symbol}
      lets the operator backfill the bot's realized_pnl from IB on
      already-closed rows that have realized_pnl == 0.

These tests pin the endpoint contract (apportion math, idempotence,
"already populated" path, "no IB activity" path).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ─── Fake collection that supports update_one + find ─────────────


class _FakeColl:
    def __init__(self, docs: List[dict] | None = None):
        self.docs = list(docs or [])
        self.updates: List[Dict[str, Any]] = []

    def _matches(self, doc, query):
        if not query:
            return True
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
                if "$exists" in v:
                    has = k in doc
                    if has != v["$exists"]:
                        return False
            elif v is None:
                if actual is not None:
                    return False
            else:
                if actual != v:
                    return False
        return True

    def find(self, query=None, projection=None, sort=None, limit=None):
        rows = [d for d in self.docs if self._matches(d, query)]
        if sort:
            for k, direction in reversed(sort):
                rows.sort(key=lambda r: r.get(k) or "", reverse=direction == -1)
        if limit:
            rows = rows[:limit]
        return iter(rows)

    def find_one(self, query=None, projection=None):
        rows = list(self.find(query, projection))
        return rows[0] if rows else None

    def update_one(self, query, update):
        for d in self.docs:
            if self._matches(d, query):
                for k, v in update.get("$set", {}).items():
                    d[k] = v
                self.updates.append({"query": query, "update": update})
                return type("_R", (), {"matched_count": 1, "modified_count": 1})
        return type("_R", (), {"matched_count": 0, "modified_count": 0})


class _FakeDB:
    def __init__(self):
        self.bot_trades = _FakeColl()
        self.ib_live_snapshot = _FakeColl()

    def __getitem__(self, name):
        return getattr(self, name)


def _trade(id_, symbol, shares=100, realized_pnl=0, status="closed",
           hours_ago=2):
    base = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {
        "id": id_,
        "symbol": symbol,
        "direction": "long",
        "shares": shares,
        "status": status,
        "executed_at": base,
        "closed_at": base if status == "closed" else None,
        "realized_pnl": realized_pnl,
    }


@pytest.fixture
def patch_db():
    from routers import diagnostics as diag
    fake = _FakeDB()
    original = diag._db
    diag._db = fake
    yield fake
    diag._db = original


# ─── Recalc endpoint tests ────────────────────────────────────────


@pytest.mark.asyncio
async def test_recalc_claims_ib_realized_when_bot_is_zero(patch_db):
    """The exact LITE scenario — bot has 1 closed row at $0, IB shows
    $112.66 realized. Endpoint should stamp $112.66 onto the row."""
    from routers.diagnostics import recalc_realized_pnl
    patch_db.bot_trades.docs = [_trade("t1", "LITE", shares=62, realized_pnl=0)]
    patch_db.ib_live_snapshot.docs = [{
        "_id": "current",
        "positions": [{"symbol": "LITE", "position": 0, "realizedPNL": 112.66}],
    }]

    res = await recalc_realized_pnl("LITE", days=7)

    assert res["success"] is True
    assert res["ib_realized_pnl"] == 112.66
    assert res["claimed"] == 112.66
    assert len(res["rows_updated"]) == 1
    assert res["rows_updated"][0]["claimed_pnl"] == 112.66
    # Row in fake DB updated in place
    assert patch_db.bot_trades.docs[0]["realized_pnl"] == 112.66
    assert patch_db.bot_trades.docs[0].get("realized_pnl_recalc_source") == "ib_snapshot_v19_31_12"


@pytest.mark.asyncio
async def test_recalc_apportions_across_multiple_rows_by_shares(patch_db):
    """3 closed rows totalling 300 shares, IB realized $300 — each row
    gets a fair share by share count."""
    from routers.diagnostics import recalc_realized_pnl
    patch_db.bot_trades.docs = [
        _trade("t1", "X", shares=100, realized_pnl=0),
        _trade("t2", "X", shares=200, realized_pnl=0),
    ]
    patch_db.ib_live_snapshot.docs = [{
        "_id": "current",
        "positions": [{"symbol": "X", "position": 0, "realizedPNL": 300.0}],
    }]
    res = await recalc_realized_pnl("X", days=7)
    by_id = {u["trade_id"]: u for u in res["rows_updated"]}
    # 100/300 share = $100, 200/300 share = $200
    assert by_id["t1"]["claimed_pnl"] == 100.00
    assert by_id["t2"]["claimed_pnl"] == 200.00
    assert res["claimed"] == 300.00


@pytest.mark.asyncio
async def test_recalc_skips_rows_already_populated(patch_db):
    """Don't overwrite existing realized_pnl. Idempotent."""
    from routers.diagnostics import recalc_realized_pnl
    patch_db.bot_trades.docs = [
        _trade("t1", "X", realized_pnl=50),  # already populated
        _trade("t2", "X", realized_pnl=0),   # zero, claim
    ]
    patch_db.ib_live_snapshot.docs = [{
        "_id": "current",
        "positions": [{"symbol": "X", "position": 0, "realizedPNL": 100.0}],
    }]
    res = await recalc_realized_pnl("X", days=7)
    # Only t2 should have been updated
    assert len(res["rows_updated"]) == 1
    assert res["rows_updated"][0]["trade_id"] == "t2"
    # t1 unchanged
    by_id = {d["id"]: d for d in patch_db.bot_trades.docs}
    assert by_id["t1"]["realized_pnl"] == 50


@pytest.mark.asyncio
async def test_recalc_idempotent_running_twice(patch_db):
    """Running recalc twice must NOT double-claim — second run should
    be a no-op since realized_pnl is no longer 0."""
    from routers.diagnostics import recalc_realized_pnl
    patch_db.bot_trades.docs = [_trade("t1", "X", realized_pnl=0, shares=100)]
    patch_db.ib_live_snapshot.docs = [{
        "_id": "current",
        "positions": [{"symbol": "X", "position": 0, "realizedPNL": 50.0}],
    }]
    r1 = await recalc_realized_pnl("X", days=7)
    assert r1["claimed"] == 50.00
    # Run again
    r2 = await recalc_realized_pnl("X", days=7)
    assert r2["claimed"] == 0.00
    assert len(r2["rows_updated"]) == 0
    # Row still at $50, not $100
    assert patch_db.bot_trades.docs[0]["realized_pnl"] == 50


@pytest.mark.asyncio
async def test_recalc_no_ib_activity_returns_note(patch_db):
    """IB realizedPNL = 0 → nothing to claim."""
    from routers.diagnostics import recalc_realized_pnl
    patch_db.bot_trades.docs = [_trade("t1", "X", realized_pnl=0)]
    patch_db.ib_live_snapshot.docs = [{
        "_id": "current",
        "positions": [{"symbol": "X", "position": 0, "realizedPNL": 0}],
    }]
    res = await recalc_realized_pnl("X", days=7)
    assert res["claimed"] == 0
    assert res["rows_updated"] == []
    assert "no realized pnl" in res.get("note", "").lower()


@pytest.mark.asyncio
async def test_recalc_negative_ib_realized_propagates(patch_db):
    """Loser trade — IB realized −$200 → bot row stamped −$200."""
    from routers.diagnostics import recalc_realized_pnl
    patch_db.bot_trades.docs = [_trade("t1", "X", realized_pnl=0)]
    patch_db.ib_live_snapshot.docs = [{
        "_id": "current",
        "positions": [{"symbol": "X", "position": 0, "realizedPNL": -200.0}],
    }]
    res = await recalc_realized_pnl("X", days=7)
    assert res["claimed"] == -200.00
    assert patch_db.bot_trades.docs[0]["realized_pnl"] == -200.00


@pytest.mark.asyncio
async def test_recalc_only_touches_closed_rows(patch_db):
    """Open rows (status != closed) must NOT be touched."""
    from routers.diagnostics import recalc_realized_pnl
    patch_db.bot_trades.docs = [
        _trade("open1", "X", status="open", realized_pnl=0),
        _trade("closed1", "X", status="closed", realized_pnl=0),
    ]
    patch_db.ib_live_snapshot.docs = [{
        "_id": "current",
        "positions": [{"symbol": "X", "position": 0, "realizedPNL": 100.0}],
    }]
    res = await recalc_realized_pnl("X", days=7)
    # Only the closed row was claimed
    assert len(res["rows_updated"]) == 1
    assert res["rows_updated"][0]["trade_id"] == "closed1"
    by_id = {d["id"]: d for d in patch_db.bot_trades.docs}
    assert by_id["open1"]["realized_pnl"] == 0
    assert by_id["closed1"]["realized_pnl"] == 100.00


@pytest.mark.asyncio
async def test_recalc_rejects_empty_symbol(patch_db):
    from routers.diagnostics import recalc_realized_pnl
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        await recalc_realized_pnl("", days=7)
    assert ei.value.status_code == 400
