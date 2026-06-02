#!/usr/bin/env python3
"""probe_catalyst_dist.py (READ-ONLY) — catalyst sub-score distribution across
recent alert tqs_breakdowns, to confirm v220 lifts catalyst off the 40 floor
for real symbols (not just 1-2). Writes nothing."""
import os
from collections import Counter
from datetime import datetime, timezone, timedelta


def _env():
    u = os.environ.get("MONGO_URL"); n = os.environ.get("DB_NAME")
    for c in ("/app/backend/.env", "backend/.env", ".env"):
        if not os.path.exists(c):
            continue
        for line in open(c):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1); k, v = k.strip(), v.strip().strip('"').strip("'")
                if k == "MONGO_URL" and not u:
                    u = v
                if k == "DB_NAME" and not n:
                    n = v
    return u or "mongodb://localhost:27017", n or "tradecommand"


def _find_catalyst(bd):
    """Walk the breakdown dict to find fundamental.components.catalyst."""
    if not isinstance(bd, dict):
        return None
    f = bd.get("fundamental") or (bd.get("pillars", {}) or {}).get("fundamental")
    if isinstance(f, dict):
        comp = f.get("components", {})
        if isinstance(comp, dict) and "catalyst" in comp:
            return comp["catalyst"]
    return None


def main():
    from pymongo import MongoClient
    u, n = _env()
    db = MongoClient(u, serverSelectionTimeoutMS=5000)[n]
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    q = {"$or": [{"timestamp": {"$gte": cutoff}}, {"created_at": {"$gte": cutoff}},
                 {"alert_time": {"$gte": cutoff}}]}
    cur = db["live_alerts"].find(q, {"tqs_breakdown": 1, "symbol": 1}).limit(500)
    dist = Counter(); n_alerts = 0; lifted = 0; samples = []
    for d in cur:
        cv = _find_catalyst(d.get("tqs_breakdown", {}))
        if cv is None:
            continue
        n_alerts += 1
        dist[round(float(cv), 0)] += 1
        if float(cv) > 40:
            lifted += 1
            if len(samples) < 12:
                samples.append((d.get("symbol"), cv))
    print(f"DB: {n}   alerts with catalyst sub-score (last 30m): {n_alerts}")
    if not n_alerts:
        print("  (no breakdowns in window — widen the window or wait for scans)")
        return
    print(f"  lifted OFF the 40 floor: {lifted}/{n_alerts}  ({lifted/n_alerts*100:.0f}%)")
    print("\n  catalyst sub-score distribution:")
    for score in sorted(dist):
        bar = "#" * min(40, dist[score])
        tag = {40: "floor/no-news", 50: "news neutral", 55: "news (caught)",
               65: "directional news", 70: "news+", 85: "strong"}.get(int(score), "")
        print(f"    {score:5.0f}  {dist[score]:4d}  {bar}  {tag}")
    if samples:
        print("\n  sample lifted symbols:", ", ".join(f"{s}({c})" for s, c in samples))
    print("\nDone. Read-only.")


if __name__ == "__main__":
    main()
