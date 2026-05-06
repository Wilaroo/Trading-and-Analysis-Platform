"""
Zombie root-cause spot-check (READ-ONLY).

Purpose: verify that the upstream zombie creator is `_shrink_drift_trades`
(v19.34.15b LIFO peel) by counting how many of the existing zombies
(`remaining_shares: 0` AND `status: OPEN`) carry the
`'v19.34.15b: shrunk'` token in their `notes`.

Run from DGX:
    cd ~/Trading-and-Analysis-Platform/backend
    python3 scripts/zombie_root_cause_spotcheck.py

Mutates nothing. Pure SELECT.
"""
import os
import json
import sys
from collections import Counter, defaultdict

from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")
if not MONGO_URL or not DB_NAME:
    print("ERROR: MONGO_URL / DB_NAME not set in env.")
    sys.exit(1)

db = MongoClient(MONGO_URL)[DB_NAME]

PROJ = {
    "_id": 0,
    "id": 1,
    "symbol": 1,
    "direction": 1,
    "shares": 1,
    "remaining_shares": 1,
    "status": 1,
    "notes": 1,
    "close_reason": 1,
    "entered_by": 1,
    "setup_type": 1,
    "executed_at": 1,
    "closed_at": 1,
    "fill_price": 1,
}

# Status comparison handles both string ("OPEN") and enum-stamped ("TradeStatus.OPEN").
zombies = list(
    db.bot_trades.find(
        {
            "remaining_shares": 0,
            "$or": [
                {"status": "OPEN"},
                {"status": "TradeStatus.OPEN"},
            ],
        },
        PROJ,
    )
)

total = len(zombies)
shrunk = [z for z in zombies if "v19.34.15b: shrunk" in (z.get("notes") or "")]
not_shrunk = [z for z in zombies if z not in shrunk]

print("=" * 72)
print(f"TOTAL ZOMBIES (rs=0, status=OPEN)            : {total}")
print(f"  ↳ carry 'v19.34.15b: shrunk' in notes      : {len(shrunk)}")
print(f"  ↳ NO 15b-shrunk token (other upstream?)    : {len(not_shrunk)}")
if total:
    pct = 100.0 * len(shrunk) / total
    print(f"  ↳ confirmation pct                         : {pct:.1f}%")
print("=" * 72)

# Per-symbol breakdown
by_sym = defaultdict(lambda: {"total": 0, "shrunk": 0, "shares": 0})
for z in zombies:
    sym = (z.get("symbol") or "?").upper()
    by_sym[sym]["total"] += 1
    by_sym[sym]["shares"] += int(z.get("shares") or 0)
    if "v19.34.15b: shrunk" in (z.get("notes") or ""):
        by_sym[sym]["shrunk"] += 1

print("\nPER-SYMBOL BREAKDOWN:")
print(f"{'symbol':<8} {'zombies':>8} {'shrunk-flagged':>16} {'orig-shares-sum':>18}")
for sym, st in sorted(by_sym.items(), key=lambda kv: -kv[1]["total"]):
    print(f"{sym:<8} {st['total']:>8} {st['shrunk']:>16} {st['shares']:>18}")

# `close_reason` and `entered_by` distribution on the non-shrunk bucket —
# helps spot a second leak.
if not_shrunk:
    print("\nNON-SHRUNK ZOMBIES — close_reason distribution:")
    for k, v in Counter(z.get("close_reason") for z in not_shrunk).most_common():
        print(f"  {str(k):<40} {v}")
    print("\nNON-SHRUNK ZOMBIES — entered_by distribution:")
    for k, v in Counter(z.get("entered_by") for z in not_shrunk).most_common():
        print(f"  {str(k):<40} {v}")
    print("\nNON-SHRUNK ZOMBIES — setup_type distribution:")
    for k, v in Counter(z.get("setup_type") for z in not_shrunk).most_common():
        print(f"  {str(k):<40} {v}")

# First 10 raw rows (each bucket) for eyeballing.
print("\n--- SAMPLE: first 10 SHRUNK zombies ---")
for z in shrunk[:10]:
    print(json.dumps(z, default=str))

print("\n--- SAMPLE: first 10 NON-SHRUNK zombies ---")
for z in not_shrunk[:10]:
    print(json.dumps(z, default=str))

print("\nDone.")
