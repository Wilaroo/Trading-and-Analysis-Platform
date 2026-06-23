"""Horizon-funnel diagnostic e2e — seeds gate-log + trades across horizons and
checks the funnel correctly classifies + detects the choke point. Self-cleaning.
"""
import os
import pymongo
from datetime import datetime, timezone

from services.horizon_funnel import generate_report, horizon_of

GMARK = "hf_test_DELETEME"
TMARK = "hf_test_trade_DELETEME"


def _gate(setup, decision):
    return {"marker": GMARK, "setup_type": setup, "decision": decision,
            "timestamp": datetime.now(timezone.utc).isoformat()}


def _trade(setup, status, pnl=None, risk=None):
    return {"marker": TMARK, "setup_type": setup, "status": status,
            "realized_pnl": pnl, "risk_amount": risk,
            "created_at": datetime.now(timezone.utc).isoformat()}


def main():
    db = pymongo.MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    db["confidence_gate_log"].delete_many({"marker": GMARK})
    db["bot_trades"].delete_many({"marker": TMARK})

    assert horizon_of("spencer_scalp") == "scalp"
    assert horizon_of("big_dog") == "intraday"
    assert horizon_of("stage_2_breakout") == "position"
    assert horizon_of("daily_squeeze") == "swing"  # multi_day -> swing

    gate = []
    # SCALP: lots evaluated but gate VETOES most (low approve-rate) -> gate_veto
    gate += [_gate("spencer_scalp", "SKIP") for _ in range(16)]
    gate += [_gate("spencer_scalp", "GO") for _ in range(4)]
    # INTRADAY: approved a lot but few taken -> capacity choke
    gate += [_gate("big_dog", "GO") for _ in range(20)]
    # POSITION: healthy (approved and taken)
    gate += [_gate("stage_2_breakout", "GO") for _ in range(20)]
    db["confidence_gate_log"].insert_many(gate)

    trades = []
    trades += [_trade("spencer_scalp", "closed", 100.0, 200.0) for _ in range(4)]   # taken≈approved
    trades += [_trade("big_dog", "closed", -50.0, 200.0) for _ in range(3)]         # taken 3 << approved 20
    trades += [_trade("stage_2_breakout", "closed", 400.0, 200.0) for _ in range(18)]
    db["bot_trades"].insert_many(trades)

    rep = generate_report(db, days=1)
    by = {h["horizon"]: h for h in rep["horizons"]}
    print("HEADLINE:", rep["headline"])
    for h in ("scalp", "intraday", "position"):
        r = by[h]
        print(f"  {h:9s} eval={r['evaluated']:3d} approve_rate={r['approve_rate']} "
              f"taken={r['taken']:3d} t/appr={r['taken_vs_approved']} choke={r['choke']} "
              f"avg_r={r['realized']['avg_r']}")

    assert by["scalp"]["approve_rate"] == 0.2, by["scalp"]
    assert by["scalp"]["choke"] == "gate_veto", by["scalp"]
    assert by["intraday"]["choke"] == "capacity", by["intraday"]   # 3 taken << 20 approved
    assert by["position"]["choke"] == "healthy", by["position"]
    assert by["scalp"]["realized"]["avg_r"] == 0.5, by["scalp"]["realized"]
    assert "scalp=gate_veto" in rep["headline"] and "intraday=capacity" in rep["headline"], rep["headline"]

    db["confidence_gate_log"].delete_many({"marker": GMARK})
    db["bot_trades"].delete_many({"marker": TMARK})
    print("CLEANED UP — HORIZON-FUNNEL E2E PASS")


if __name__ == "__main__":
    main()
