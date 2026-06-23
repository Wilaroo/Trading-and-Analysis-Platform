"""A/B/C diagnostics e2e — isolated throwaway DB so aggregates are clean.

A) MFE/MAE study: scalp=entry_problem (low MFE), intraday=exit_giveback (losers
   reached +1R). B) TQS integrity: monotonic grades=predictive, tight score=compressed,
   pillar at 50 = defaulted. C) funnel unique alert_id dedup + capacity rejections.
"""
import os
import pymongo
from datetime import datetime, timezone

from services.mfe_mae_study import generate_report as mfe_report
from services.tqs_integrity import generate_report as tqs_report
from services.horizon_funnel import generate_report as funnel_report

NOW = datetime.now(timezone.utc).isoformat()
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
DBNAME = "diag_abc_DELETEME_db"


def main():
    client = pymongo.MongoClient(os.environ["MONGO_URL"])
    db = client[DBNAME]
    client.drop_database(DBNAME)

    # ---- A: closed trades with MFE/MAE ----
    bt = []
    for _ in range(12):  # scalp: never works -> entry_problem (mfe 0.2)
        bt.append({"setup_type": "spencer_scalp", "status": "closed",
                   "realized_pnl": -100.0, "risk_amount": 200.0,
                   "mfe_r": 0.2, "mae_r": -1.0, "closed_at": NOW})
    for _ in range(12):  # intraday: green then reversed -> exit_giveback
        bt.append({"setup_type": "big_dog", "status": "closed",
                   "realized_pnl": -200.0, "risk_amount": 200.0,
                   "mfe_r": 1.5, "mae_r": -1.2, "closed_at": NOW})
    db["bot_trades"].insert_many(bt)

    a = mfe_report(db, days=1)
    byh = {h["horizon"]: h for h in a["horizons"]}
    print("A scalp:", byh["scalp"]["verdict"], "intraday:", byh["intraday"]["verdict"])
    assert byh["scalp"]["verdict"] == "entry_problem", byh["scalp"]
    assert byh["intraday"]["verdict"] == "exit_giveback", byh["intraday"]
    assert byh["intraday"]["pct_losers_reached_1r"] == 1.0, byh["intraday"]

    # ---- B: grade separation (alert_outcomes) ----
    ao = []
    for g, rm in (("A", 1.0), ("B", 0.3), ("C", -0.1), ("D", -0.6)):
        for _ in range(10):
            ao.append({"trade_grade": g, "r_multiple": rm, "outcome": "win" if rm > 0 else "loss",
                       "setup_type": "stage_2_breakout", "closed_at": NOW})
    db["alert_outcomes"].insert_many(ao)

    # gate-log: tight quality_score (compressed) + alert_id dups + pillar_scores
    gl = []
    for i in range(20):  # 20 evals, 4 unique alert_ids -> scalp GO
        gl.append({"setup_type": "spencer_scalp", "decision": "GO",
                   "alert_id": f"aid_{i % 4}", "quality_score": 50 + (i % 3) - 1,
                   "timestamp": NOW})
    for i in range(5):   # pillar_scores: setup+execution at neutral default
        gl.append({"setup_type": "big_dog", "decision": "SKIP",
                   "alert_id": f"bd_{i}", "quality_score": 50,
                   "pillar_scores": {"setup": 50.0, "technical": 62.0,
                                     "fundamental": 55.0, "context": 48.0,
                                     "execution": 50.0}, "timestamp": NOW})
    db["confidence_gate_log"].insert_many(gl)

    b = tqs_report(db, days=1)
    gs = b["grade_separation"]
    print("B grade:", gs["verdict"], "monotonic:", gs["monotonic_A_to_F"],
          "spread:", gs["avg_r_spread_A_minus_worst"])
    assert gs["monotonic_A_to_F"] is True and gs["verdict"] == "predictive", gs
    assert b["score_discrimination"]["verdict"] == "compressed", b["score_discrimination"]
    pc = {p["pillar"]: p for p in b["pillar_coverage"]["pillars"]}
    assert pc["setup"]["defaulted_pct"] == 100.0, pc["setup"]
    assert pc["execution"]["defaulted_pct"] == 100.0, pc["execution"]
    assert pc["technical"]["defaulted_pct"] == 0.0, pc["technical"]
    print("B pillars defaulted:", {k: v["defaulted_pct"] for k, v in pc.items()})

    # ---- C: funnel unique dedup + capacity rejections ----
    db["rejection_daily_counts"].insert_one({
        "date": TODAY, "reason_code": "portfolio_exposure_cap",
        "horizon": "scalp", "count": 50})
    f = funnel_report(db, days=1)
    fh = {h["horizon"]: h for h in f["horizons"]}
    print("C scalp evaluated:", fh["scalp"]["evaluated"],
          "unique:", fh["scalp"]["evaluated_unique"])
    assert fh["scalp"]["evaluated"] == 20 and fh["scalp"]["evaluated_unique"] == 4, fh["scalp"]
    assert f["capacity_rejections"]["total"] == 50, f["capacity_rejections"]
    assert f["capacity_rejections"]["by_horizon"].get("scalp") == 50, f["capacity_rejections"]
    print("C capacity_rejections:", f["capacity_rejections"]["by_horizon"])

    client.drop_database(DBNAME)
    print("CLEANED UP — A/B/C DIAGNOSTICS E2E PASS")


if __name__ == "__main__":
    main()
