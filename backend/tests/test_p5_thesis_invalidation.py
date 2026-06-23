"""P5 e2e: thesis-invalidation OBSERVE detector + report.

Simulates an open LONG position entered in a BULL regime whose setup x dir is
now statistically HOSTILE in the CURRENT (BEAR) regime band per the T6 table —
so both triggers should fire (regime_hostile_cell + hard_regime_flip). Then
closes the trade and checks the report scores 'exit at signal' vs 'held'.
Self-cleaning. No live close ever happens (observe mode).
"""
import os
import asyncio
import pymongo

os.environ["THESIS_INVALIDATION_MODE"] = "observe"

from services.thesis_invalidation import observe_open_positions, generate_report, COLLECTION
from services.setup_taxonomy import canonicalize

TRADE_ID = "p5test_trade_DELETEME"
SETUP = "stage_2_breakout"


class _FakeRegime:
    """Returns a BEAR composite score (band BEAR<=45)."""
    async def get_current_regime(self, force_refresh=False):
        return {"composite_score": 30.0, "regime": "bearish"}


class _FakeTrade:
    def __init__(self):
        self.id = TRADE_ID
        self.alert_id = "p5test_alert"
        self.symbol = "TESTX"
        self.setup_type = SETUP
        self.direction = "long"
        self.status = "open"
        self.fill_price = 100.0
        self.stop_price = 98.0
        self.current_price = 99.0          # underwater -> unrealized R = -0.5
        self.risk_amount = 200.0           # $ risk
        self.unrealized_pnl = -100.0       # -0.5 R
        self.entry_context = {"regime_score": 70.0}  # entered in BULL


class _FakeBot:
    def __init__(self, db):
        self._db = db
        self._market_regime_engine = _FakeRegime()
        self._open_trades = {TRADE_ID: _FakeTrade()}


async def main():
    db = pymongo.MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    col = db[COLLECTION]
    col.delete_many({"trade_id": TRADE_ID})
    db.bot_trades.delete_many({"id": TRADE_ID})

    canon = canonicalize(SETUP)
    # Seed a T6 table: hostile in BEAR, healthy in BULL -> a genuine flip.
    db["setup_regime_expectancy"].update_one(
        {"_id": "p5test_current_BACKUP_GUARD"},  # never used; just ensures coll exists
        {"$setOnInsert": {"x": 1}}, upsert=True,
    )
    prev = db["setup_regime_expectancy"].find_one({"_id": "current"})
    db["setup_regime_expectancy"].update_one(
        {"_id": "current"},
        {"$set": {
            "params": {"min_eff_n": 25.0, "hard_r": -0.5, "soft_r": -0.12},
            "cells": {
                f"{canon}|long|BEAR<=45": {"weighted_mean_r": -0.62, "eff_n": 40.0, "raw_n": 40},
                f"{canon}|long|BULL>60": {"weighted_mean_r": 0.35, "eff_n": 40.0, "raw_n": 40},
            },
        }},
        upsert=True,
    )

    bot = _FakeBot(db)
    res = await observe_open_positions(bot)
    print("OBSERVE:", res)
    sigs = list(col.find({"trade_id": TRADE_ID}))
    ttypes = {s["trigger_type"] for s in sigs}
    assert "regime_hostile_cell" in ttypes, ttypes
    assert "hard_regime_flip" in ttypes, ttypes
    one = next(s for s in sigs if s["trigger_type"] == "regime_hostile_cell")
    assert one["entry_band"] == "BULL>60" and one["current_band"] == "BEAR<=45", one
    assert one["unrealized_r_at_signal"] == -0.5, one
    assert one["acted"] is False  # OBSERVE never acts
    print("SIGNALS OK:", {s["trigger_type"]: s["unrealized_r_at_signal"] for s in sigs})

    # Idempotent: a second pass must NOT duplicate (dedup by trade+trigger).
    res2 = await observe_open_positions(bot)
    assert res2["new_signals"] == 0, res2
    assert col.count_documents({"trade_id": TRADE_ID}) == len(sigs), "dedup failed"
    print("DEDUP OK:", res2)

    # Close the trade as a BIG LOSER (held to -2R) -> exiting at -0.5R would have helped.
    db.bot_trades.insert_one({
        "id": TRADE_ID, "status": "closed", "symbol": "TESTX",
        "realized_pnl": -400.0, "risk_amount": 200.0,  # held R = -2.0
    })
    report = await generate_report(db, days=1)
    print("REPORT:", report)
    assert report["scored"] >= 1, report
    # exit_r (-0.5) - held_r (-2.0) = +1.5 -> helped
    assert report["avg_r_delta"] == 1.5, report
    assert report["would_have_helped"] >= 1, report

    # cleanup
    col.delete_many({"trade_id": TRADE_ID})
    db.bot_trades.delete_many({"id": TRADE_ID})
    db["setup_regime_expectancy"].delete_one({"_id": "p5test_current_BACKUP_GUARD"})
    # restore prior expectancy doc if the test overwrote a real one
    if prev is not None:
        prev.pop("_id", None)
        db["setup_regime_expectancy"].update_one({"_id": "current"}, {"$set": prev}, upsert=True)
    else:
        db["setup_regime_expectancy"].delete_one({"_id": "current"})
    print("CLEANED UP — P5 THESIS-INVALIDATION E2E PASS")


if __name__ == "__main__":
    asyncio.run(main())
