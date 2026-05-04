"""
v19.31 (2026-05-04) — regression pin for the IB-survival guard on
reset_bot_open_trades.py.

The bug:
  Operator's morning reset script blindly closed every status=open row
  in `bot_trades`. When IB still held positions overnight (yesterday's
  swings), the reset wiped the bot's tracking record but didn't touch
  IB. Result: 13 ORPHAN positions on this morning's dashboard.

The fix:
  Cross-check each `bot_trades` row against `ib_live_snapshot.current`.
  If `(symbol, direction)` is still in IB's pushed snapshot, SKIP that
  row. Pass `--force` to override.

These tests pin the partition logic on a fake Mongo.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ─── Fake Mongo ─────────────────────────────────────────────────────


class _FakeColl:
    def __init__(self, docs: List[dict] | None = None):
        self.docs = docs or []
        self.update_calls: List[Dict[str, Any]] = []
        self.insert_calls: List[Dict[str, Any]] = []

    def find(self, query=None, projection=None):
        # Naive matcher: only support our specific query shape.
        if not query:
            return list(self.docs)
        out = []
        for d in self.docs:
            if "status" in query and d.get("status") != query["status"]:
                continue
            if "symbol" in query:
                cond = query["symbol"]
                if isinstance(cond, dict) and "$in" in cond:
                    if d.get("symbol") not in cond["$in"]:
                        continue
                elif d.get("symbol") != cond:
                    continue
            out.append(d)
        return out

    def find_one(self, query=None, projection=None):
        out = self.find(query, projection)
        return out[0] if out else None

    def update_many(self, query, update):
        affected = 0
        for d in self.find(query):
            if "trade_id" in query:
                if d.get("trade_id") not in query["trade_id"].get("$in", []):
                    continue
            for k, v in update.get("$set", {}).items():
                d[k] = v
            affected += 1
        self.update_calls.append({"query": query, "update": update, "affected": affected})
        return type("_R", (), {"modified_count": affected})

    def insert_one(self, doc):
        self.insert_calls.append(doc)
        return type("_R", (), {"inserted_id": "fake-id"})

    def create_index(self, *args, **kwargs):
        return None


class _FakeDB:
    def __init__(self):
        self.bot_trades = _FakeColl()
        self.ib_live_snapshot = _FakeColl()
        self.bot_trades_reset_log = _FakeColl()

    def __getitem__(self, name):
        return getattr(self, name)


# ─── Tests ──────────────────────────────────────────────────────────


def _make_trade(trade_id, symbol, direction, shares=100, remaining=None):
    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "direction": direction,
        "shares": shares,
        "remaining_shares": remaining if remaining is not None else shares,
        "status": "open",
        "executed_at": datetime.now(timezone.utc).isoformat(),
    }


def test_skips_row_when_ib_still_holds_matching_position():
    """The exact morning-reset bug: bot_trades has APH long open, IB
    snapshot still holds APH 588 long → row must be SKIPPED."""
    from backend.scripts.reset_bot_open_trades import reset_open_trades

    db = _FakeDB()
    db.bot_trades.docs = [
        _make_trade("aph-1", "APH", "long", shares=588),
    ]
    db.ib_live_snapshot.docs = [{
        "_id": "current",
        "positions": [{"symbol": "APH", "position": 588.0}],
    }]

    result = reset_open_trades(db=db, dry_run=False, force=False)

    assert result["matched_count"] == 1
    assert result["safe_to_close_count"] == 0
    assert result["modified_count"] == 0
    assert len(result["skipped_ib_held"]) == 1
    skipped = result["skipped_ib_held"][0]
    assert skipped["symbol"] == "APH"
    assert skipped["direction"] == "long"
    # Row should still be open
    assert db.bot_trades.docs[0]["status"] == "open"


def test_closes_row_when_ib_does_not_hold():
    """Bot has stale row for symbol IB no longer holds → close it."""
    from backend.scripts.reset_bot_open_trades import reset_open_trades

    db = _FakeDB()
    db.bot_trades.docs = [
        _make_trade("stale-1", "STALE", "long", shares=100),
    ]
    db.ib_live_snapshot.docs = [{"_id": "current", "positions": []}]

    result = reset_open_trades(db=db, dry_run=False, force=False)

    assert result["matched_count"] == 1
    assert result["safe_to_close_count"] == 1
    assert result["modified_count"] == 1
    assert result["skipped_ib_held"] == []
    assert db.bot_trades.docs[0]["status"] == "closed"
    assert db.bot_trades.docs[0]["close_reason"] == "manual_pre_open_reset_v19_29"


def test_force_flag_bypasses_survival_guard():
    """--force skips the IB check and closes everything."""
    from backend.scripts.reset_bot_open_trades import reset_open_trades

    db = _FakeDB()
    db.bot_trades.docs = [
        _make_trade("aph-1", "APH", "long", shares=588),
    ]
    db.ib_live_snapshot.docs = [{
        "_id": "current",
        "positions": [{"symbol": "APH", "position": 588.0}],
    }]

    result = reset_open_trades(db=db, dry_run=False, force=True)

    assert result["force"] is True
    assert result["modified_count"] == 1
    assert db.bot_trades.docs[0]["status"] == "closed"


def test_aborts_when_snapshot_missing_and_not_forced():
    """Fail-closed when ib_live_snapshot.current is missing — operator
    must consciously pass --force to nuke without IB visibility."""
    from backend.scripts.reset_bot_open_trades import reset_open_trades

    db = _FakeDB()
    db.bot_trades.docs = [_make_trade("1", "ABC", "long")]
    # No ib_live_snapshot doc at all
    db.ib_live_snapshot.docs = []

    result = reset_open_trades(db=db, dry_run=False, force=False)

    assert result["aborted"] == "no_ib_snapshot"
    assert result["modified_count"] == 0
    assert db.bot_trades.docs[0]["status"] == "open"


def test_dry_run_with_snapshot_still_reports_skipped():
    """Dry-run should report what WOULD be skipped without writing."""
    from backend.scripts.reset_bot_open_trades import reset_open_trades

    db = _FakeDB()
    db.bot_trades.docs = [
        _make_trade("aph-1", "APH", "long"),
        _make_trade("stale-1", "STALE", "short"),
    ]
    db.ib_live_snapshot.docs = [{
        "_id": "current",
        "positions": [{"symbol": "APH", "position": 588.0}],
    }]

    result = reset_open_trades(db=db, dry_run=True, force=False)

    assert result["dry_run"] is True
    assert result["matched_count"] == 2
    assert result["safe_to_close_count"] == 1
    assert len(result["skipped_ib_held"]) == 1
    assert result["modified_count"] == 0
    # Nothing actually changed in dry-run
    assert all(d["status"] == "open" for d in db.bot_trades.docs)


def test_partial_partition_when_some_held_some_not():
    """Mix: 3 trades — APH (held), STALE (gone), V (gone). Only the 2
    truly-orphaned bot rows close; APH preserved."""
    from backend.scripts.reset_bot_open_trades import reset_open_trades

    db = _FakeDB()
    db.bot_trades.docs = [
        _make_trade("aph-1", "APH", "long", shares=588),
        _make_trade("stale-1", "STALE", "long", shares=100),
        _make_trade("v-1", "V", "long", shares=200),
    ]
    db.ib_live_snapshot.docs = [{
        "_id": "current",
        "positions": [
            {"symbol": "APH", "position": 588.0},
            # STALE and V no longer in IB
        ],
    }]

    result = reset_open_trades(db=db, dry_run=False, force=False)

    assert result["matched_count"] == 3
    assert result["safe_to_close_count"] == 2
    assert result["modified_count"] == 2
    assert len(result["skipped_ib_held"]) == 1
    assert result["skipped_ib_held"][0]["symbol"] == "APH"
    # APH still open, others closed
    by_sym = {d["symbol"]: d for d in db.bot_trades.docs}
    assert by_sym["APH"]["status"] == "open"
    assert by_sym["STALE"]["status"] == "closed"
    assert by_sym["V"]["status"] == "closed"


def test_direction_aware_survival_guard():
    """If bot has SOFI long but IB has SOFI short, row should NOT be
    saved by the guard (different direction = different position)."""
    from backend.scripts.reset_bot_open_trades import reset_open_trades

    db = _FakeDB()
    db.bot_trades.docs = [
        _make_trade("sofi-1", "SOFI", "long", shares=500),
    ]
    db.ib_live_snapshot.docs = [{
        "_id": "current",
        "positions": [{"symbol": "SOFI", "position": -300.0}],  # SHORT
    }]

    result = reset_open_trades(db=db, dry_run=False, force=False)

    # Bot's LONG row should be closed (IB doesn't hold long) — direction matters
    assert result["modified_count"] == 1
    assert db.bot_trades.docs[0]["status"] == "closed"
