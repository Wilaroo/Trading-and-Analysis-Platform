#!/usr/bin/env python3
"""
v382 — TQS PILLAR-COMPRESSION PROBE (READ-ONLY).  Path B scoping.

WHY: the composite TQS is a weighted AVERAGE of 5 pillars and tops out ~68
(diag_v378c). Before changing any scoring math, this probe shows — on live
data — HOW MUCH each pillar is compressed and WHERE the crush comes from:
  - per-pillar distribution (n, min, p10, p50, p90, max, mean, stdev)
  - % of alerts where FUNDAMENTAL is pinned at the absent-data default (50)
  - % where the SETUP pillar's SMB sub-score hit the TQS_SETUP_DECOMPRESS
    neutral-50 path (uninformative SMB)
  - composite headroom: % reaching the grade floors (>=57 B, >=60 A)
The pillar with the lowest stdev / most pinning is the prime de-compression
target. NOTHING is changed — this only reads live_alerts.

Usage (DGX, repo root):
  .venv/bin/python backend/scripts/diag_v382_tqs_pillar_compression.py --days 5
  .venv/bin/python backend/scripts/diag_v382_tqs_pillar_compression.py --days 5 --rth-only
"""
import statistics as st
import sys
from datetime import datetime, timezone

ALERTS = "live_alerts"
PILLARS = ["setup", "technical", "fundamental", "context", "execution"]
WEIGHTS = {"setup": 0.25, "technical": 0.25, "fundamental": 0.15,
           "context": 0.20, "execution": 0.15}  # intraday/T2H default


def _arg(flag, default, cast=str):
    if flag in sys.argv:
        try:
            return cast(sys.argv[sys.argv.index(flag) + 1])
        except Exception:
            return default
    return default


def _load_db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    from pymongo import MongoClient
    return MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=20000)[env["DB_NAME"]]


def _pct(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    i = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[i]


def _row(name, vals):
    if not vals:
        return f"  {name:<12} n=0"
    sd = st.pstdev(vals) if len(vals) > 1 else 0.0
    return (f"  {name:<12} n={len(vals):<5} min={min(vals):4.0f} p10={_pct(vals,10):4.0f} "
            f"p50={_pct(vals,50):4.0f} p90={_pct(vals,90):4.0f} max={max(vals):4.0f} "
            f"mean={st.mean(vals):5.1f} stdev={sd:4.1f}")


def main():
    days = _arg("--days", 5, float)
    rth_only = "--rth-only" in sys.argv
    since = (datetime.now(timezone.utc) - __import__("datetime").timedelta(days=days)).strftime("%Y-%m-%d")
    db = _load_db()

    q = {"created_at": {"$gte": since}, "tqs_score": {"$gt": 0}}
    if rth_only:
        q["time_window"] = {"$nin": ["premarket", "closed"]}
    proj = {"_id": 0, "tqs_score": 1, "tqs_pillar_scores": 1, "tqs_breakdown": 1,
            "tqs_grade": 1}
    rows = list(db[ALERTS].find(q, proj))

    print("=" * 84)
    print(f"TQS pillar compression — {len(rows)} alerts (last {days}d"
          f"{', RTH-only' if rth_only else ''})")
    print("=" * 84)
    if not rows:
        print("No graded alerts in window.")
        return

    composite = [float(r["tqs_score"]) for r in rows if isinstance(r.get("tqs_score"), (int, float))]
    pillar_vals = {p: [] for p in PILLARS}
    fund_at_50 = 0
    smb_neutral = 0
    smb_seen = 0
    for r in rows:
        ps = r.get("tqs_pillar_scores") or {}
        for p in PILLARS:
            v = ps.get(p)
            if isinstance(v, (int, float)):
                pillar_vals[p].append(float(v))
        if isinstance(ps.get("fundamental"), (int, float)) and abs(ps["fundamental"] - 50.0) < 0.5:
            fund_at_50 += 1
        comp = (((r.get("tqs_breakdown") or {}).get("setup") or {}).get("components") or {})
        if isinstance(comp.get("smb"), (int, float)):
            smb_seen += 1
            if abs(comp["smb"] - 50.0) < 0.5:
                smb_neutral += 1

    print("\nDISTRIBUTIONS (0-100 each)")
    print("-" * 84)
    print(_row("COMPOSITE", composite))
    for p in PILLARS:
        print(_row(p, pillar_vals[p]))

    print("\nPINNING / COMPRESSION SOURCES")
    print("-" * 84)
    n = len(rows)
    print(f"  fundamental pinned at 50 (absent-data default): {fund_at_50}/{n} "
          f"({fund_at_50/n*100:.1f}%)  [weight {WEIGHTS['fundamental']*100:.0f}%]")
    if smb_seen:
        print(f"  setup SMB sub-score at neutral 50 (TQS_SETUP_DECOMPRESS): "
              f"{smb_neutral}/{smb_seen} ({smb_neutral/smb_seen*100:.1f}%)")
    # lowest-variance pillar = biggest crush contributor
    sds = {p: (st.pstdev(v) if len(v) > 1 else 0.0) for p, v in pillar_vals.items() if v}
    if sds:
        tight = sorted(sds.items(), key=lambda kv: kv[1])
        print("  pillar stdev (low = most compressed/pinned):")
        for p, s in tight:
            mean = st.mean(pillar_vals[p])
            print(f"      {p:<12} stdev={s:4.1f}  mean={mean:5.1f}")

    print("\nCOMPOSITE HEADROOM vs GRADE FLOORS")
    print("-" * 84)
    for floor, lbl in ((57, "B"), (60, "A")):
        c = sum(1 for x in composite if x >= floor)
        print(f"  >= {floor} (grade {lbl} floor): {c}/{len(composite)} "
              f"({c/len(composite)*100:.1f}%)")
    print(f"  composite max observed: {max(composite):.1f}")

    print("\n" + "=" * 84)
    print("READ")
    print("=" * 84)
    if sds:
        worst = min(sds, key=sds.get)
        print(f"  Most-pinned pillar: {worst} (stdev {sds[worst]:.1f}).")
    print(f"  Fundamental pinned at 50 for {fund_at_50/n*100:.0f}% of alerts at "
          f"{WEIGHTS['fundamental']*100:.0f}% weight — that alone holds ~"
          f"{WEIGHTS['fundamental']*100*fund_at_50/n/100*1:.1f} pts of the composite at the midpoint.")
    print("  Path B levers to evaluate (separately, with validation):")
    print("   1) when fundamental data is genuinely ABSENT, drop it from the weighted")
    print("      average and renormalize the other 4 pillars (don't inject a flat 50).")
    print("   2) re-test TQS_SETUP_DECOMPRESS now that v310 C-1 feeds real SMB scores.")
    print("   3) re-baseline whichever pillar above shows the lowest stdev.")
    print("  Then re-run this probe to confirm the composite spreads toward 0-100.")


if __name__ == "__main__":
    main()
