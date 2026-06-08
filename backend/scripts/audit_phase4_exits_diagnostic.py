#!/usr/bin/env python3
"""
Audit Phase 4 (Manage) — EXIT-MECHANISM diagnostic  (READ-ONLY).

The first diagnostic showed scale-out/trailing is dormant (8/1457 hit T1, 0 hit T2,
0 trailing moves). This script explains WHY by showing how trades ACTUALLY exit and
whether they ever reach the higher targets the local engine is supposed to manage.

Reports (read-only, {"_id":0} projection, no writes):
  1. close_reason distribution         — the real exit mechanism (IB bracket vs local).
  2. target_prices ladder length        — how many targets each trade carries.
  3. scale_out / trailing config flags   — enabled vs actually used.
  4. MFE-vs-targets                      — did price REACH T1/T2/T3 (mfe) even though
                                           the local engine didn't record a scale-out?
                                           High "reached-but-not-recorded" = exits are
                                           server-side (single-target OCA at T1).

Run on the DGX:
    cd ~/Trading-and-Analysis-Platform/backend
    ../.venv/bin/python scripts/audit_phase4_exits_diagnostic.py
    # optional: --days 30
"""
import argparse
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone


def _load_env():
    here = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(os.path.dirname(here), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    mongo = os.environ.get("MONGO_URL")
    db = os.environ.get("DB_NAME")
    if not mongo or not db:
        print("ERROR: MONGO_URL / DB_NAME not found in env or backend/.env")
        sys.exit(2)
    return mongo, db


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0)
    args = ap.parse_args()

    mongo_url, db_name = _load_env()
    from pymongo import MongoClient
    db = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)[db_name]

    q = {"fill_price": {"$ne": None}}
    if args.days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
        q["$or"] = [{"executed_at": {"$gte": cutoff}}, {"created_at": {"$gte": cutoff}}]

    proj = {"_id": 0, "symbol": 1, "direction": 1, "status": 1, "close_reason": 1,
            "fill_price": 1, "stop_price": 1, "target_prices": 1, "exit_price": 1,
            "mfe_r": 1, "mfe_price": 1, "scale_out_config": 1, "trailing_stop_config": 1}
    trades = list(db["bot_trades"].find(q, proj))
    total = len(trades)

    print("=" * 72)
    print(f"AUDIT PHASE 4 — EXIT-MECHANISM DIAGNOSTIC   ({db_name})")
    print(f"filled trades scanned: {total}"
          + (f"  (last {args.days}d)" if args.days else "  (all time)"))
    print("=" * 72)
    if total == 0:
        print("No filled bot_trades found.")
        return

    closed = [t for t in trades if str(t.get("status", "")).lower() == "closed"]

    # 1) close_reason distribution
    cr = Counter(str(t.get("close_reason") or "(none/open)") for t in trades)
    print(f"\n── 1. close_reason distribution (closed={len(closed)}) ──")
    for reason, n in cr.most_common(20):
        print(f"  {n:6d}  {reason}")

    # 2) target ladder length
    ladder = Counter(len(t.get("target_prices") or []) for t in trades)
    print("\n── 2. target_prices ladder length (how many targets per trade) ──")
    for length, n in sorted(ladder.items()):
        print(f"  {n:6d} trades carry {length} target level(s)")

    # 3) config flags vs usage
    scale_enabled = sum(1 for t in trades
                        if (t.get("scale_out_config") or {}).get("enabled", True))
    trail_enabled = sum(1 for t in trades
                        if (t.get("trailing_stop_config") or {}).get("enabled", True))
    any_partial = sum(1 for t in trades
                      if (t.get("scale_out_config") or {}).get("partial_exits"))
    any_stopadj = sum(1 for t in trades
                      if (t.get("trailing_stop_config") or {}).get("stop_adjustments"))
    print("\n── 3. config ENABLED vs actually USED ──")
    print(f"  scale_out enabled:      {scale_enabled}/{total}")
    print(f"  trailing enabled:       {trail_enabled}/{total}")
    print(f"  trades w/ ANY partial_exit recorded:   {any_partial}")
    print(f"  trades w/ ANY stop_adjustment recorded:{any_stopadj}")

    # 4) MFE vs targets — did price REACH the targets even if not recorded?
    #    R-multiple of MFE tells us how far in favor the trade went.
    reached = Counter()
    mfe_have = 0
    for t in trades:
        mfe_r = t.get("mfe_r")
        if mfe_r is None:
            continue
        try:
            mfe_r = float(mfe_r)
        except (TypeError, ValueError):
            continue
        mfe_have += 1
        if mfe_r >= 1.0:
            reached["mfe>=1R (could hit T1)"] += 1
        if mfe_r >= 2.0:
            reached["mfe>=2R (could hit T2)"] += 1
        if mfe_r >= 3.0:
            reached["mfe>=3R (could hit T3)"] += 1
    print(f"\n── 4. MFE reach (trades with mfe_r present: {mfe_have}) ──")
    if mfe_have:
        for k in ("mfe>=1R (could hit T1)", "mfe>=2R (could hit T2)",
                  "mfe>=3R (could hit T3)"):
            n = reached.get(k, 0)
            print(f"  {n:6d}  {k}   ({n/mfe_have*100:.0f}% of trades w/ MFE)")
        print("  INTERPRETATION: if many trades reached >=1R/2R MFE but section 3 shows")
        print("  ~0 partial_exits / stop_adjustments, the position was EXITED SERVER-SIDE")
        print("  by the single-target OCA bracket (LMT at T1) before the local scale-out/")
        print("  trailing engine could act → scale-out & trailing are effectively OFF.")
    else:
        print("  (no mfe_r data — cannot assess reach)")

    print("\n" + "=" * 72)
    print("DONE — read-only. No documents were modified.")
    print("=" * 72)


if __name__ == "__main__":
    main()
