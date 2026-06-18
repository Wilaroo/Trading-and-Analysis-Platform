#!/usr/bin/env python3
"""diag_v367_verify.py (READ-ONLY) — confirm v367 multi-TF shadow records are being written.

The v366 readiness diag only inspects the single live_prediction.regime_shadow (always 5min),
so it can't show multi-TF. This checks the NEW live_prediction.regime_shadows[] list directly.
NOTHING IS WRITTEN. Usage: .venv/bin/python backend/scripts/diag_v367_verify.py [--mins 60]
"""
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone


def _arg(flag, d, c):
    if flag in sys.argv:
        try:
            return c(sys.argv[sys.argv.index(flag) + 1])
        except Exception:
            return d
    return d


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


def main():
    mins = _arg("--mins", 60, int)
    db = _load_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=mins)).isoformat()
    col = db["confidence_gate_log"]

    has_list = col.count_documents({"live_prediction.regime_shadows": {"$exists": True}})
    has_single_only = col.count_documents({
        "live_prediction.regime_shadow": {"$exists": True},
        "live_prediction.regime_shadows": {"$exists": False},
    })
    print(f"\n=== v367 multi-TF verify (now {datetime.now(timezone.utc).isoformat(timespec='seconds')}) ===")
    print(f"  docs WITH regime_shadows[] (post-v367) : {has_list}")
    print(f"  docs with single regime_shadow only    : {has_single_only}  (pre-v367 / multi-tf off)")

    # recent docs carrying the list — tally list length + bar_sizes inside the lists
    cur = col.find(
        {"live_prediction.regime_shadows": {"$exists": True}, "timestamp": {"$gte": cutoff}},
        {"_id": 0, "live_prediction.regime_shadows": 1, "symbol": 1, "timestamp": 1},
    ).sort("timestamp", -1).limit(500)
    rows = list(cur)
    print(f"\n  recent docs (last {mins}m) with regime_shadows[] : {len(rows)}")
    len_dist = Counter()
    bs_dist = Counter()
    for d in rows:
        lst = (d.get("live_prediction") or {}).get("regime_shadows") or []
        len_dist[len(lst)] += 1
        for s in lst:
            bs_dist[s.get("bar_size", "?")] += 1
    print(f"  list-length distribution : {dict(len_dist)}")
    print(f"  bar_size distribution (across all list entries) : {dict(bs_dist)}")

    if rows:
        ex = rows[0]
        lst = (ex.get("live_prediction") or {}).get("regime_shadows") or []
        print(f"\n  sample ({ex.get('symbol')} @ {ex.get('timestamp')}):")
        for s in lst:
            print(f"    bar_size={s.get('bar_size'):<8} regime={s.get('regime'):<10} "
                  f"regime_model_available={s.get('regime_model_available')} "
                  f"agree={s.get('directions_agree')}")
    print("\n  -> Expect list-length up to 3 and bar_size dist spanning 1 min / 5 mins / 15 mins")
    print("     for symbols with >=50 bars at each TF. If only '5 mins' appears with length 1,")
    print("     either PWIRE_MULTI_TF_SHADOW=0 or those symbols lacked 1/15min bars at fire time.\n")


if __name__ == "__main__":
    main()
