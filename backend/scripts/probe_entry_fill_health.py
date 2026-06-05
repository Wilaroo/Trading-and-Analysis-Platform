#!/usr/bin/env python3
"""
probe_entry_fill_health.py  (v19.34.283) — READ-ONLY.

Reports today's entry fill-rate health: how many auto-submitted entries filled
vs were rejected, and segments the rejects by reason. Run before/after the v283
marketable-limit fix to measure the recovery.

Usage (DGX, repo root):
    .venv/bin/python backend/scripts/probe_entry_fill_health.py
    .venv/bin/python backend/scripts/probe_entry_fill_health.py 2026-06-05
"""
import collections
import sys
from datetime import datetime, timezone

from pymongo import MongoClient


def _load_env():
    env = {}
    for line in open("backend/.env"):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def _sub_reason(notes):
    n = str(notes or "")
    if "[REJECTED: " in n:
        return n.split("[REJECTED: ")[1].split("]")[0].split(":")[0]
    return None


def main():
    day = sys.argv[1] if len(sys.argv) > 1 else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    env = _load_env()
    d = MongoClient(env["MONGO_URL"])[env.get("DB_NAME", "tradecommand")]
    rows = list(d["bot_trades"].find({"created_at": {"$gte": day}}))

    by_status = collections.Counter(str(r.get("status")) for r in rows)
    rejected = [r for r in rows if str(r.get("status")) == "rejected"]
    by_close = collections.Counter(str(r.get("close_reason")) for r in rejected)
    sub = collections.Counter(
        _sub_reason(r.get("notes")) or "n/a"
        for r in rejected if str(r.get("close_reason")) == "broker_rejected"
    )

    filled = by_status.get("filled", 0) + by_status.get("open", 0) + by_status.get("closed", 0) + by_status.get("partial", 0)
    submitted = filled + len(rejected)
    fill_rate = (filled / submitted * 100.0) if submitted else 0.0
    recoverable = by_close.get("stale_pending_auto_reaper", 0) + sub.get("parent_not_filled", 0)

    print(f"\n=== entry fill health — {day} ===")
    print(f"trades created today : {len(rows)}")
    print(f"by status            : {dict(by_status)}")
    print(f"fill rate            : {filled}/{submitted} = {fill_rate:.1f}%")
    print(f"rejected total       : {len(rejected)}")
    print(f"  by close_reason    : {dict(by_close)}")
    print(f"  broker_rejected ->  : {dict(sub)}")
    print(f"est. recoverable by v283 (parent_not_filled + reaped): {recoverable}")
    print("  (alert_stale stays skipped by design — genuinely blown setups)\n")


if __name__ == "__main__":
    main()
