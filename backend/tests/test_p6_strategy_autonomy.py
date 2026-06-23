"""P6 e2e: strategy-autonomy on/off recommendations for the current regime.

Seeds a BEAR regime + an expectancy table with three families and checks the
read-model classifies them: hostile -> DISABLE, healthy -> ENABLE, edge-decaying
-> WATCH. Self-cleaning. Pure read-model — no live behavior change.
"""
import os
import pymongo
from datetime import datetime, timezone

from services.strategy_autonomy import generate_report
from services.setup_taxonomy import canonicalize

HOSTILE = canonicalize("stage_2_breakout")
HEALTHY = "p6_healthy_setup"
DECAY = "p6_decaying_setup"
REGIME_DATE = "p6test_DELETEME"


def main():
    db = pymongo.MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    # seed latest regime = BEAR (composite 30 -> BEAR<=45)
    db["market_regime_state"].delete_many({"date": REGIME_DATE})
    db["market_regime_state"].insert_one({
        "date": REGIME_DATE,
        "timestamp": datetime.now(timezone.utc),
        "composite_score": 30.0,
    })
    band = "BEAR<=45"
    prev = db["setup_regime_expectancy"].find_one({"_id": "current"})
    db["setup_regime_expectancy"].update_one(
        {"_id": "current"},
        {"$set": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "params": {"min_eff_n": 25.0, "hard_r": -0.5, "soft_r": -0.12},
            "cells": {
                f"{HOSTILE}|{band}": {"weighted_mean_r": -0.62, "eff_n": 40.0,
                                      "diag": {"r_30d": -0.6, "r_90d": -0.5, "n_30d": 30}},
                f"{HEALTHY}|{band}": {"weighted_mean_r": 0.30, "eff_n": 40.0,
                                      "diag": {"r_30d": 0.30, "r_90d": 0.30, "n_30d": 30}},
                f"{DECAY}|{band}": {"weighted_mean_r": 0.05, "eff_n": 40.0,
                                    "diag": {"r_30d": -0.05, "r_90d": 0.30, "n_30d": 20}},
            },
        }},
        upsert=True,
    )

    rep = generate_report(db)
    print("BAND:", rep["current_band"], "score:", rep["current_regime_score"])
    by = {r["setup"]: r["recommendation"] for r in rep["recommendations"]}
    print("RECS:", by)
    assert rep["current_band"] == band, rep
    assert by.get(HOSTILE) == "DISABLE", by
    assert by.get(HEALTHY) == "ENABLE", by
    assert by.get(DECAY) == "WATCH", by              # edge-decay flagged
    assert rep["counts"]["DISABLE"] >= 1 and rep["counts"]["WATCH"] >= 1, rep["counts"]
    # DISABLE must sort first for operator triage
    assert rep["recommendations"][0]["recommendation"] == "DISABLE", rep["recommendations"][0]

    # cleanup
    db["market_regime_state"].delete_many({"date": REGIME_DATE})
    if prev is not None:
        prev.pop("_id", None)
        db["setup_regime_expectancy"].update_one({"_id": "current"}, {"$set": prev}, upsert=True)
    else:
        db["setup_regime_expectancy"].delete_one({"_id": "current"})
    print("CLEANED UP — P6 STRATEGY-AUTONOMY E2E PASS")


if __name__ == "__main__":
    main()
