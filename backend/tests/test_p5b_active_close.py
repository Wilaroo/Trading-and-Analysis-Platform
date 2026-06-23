"""P5 Phase-2 e2e: ACTIVE-mode thesis-invalidation close with hysteresis.

Verifies: (1) active mode does NOT close on first sight (hysteresis guard);
(2) once the hard_regime_flip signal persists past hysteresis it closes via the
bot's close_trade path; (3) regime_hostile_cell does NOT act (not in the default
THESIS_INVALIDATION_ACT_TRIGGERS). Uses a fake bot/PM — no real orders.
"""
import os
import asyncio
import pymongo

os.environ["THESIS_INVALIDATION_MODE"] = "active"
os.environ["THESIS_INVALIDATION_HYSTERESIS_SECONDS"] = "60"
# THESIS_INVALIDATION_ACT_TRIGGERS left default => hard_regime_flip only

from services.thesis_invalidation import observe_open_positions, COLLECTION
from services.setup_taxonomy import canonicalize

TRADE_ID = "p5b_trade_DELETEME"
SETUP = "stage_2_breakout"


class _FakeRegime:
    async def get_current_regime(self, force_refresh=False):
        return {"composite_score": 30.0}  # BEAR<=45


class _FakePM:
    def __init__(self):
        self.closed = []

    async def close_trade(self, tid, bot, reason=""):
        self.closed.append((tid, reason))
        bot._open_trades.pop(tid, None)
        return True


class _FakeTrade:
    def __init__(self):
        self.id = TRADE_ID
        self.alert_id = "a"
        self.symbol = "TESTX"
        self.setup_type = SETUP
        self.direction = "long"
        self.status = "open"
        self.fill_price = 100.0
        self.stop_price = 98.0
        self.current_price = 99.0
        self.risk_amount = 200.0
        self.unrealized_pnl = -100.0
        self.entry_context = {"regime_score": 70.0}  # entered BULL


class _FakeBot:
    def __init__(self, db):
        self._db = db
        self._market_regime_engine = _FakeRegime()
        self._position_manager = _FakePM()
        self._open_trades = {TRADE_ID: _FakeTrade()}


async def main():
    db = pymongo.MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    col = db[COLLECTION]
    col.delete_many({"trade_id": TRADE_ID})
    canon = canonicalize(SETUP)
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

    # Pass 1 — records, but must NOT close (hysteresis not elapsed).
    r1 = await observe_open_positions(bot)
    assert r1["acted"] == 0, r1
    assert bot._position_manager.closed == [], "must not close on first sight"
    assert TRADE_ID in bot._open_trades

    # Age ONLY the hard_regime_flip signal past hysteresis.
    col.update_one(
        {"trade_id": TRADE_ID, "trigger_type": "hard_regime_flip"},
        {"$set": {"created_at": "2020-01-01T00:00:00+00:00"}},
    )

    # Pass 2 — now acts on hard_regime_flip; closes via close_trade.
    r2 = await observe_open_positions(bot)
    print("PASS2:", r2, "closed:", bot._position_manager.closed)
    assert r2["acted"] == 1, r2
    assert any(reason == "thesis_invalidation:hard_regime_flip"
               for _, reason in bot._position_manager.closed), bot._position_manager.closed
    assert TRADE_ID not in bot._open_trades  # PM removed it

    acted_sig = col.find_one({"trade_id": TRADE_ID, "trigger_type": "hard_regime_flip"})
    assert acted_sig.get("acted") is True and acted_sig.get("close_reason"), acted_sig
    hostile_sig = col.find_one({"trade_id": TRADE_ID, "trigger_type": "regime_hostile_cell"})
    assert hostile_sig and not hostile_sig.get("acted"), "hostile-cell must NOT act by default"
    print("ACTIVE-CLOSE + HYSTERESIS + ACT-TRIGGER-FILTER OK")

    # cleanup
    col.delete_many({"trade_id": TRADE_ID})
    if prev is not None:
        prev.pop("_id", None)
        db["setup_regime_expectancy"].update_one({"_id": "current"}, {"$set": prev}, upsert=True)
    else:
        db["setup_regime_expectancy"].delete_one({"_id": "current"})
    print("CLEANED UP — P5b ACTIVE-CLOSE E2E PASS")


if __name__ == "__main__":
    asyncio.run(main())
