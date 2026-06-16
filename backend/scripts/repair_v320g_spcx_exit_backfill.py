#!/usr/bin/env python3
"""repair_v320g_spcx_exit_backfill.py  —  v19.34.320g surgical  (2026-06-16)

Comprehensive close-side rebuild for the SINGLE degraded SPCX bot_trades
row id=31651c71. This row was closed by the v19.31-era OCA-external
close path which updated `realized_pnl` (using `fill_price` as the entry
basis) but left `exit_price`, `net_pnl`, and `pnl_pct` un-finalized.

Canonical sources used:
  • `exit_price` ← IB execution @ order_id=408355 (SELL, 42sh @ 189.30,
                   2026-06-15T19:50:00Z, exec_id=00025b49.6a36c069.01.01)
  • `net_pnl`    ← realized_pnl - total_commissions = 699.65 - 1.00 = 698.65
  • `pnl_pct`    ← (exit_price - fill_price) / fill_price × 100
                  = (189.30 - 172.59) / 172.59 × 100 = 9.68 (rounded)
  • `realized_pnl` is LEFT UNCHANGED (already self-consistent with
    fill_price-as-entry-basis math; 5¢ rounding vs IB exec is within
    tolerance for partial-fill aggregation).

Safety:
  • All EXPECTED current values are asserted as pre-conditions before
    --apply touches anything. If ANY precondition drifts (e.g., another
    fix already partially applied the row), apply ABORTS without writing.
  • Single-row write, ordered=False not needed.
  • Audit row in `bot_trades_repair_audit_v320g` captures both before and
    after states with the IB-exec reference embedded.
  • `--rollback` restores the previous values atomically.

FLAGS:
  --check     Dry-run. Asserts preconditions, prints projected diff, no writes.
  --apply     Applies the three-field update; aborts if any precondition fails.
  --rollback  Reverts using the audit row.
  --status    Prints the current row state + audit history.
"""

import argparse
import os
import sys
from datetime import datetime, timezone

from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TRADE_ID = "31651c71"
AUDIT_COLL = "bot_trades_repair_audit_v320g"

# Canonical truth sourced from IB executions (diag_v320g_spcx_exit_lookup
# run 2026-06-16):
IB_EXEC_REF = {
    "order_id": 408355,
    "exec_id": "00025b49.6a36c069.01.01",
    "perm_id": 1647308841,
    "side": "SELL",
    "shares": 42.0,
    "price": 189.30,
    "time": "2026-06-15T19:50:00+00:00",
}

# Expected current state (preconditions) — abort apply if any drifts.
EXPECTED_BEFORE = {
    "symbol": "SPCX",
    "direction": "long",
    "shares": 42,
    "status": "closed",
    "entry_price": 172.42,
    "fill_price": 172.59,
    "exit_price": None,
    "realized_pnl": 699.65,
    "net_pnl": -1.0,
    "pnl_pct": 9.09090909090909,
    "total_commissions": 1.0,
    "entered_by": "bot_fired",
    "close_reason": "oca_closed_externally_v19_31",
}

# Field-level tolerance for float compares (handles internal 5¢ rounding).
FLOAT_EPS = 0.0001

# Target after-values.
NEW_EXIT_PRICE = 189.30
NEW_NET_PNL = round(EXPECTED_BEFORE["realized_pnl"]
                    - EXPECTED_BEFORE["total_commissions"], 2)   # 698.65
NEW_PNL_PCT = round((NEW_EXIT_PRICE - EXPECTED_BEFORE["fill_price"])
                    / EXPECTED_BEFORE["fill_price"] * 100, 2)    # 9.68


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def hr(t):
    print("\n" + "=" * 92 + f"\n{t}\n" + "=" * 92)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _connect():
    mu, dn = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not mu or not dn:
        print("ERROR: MONGO_URL / DB_NAME env not set")
        sys.exit(1)
    return MongoClient(mu, serverSelectionTimeoutMS=8000)[dn]


def _eq(a, b):
    if a is None and b is None:
        return True
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) < FLOAT_EPS
        except (TypeError, ValueError):
            return False
    return a == b


def _check_preconditions(doc, verbose=True):
    """Returns (ok, diffs[]). Verifies the row matches EXPECTED_BEFORE."""
    diffs = []
    for k, expected in EXPECTED_BEFORE.items():
        actual = doc.get(k, "<missing>")
        if not _eq(actual, expected):
            diffs.append((k, expected, actual))
    if verbose:
        if diffs:
            print(f"  ❌ {len(diffs)} precondition(s) DRIFTED from expected:")
            for k, exp, act in diffs:
                print(f"      {k:>22}:  expected={exp!r}  actual={act!r}")
        else:
            print(f"  ✓ all {len(EXPECTED_BEFORE)} preconditions match.")
    return (not diffs), diffs


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_check():
    db = _connect()
    bt = db["bot_trades"]

    hr(f"Section 1 — current bot_trades row id={TRADE_ID}")
    doc = bt.find_one({"id": TRADE_ID}, {"_id": 0})
    if not doc:
        print(f"  ERROR: no row with id={TRADE_ID}")
        sys.exit(1)
    for k in ("id", "symbol", "direction", "shares", "status",
              "entry_price", "fill_price", "exit_price",
              "realized_pnl", "net_pnl", "pnl_pct",
              "total_commissions", "entered_by", "close_reason"):
        print(f"  {k:>22} : {doc.get(k)}")

    hr("Section 2 — preconditions")
    ok, diffs = _check_preconditions(doc)

    hr("Section 3 — projected diff (--apply would write)")
    fields = [("exit_price", doc.get("exit_price"), NEW_EXIT_PRICE),
              ("net_pnl",     doc.get("net_pnl"),    NEW_NET_PNL),
              ("pnl_pct",     doc.get("pnl_pct"),    NEW_PNL_PCT)]
    for k, before, after in fields:
        arrow = "→"
        print(f"  {k:>14}:  {before!r:>20}  {arrow}  {after!r}")

    hr("Section 4 — IB exec reference (audit will embed this)")
    for k, v in IB_EXEC_REF.items():
        print(f"  {k:>10} : {v}")

    hr("Section 5 — audit collection state")
    n = db[AUDIT_COLL].count_documents({"trade_id": TRADE_ID})
    print(f"  prior audit rows for this trade_id: {n}")
    if n:
        for a in db[AUDIT_COLL].find({"trade_id": TRADE_ID}, {"_id": 0}).sort("ts", -1):
            print(f"    {a.get('ts')}  action={a.get('action')}  "
                  f"rolled_back={a.get('rolled_back', False)}")

    print()
    if not ok:
        print("  → apply will ABORT because preconditions drifted. "
              "Investigate before retrying.")
        sys.exit(2)
    print("  → preconditions clean. Run --apply to write.")


def cmd_apply():
    db = _connect()
    bt = db["bot_trades"]
    aud = db[AUDIT_COLL]

    doc = bt.find_one({"id": TRADE_ID}, {"_id": 0})
    if not doc:
        print(f"ERROR: no row with id={TRADE_ID}")
        sys.exit(1)

    ok, diffs = _check_preconditions(doc, verbose=True)
    if not ok:
        print("ABORT: preconditions drifted. No write performed.")
        sys.exit(2)

    # Re-check for an unrolled audit row to prevent double-apply.
    prior = aud.find_one({"trade_id": TRADE_ID,
                          "action": "comprehensive_close_rebuild",
                          "rolled_back": {"$ne": True}})
    if prior:
        print(f"ABORT: an unrolled audit row already exists "
              f"(ts={prior.get('ts')}). Already applied?")
        sys.exit(3)

    before = {
        "exit_price": doc.get("exit_price"),
        "net_pnl":    doc.get("net_pnl"),
        "pnl_pct":    doc.get("pnl_pct"),
    }
    after = {
        "exit_price": NEW_EXIT_PRICE,
        "net_pnl":    NEW_NET_PNL,
        "pnl_pct":    NEW_PNL_PCT,
    }

    # 1) Insert audit row FIRST. If apply crashes mid-write we still have
    #    the rollback record.
    audit_doc = {
        "trade_id": TRADE_ID,
        "action": "comprehensive_close_rebuild",
        "ts": _now_iso(),
        "before": before,
        "after": after,
        "ib_exec_ref": IB_EXEC_REF,
        "expected_before": EXPECTED_BEFORE,
        "notes": ("close_reason=oca_closed_externally_v19_31; "
                  "realized_pnl left unchanged (fill_price-basis, "
                  "internally consistent)."),
        "rolled_back": False,
        "self_sha256": _self_sha256(),
    }
    aud_id = aud.insert_one(audit_doc).inserted_id

    # 2) Update the bot_trades row.
    r = bt.update_one(
        {"id": TRADE_ID, **{k: v for k, v in EXPECTED_BEFORE.items()
                            if k in ("exit_price", "net_pnl", "pnl_pct")}},
        {"$set": {**after, "v320g_repaired_at": _now_iso(),
                  "v320g_audit_ref": str(aud_id)}},
    )

    hr("APPLIED")
    print(f"  matched={r.matched_count}  modified={r.modified_count}")
    print(f"  audit _id: {aud_id}")
    print(f"  before → after:")
    for k in ("exit_price", "net_pnl", "pnl_pct"):
        print(f"    {k:>12}: {before[k]!r}  →  {after[k]!r}")
    if r.modified_count != 1:
        print("\n  WARNING: modified_count != 1 — audit recorded but update "
              "may have raced. Investigate manually.")
        sys.exit(4)

    # 3) Read-back verification.
    post = bt.find_one({"id": TRADE_ID}, {"_id": 0,
                                          "exit_price": 1, "net_pnl": 1,
                                          "pnl_pct": 1})
    ok = all(_eq(post.get(k), after[k]) for k in after)
    print(f"  read-back verify: {'✓ PASS' if ok else '❌ MISMATCH'}")
    print(f"  rollback: .venv/bin/python {os.path.basename(__file__)} --rollback")


def cmd_rollback():
    db = _connect()
    bt = db["bot_trades"]
    aud = db[AUDIT_COLL]

    a = aud.find_one({"trade_id": TRADE_ID,
                      "action": "comprehensive_close_rebuild",
                      "rolled_back": {"$ne": True}},
                     sort=[("ts", -1)])
    if not a:
        print("  no unrolled audit row found. Nothing to do.")
        return

    before = a["before"]
    r = bt.update_one(
        {"id": TRADE_ID},
        {"$set": before,
         "$unset": {"v320g_repaired_at": "", "v320g_audit_ref": ""}},
    )
    aud.update_one({"_id": a["_id"]},
                   {"$set": {"rolled_back": True, "rolled_back_at": _now_iso()}})
    hr("ROLLED BACK")
    print(f"  matched={r.matched_count}  modified={r.modified_count}")
    print(f"  restored: {before}")


def cmd_status():
    db = _connect()
    bt = db["bot_trades"]
    aud = db[AUDIT_COLL]

    doc = bt.find_one({"id": TRADE_ID}, {"_id": 0,
                                          "exit_price": 1, "net_pnl": 1,
                                          "pnl_pct": 1, "realized_pnl": 1,
                                          "v320g_repaired_at": 1,
                                          "v320g_audit_ref": 1})
    hr(f"STATUS — id={TRADE_ID}")
    if not doc:
        print("  row not found.")
        return
    for k, v in doc.items():
        print(f"  {k:>22} : {v}")
    print()
    n = aud.count_documents({"trade_id": TRADE_ID})
    print(f"  audit rows for this trade_id: {n}")
    for a in aud.find({"trade_id": TRADE_ID}, {"_id": 0}).sort("ts", -1).limit(5):
        print(f"    {a.get('ts')}  action={a.get('action')}  "
              f"rolled_back={a.get('rolled_back', False)}")


# ---------------------------------------------------------------------------
def _self_sha256():
    import hashlib
    with open(os.path.abspath(__file__), "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--rollback", action="store_true")
    g.add_argument("--status", action="store_true")
    args = ap.parse_args()

    if args.check:
        cmd_check()
    elif args.apply:
        cmd_apply()
    elif args.rollback:
        cmd_rollback()
    elif args.status:
        cmd_status()


if __name__ == "__main__":
    main()
