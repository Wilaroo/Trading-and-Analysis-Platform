"""P3 Seam-3 e2e: record_shadow_arms -> shadow_signals -> generate_arm_report.

Exercises the FULL wiring on a synthetic alert (no IB, no live bot):
  • record_shadow_arms writes 3 arm rows (champion/unified_1a2a/gate_off)
  • the new ShadowSignal arm fields persist
  • generate_arm_report groups + scores them (win-rate, raw + weighted R)
Self-cleaning: deletes its own test rows by a unique alert_id.
"""
import os
import asyncio
import pymongo

from services.slow_learning.shadow_mode_service import init_shadow_mode_service
from services.shadow_arms import record_shadow_arms

TEST_ALERT_ID = "p3test_alert_DELETEME"


async def main():
    db = pymongo.MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    svc = init_shadow_mode_service(db=db)
    col = db["shadow_signals"]

    # clean any prior run
    col.delete_many({"alert_id": TEST_ALERT_ID})

    # High-TQS (grade B) alert the live gate VETOED -> the over-veto case.
    alert = {
        "id": TEST_ALERT_ID,
        "symbol": "TESTX",
        "setup_type": "stage_2_breakout",
        "trigger_price": 100.0,
        "stop_price": 98.0,          # risk = 2.0 -> 2R target = 104.0
        "tqs_score": 70,
        "tqs_grade": "B",
        "direction": "long",
    }
    await record_shadow_arms(
        bot=None, alert=alert,
        grade="B", tqs_score=70,
        # gate vetoes AND the regime cell is HOSTILE (P4 abstention case)
        gate_result={"decision": "SKIP",
                     "regime_suppression": {"action": "SKIP",
                                            "reason": "weighted_mean_R -0.62 <= -0.5 (n=40)"}},
        champion_decision="SKIP", champion_conf_mult=1.0,
        current_price=100.0, direction="long", regime="bear",
    )

    rows = list(col.find({"alert_id": TEST_ALERT_ID}))
    arms = {r["arm"]: r for r in rows}
    assert set(arms) == {"champion", "unified_1a2a", "gate_off", "regime_fit"}, arms.keys()
    assert arms["champion"]["arm_decision"] == "SKIP"
    assert arms["champion"]["status"] == "skipped"
    assert arms["unified_1a2a"]["arm_decision"] == "REDUCE"   # quality-led, not killed
    assert arms["gate_off"]["arm_decision"] == "GO"           # TQS-only -> full
    # P4: unified would REDUCE, but the hostile regime cell forces ABSTAIN (SKIP)
    assert arms["regime_fit"]["arm_decision"] == "SKIP", arms["regime_fit"]
    assert arms["regime_fit"]["status"] == "skipped"
    assert arms["regime_fit"]["size_mult"] == 0.0
    assert arms["unified_1a2a"]["tier"] == "shadow"
    assert arms["gate_off"]["target_price"] == 104.0          # derived 2R geometry
    assert arms["gate_off"]["size_mult"] == 0.7               # grade B
    print("WRITE OK:",
          {a: (r["arm_decision"], r["status"], r["size_mult"]) for a, r in arms.items()})

    # Force one resolvable outcome to prove the report scorer: mark gate_off WON.
    col.update_one(
        {"alert_id": TEST_ALERT_ID, "arm": "gate_off"},
        {"$set": {"status": "won", "would_have_r": 2.0}},
    )

    report = await svc.generate_arm_report(days=1)
    by_arm = {a["arm"]: a for a in report["arms"]}
    assert "gate_off" in by_arm, report
    g = by_arm["gate_off"]
    assert g["resolved"] == 1 and g["wins"] == 1 and g["win_rate"] == 100.0, g
    assert g["total_r"] == 2.0, g
    assert g["weighted_r"] == 1.4, g   # 2.0R * 0.7 size  -> size-weighted
    print("REPORT OK:", by_arm)

    col.delete_many({"alert_id": TEST_ALERT_ID})
    print("CLEANED UP — P3 SHADOW-ARM E2E PASS")


if __name__ == "__main__":
    asyncio.run(main())
