#!/usr/bin/env python3
"""
Liquidity-gate forensics for a single symbol  (READ-ONLY).

Why did an illiquid name (e.g. DGCB) clear the scanner's intraday liquidity floor?
The ORB setup IS in `_intraday_setups`, so line 3607 of enhanced_scanner SHOULD require
`snapshot.avg_volume >= INTRADAY_THRESHOLD ($50M)`. This dumps the symbol's actual
alert + trade records so we can see the exact volume/ADV/RVOL the gate evaluated —
the smoking gun (bad data, units mismatch, or a bypassing code path).

READ-ONLY: .find with {"_id":0} only. No writes.

Run:
    cd ~/Trading-and-Analysis-Platform/backend
    ../.venv/bin/python scripts/liquidity_gate_forensics.py DGCB
"""
import json
import os
import sys
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
    return os.environ["MONGO_URL"], os.environ["DB_NAME"]


VOL_KEYS = ("vol", "adv", "rvol", "liquid", "dollar", "shares", "float")


def _highlight(doc):
    """Pull keys that look volume/liquidity related."""
    out = {}
    for k, v in doc.items():
        kl = k.lower()
        if any(t in kl for t in VOL_KEYS):
            out[k] = v
    return out


def _dump(doc, label):
    print(f"\n── {label} ──")
    if not doc:
        print("  (none found)")
        return
    vk = _highlight(doc)
    print("  VOLUME/LIQUIDITY fields:")
    if vk:
        for k, v in sorted(vk.items()):
            print(f"      {k:28s} = {v}")
    else:
        print("      (no vol/adv/rvol keys present on this doc!)")
    keys = ", ".join(sorted(doc.keys()))
    print(f"  all keys: {keys}")


def main():
    if len(sys.argv) < 2:
        print("usage: liquidity_gate_forensics.py SYMBOL")
        sys.exit(1)
    sym = sys.argv[1].upper()
    mongo_url, db_name = _load_env()
    from pymongo import MongoClient
    db = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)[db_name]

    cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    print("=" * 74)
    print(f"LIQUIDITY-GATE FORENSICS — {sym}   ({db_name})   since {cutoff[:10]}")
    print("INTRADAY_THRESHOLD=$50M  SWING=$10M  INVESTMENT=$2M  RVOL_floor=0.8x")
    print("=" * 74)

    # alerts
    alerts = list(db["live_alerts"].find(
        {"symbol": sym}, {"_id": 0}).sort("created_at", -1).limit(5)) \
        if "live_alerts" in db.list_collection_names() else []
    if not alerts:
        # some builds key alerts differently — try a broad recent scan
        alerts = list(db["live_alerts"].find({"symbol": sym}, {"_id": 0}).limit(5))
    print(f"\nlive_alerts for {sym}: {len(alerts)} found")
    for i, a in enumerate(alerts[:3]):
        _dump(a, f"ALERT #{i+1}  (setup={a.get('setup_type')}, "
                 f"priority={a.get('priority')}, source={a.get('source')}, "
                 f"created={a.get('created_at')})")

    # trades
    trades = list(db["bot_trades"].find({"symbol": sym}, {"_id": 0}).limit(5))
    print(f"\nbot_trades for {sym}: {len(trades)} found")
    for i, t in enumerate(trades[:3]):
        _dump(t, f"TRADE #{i+1}  (setup={t.get('setup_type')}, "
                 f"shares={t.get('shares')}, source={t.get('source')}, "
                 f"status={t.get('status')}, close={t.get('close_reason')})")

    print("\n" + "=" * 74)
    print("READ THIS: if a vol/adv field is >= 50,000,000 the gate saw it as $50M+ liquid")
    print("(bad data). If it's a small SHARE count (e.g. 80,000) compared against a $50M")
    print("DOLLAR threshold, it's a UNITS MISMATCH. If alerts have NO vol fields at all,")
    print("the ORB came from a code path that never populated/checked liquidity.")
    print("=" * 74)


if __name__ == "__main__":
    main()
