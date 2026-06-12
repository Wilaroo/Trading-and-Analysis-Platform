"""
v19.34.195 — dual-shape timestamps (`ts` ISO + `ts_dt` BSON) on bot_trades
and shadow_decisions (parity with v172 bracket_lifecycle_events /
alert_outcomes). Prevents silent cross-collection Mongo query bugs where a
filter by ISO string misses BSON-dated rows and vice-versa.
"""
import asyncio
from datetime import datetime, timezone

import mongomock

from services.bot_persistence import BotPersistence
from services.ai_modules.shadow_tracker import ShadowTracker


class _FakeTrade:
    def __init__(self, created_at):
        self.id = "t1"
        self.symbol = "AAPL"
        self.status = "open"
        self.direction = "long"
        self._created = created_at

    def to_dict(self):
        return {
            "id": self.id, "symbol": self.symbol, "status": "open",
            "direction": "long", "created_at": self._created,
        }


class _FakeBot:
    def __init__(self, db):
        self._db = db
        self._open_trades = {}


_CREATED = "2026-06-01T13:30:00+00:00"


def _assert_stamps(doc, anchor_iso):
    assert isinstance(doc.get("ts"), str), "ts must be an ISO string"
    assert isinstance(doc.get("ts_dt"), datetime), "ts_dt must be a BSON datetime"
    # Both represent the same instant as the anchor. Mongo stores BSON
    # datetimes as naive UTC, so normalize tzinfo before comparing.
    expected = datetime.fromisoformat(anchor_iso.replace("Z", "+00:00"))
    ts_dt = doc["ts_dt"]
    if ts_dt.tzinfo is None:
        ts_dt = ts_dt.replace(tzinfo=timezone.utc)
    assert ts_dt == expected
    ts_parsed = datetime.fromisoformat(doc["ts"])
    if ts_parsed.tzinfo is None:
        ts_parsed = ts_parsed.replace(tzinfo=timezone.utc)
    assert ts_parsed == expected


# ── 1. persist_trade (update_one upsert) stamps ts/ts_dt ──────────────────
def test_persist_trade_writes_dual_timestamps():
    db = mongomock.MongoClient().db
    bot = _FakeBot(db)
    BotPersistence().persist_trade(_FakeTrade(_CREATED), bot)

    doc = db["bot_trades"].find_one({"id": "t1"})
    assert doc is not None
    _assert_stamps(doc, _CREATED)


# ── 2. save_trade (replace_one upsert) stamps ts/ts_dt ────────────────────
def test_save_trade_writes_dual_timestamps():
    db = mongomock.MongoClient().db
    bot = _FakeBot(db)
    asyncio.run(BotPersistence().save_trade(_FakeTrade(_CREATED), bot))

    doc = db["bot_trades"].find_one({"_id": "t1"})
    assert doc is not None
    _assert_stamps(doc, _CREATED)


# ── 3. ts is stable across re-persists (anchored to created_at, not now) ──
def test_ts_anchored_to_created_at_stable_across_updates():
    db = mongomock.MongoClient().db
    bot = _FakeBot(db)
    bp = BotPersistence()
    t = _FakeTrade(_CREATED)
    bp.persist_trade(t, bot)
    first = db["bot_trades"].find_one({"id": "t1"})["ts_dt"]
    bp.persist_trade(t, bot)  # update again
    second = db["bot_trades"].find_one({"id": "t1"})["ts_dt"]
    assert first == second, "ts_dt must stay anchored to created_at across updates"


# ── 4. shadow_decisions insert stamps ts/ts_dt ────────────────────────────
def test_shadow_decision_writes_dual_timestamps():
    db = mongomock.MongoClient().db
    tracker = ShadowTracker()
    tracker._decisions_col = db["shadow_decisions"]

    asyncio.run(tracker.log_decision(
        symbol="NVDA", trigger_type="vwap_reclaim", price_at_decision=120.0,
        combined_recommendation="BUY", confidence_score=0.8,
        reasoning="test", was_executed=False,
    ))

    doc = db["shadow_decisions"].find_one({"symbol": "NVDA"})
    assert doc is not None
    assert isinstance(doc.get("ts"), str)
    assert isinstance(doc.get("ts_dt"), datetime)
    # ts mirrors the row's created_at.
    assert datetime.fromisoformat(doc["ts"]) == datetime.fromisoformat(
        doc["created_at"].replace("Z", "+00:00"))
