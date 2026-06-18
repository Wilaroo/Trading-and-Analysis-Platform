#!/usr/bin/env python3
"""v382 READ-ONLY TQS pillar-compression probe (Path B scoping). Reads live_alerts only.
Usage: .venv/bin/python backend/scripts/diag_v382_tqs_pillar_compression.py --days 5 [--rth-only]"""
import statistics as st, sys
from datetime import datetime, timezone, timedelta

P = ["setup", "technical", "fundamental", "context", "execution"]


def db():
    e = dict(l.strip().split("=", 1) for l in open("backend/.env")
             if "=" in l and not l.startswith("#"))
    from pymongo import MongoClient
    return MongoClient(e["MONGO_URL"].strip(), serverSelectionTimeoutMS=20000)[e["DB_NAME"].strip()]


def pct(v, p): s = sorted(v); return s[max(0, min(len(s) - 1, round(p / 100 * (len(s) - 1))))]


def row(n, v):
    if not v: return f"  {n:<12} n=0"
    return (f"  {n:<12} n={len(v):<5} min={min(v):3.0f} p10={pct(v,10):3.0f} p50={pct(v,50):3.0f} "
            f"p90={pct(v,90):3.0f} max={max(v):3.0f} mean={st.mean(v):5.1f} sd={st.pstdev(v):4.1f}")


def main():
    a = sys.argv
    days = float(a[a.index("--days") + 1]) if "--days" in a else 5
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    q = {"created_at": {"$gte": since}, "tqs_score": {"$gt": 0}}
    if "--rth-only" in a: q["time_window"] = {"$nin": ["premarket", "closed"]}
    rows = list(db()[ "live_alerts"].find(q, {"_id": 0, "tqs_score": 1, "tqs_pillar_scores": 1, "tqs_breakdown": 1}))
    print(f"== TQS pillar compression: {len(rows)} alerts (last {days}d) ==")
    if not rows: return print("No graded alerts in window.")

    comp = [float(r["tqs_score"]) for r in rows]
    pv = {p: [] for p in P}; fund50 = smb_n = smb_seen = 0
    for r in rows:
        ps = r.get("tqs_pillar_scores") or {}
        for p in P:
            if isinstance(ps.get(p), (int, float)): pv[p].append(float(ps[p]))
        if isinstance(ps.get("fundamental"), (int, float)) and abs(ps["fundamental"] - 50) < .5: fund50 += 1
        smb = (((r.get("tqs_breakdown") or {}).get("setup") or {}).get("components") or {}).get("smb")
        if isinstance(smb, (int, float)): smb_seen += 1; smb_n += abs(smb - 50) < .5
    print(row("COMPOSITE", comp)); [print(row(p, pv[p])) for p in P]
    n = len(rows)
    print(f"\nfundamental pinned@50: {fund50}/{n} ({fund50/n*100:.0f}%)  [15% weight]")
    if smb_seen: print(f"setup SMB neutral@50 (DECOMPRESS): {smb_n}/{smb_seen} ({smb_n/smb_seen*100:.0f}%)")
    sds = {p: st.pstdev(v) for p, v in pv.items() if len(v) > 1}
    if sds:
        print("pillar stdev (low=most pinned): " + "  ".join(f"{p}={s:.1f}" for p, s in sorted(sds.items(), key=lambda x: x[1])))
    for f, l in ((57, "B"), (60, "A")):
        c = sum(x >= f for x in comp); print(f">= {f} (grade {l}): {c}/{n} ({c/n*100:.0f}%)")
    print(f"composite max={max(comp):.1f}")


if __name__ == "__main__":
    main()
