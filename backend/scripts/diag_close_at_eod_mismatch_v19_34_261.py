"""
diag_close_at_eod_mismatch_v19_34_261.py
─────────────────────────────────────────────────────────────────────────────
Reports (and optionally backfills) OPEN bot_trades whose STORED `close_at_eod`
disagrees with the trade-style POLICY (`should_close_at_eod`).

Context: v19.34.245 made the EOD close decision read the policy, and brackets
already derive their TIF from the same policy — so the stored `close_at_eod`
attribute is now largely vestigial. But a few guards historically read it
(now fixed in v19.34.261 to use the policy). This script surfaces any live
divergence so the data is clean for the UI / stats / morning-readiness.

REPORT-ONLY by default. Pass --apply to backfill stored close_at_eod = policy
on currently OPEN/PARTIAL trades.

    cd ~/Trading-and-Analysis-Platform/backend
    python3 scripts/diag_close_at_eod_mismatch_v19_34_261.py          # report
    python3 scripts/diag_close_at_eod_mismatch_v19_34_261.py --apply  # backfill
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_env(path):
    if not os.path.exists(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from pymongo import MongoClient  # type: ignore
from services.order_policy_registry import should_close_at_eod, get_policy_for_trade  # type: ignore

APPLY = "--apply" in sys.argv

db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

open_trades = list(
    db["bot_trades"].find(
        {"status": {"$in": ["open", "OPEN", "partial", "PARTIAL"]}},
        {"_id": 1, "symbol": 1, "trade_style": 1, "setup_type": 1,
         "close_at_eod": 1, "status": 1},
    )
)

print(f"\n=== OPEN/PARTIAL trades: {len(open_trades)} ===\n")
mismatches = []
for t in open_trades:
    stored = t.get("close_at_eod")
    policy = should_close_at_eod(t)
    if stored is None or bool(stored) != bool(policy):
        mismatches.append((t, stored, policy))

if not mismatches:
    print("✅ No stored-vs-policy mismatches among open positions. Nothing to fix.")
    sys.exit(0)

print(f"{'SYMBOL':<8}{'TRADE_STYLE':<14}{'SETUP_TYPE':<22}"
      f"{'STORED':<10}{'POLICY':<10}{'RESOLVED_STYLE'}")
for t, stored, policy in mismatches:
    print(f"{(t.get('symbol') or '?'):<8}{str(t.get('trade_style') or '(none)'):<14}"
          f"{str(t.get('setup_type') or '(none)'):<22}{str(stored):<10}{str(policy):<10}"
          f"{get_policy_for_trade(t).style}")

print(f"\n{len(mismatches)} mismatch(es).")
if not APPLY:
    print("REPORT-ONLY. Re-run with --apply to backfill stored close_at_eod = policy.")
    sys.exit(0)

n = 0
for t, _stored, policy in mismatches:
    db["bot_trades"].update_one({"_id": t["_id"]}, {"$set": {"close_at_eod": bool(policy)}})
    n += 1
print(f"✅ Backfilled close_at_eod = policy on {n} open trade(s).")
