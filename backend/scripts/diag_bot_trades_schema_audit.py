#!/usr/bin/env python3
"""diag_bot_trades_schema_audit.py  —  READ-ONLY  (2026-06-16)

V1 hygiene diag reported 100% missing fields. Apply VERIFY-BEFORE-CLAIM:
sample bot_trades and print the actual field distribution. Either
fields were RENAMED (cosmetic), or really MISSING (real bug).
"""
import os
import sys
from collections import Counter
from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass


def main():
    mu = os.environ.get("MONGO_URL")
    dn = os.environ.get("DB_NAME")
    if not mu or not dn:
        print("ERROR: env")
        sys.exit(1)
    db = MongoClient(mu, serverSelectionTimeoutMS=8000)[dn]
    col = db["bot_trades"]
    total = col.count_documents({})
    print(f"bot_trades total docs: {total:,}\n")

    # Field-name frequency across last 500 docs sorted by created_at desc.
    print("=" * 92)
    print("Section 1 — field-name FREQUENCY across most recent 500 docs")
    print("=" * 92)
    cnt = Counter()
    sample = list(col.find({}, {}).sort("created_at", -1).limit(500))
    for d in sample:
        for k in d.keys():
            cnt[k] += 1
    print(f"  scanned: {len(sample)} docs\n")
    print(f"  {'field':>30} {'present':>8} {'rate':>7}")
    for k, c in cnt.most_common(60):
        pct = c / len(sample) * 100
        flag = " ⚠ rare" if pct < 50 else ""
        print(f"  {k:>30} {c:>8} {pct:>6.1f}%{flag}")

    # Look for likely renames of the v1 expected fields.
    print("\n" + "=" * 92)
    print("Section 2 — RENAME hypothesis check (v1 expected → most-likely actual)")
    print("=" * 92)
    rename_candidates = {
        "entry_time": ["created_at", "opened_at", "fill_time", "entry_dt"],
        "exit_time":  ["closed_at", "close_time", "exit_dt"],
        "size":       ["quantity", "qty", "shares", "size_filled", "filled_qty"],
        "conid":      ["contract_id", "con_id", "instrument_id"],
        "pnl":        ["realized_pnl", "pnl_after_fees", "net_pnl", "gross_pnl"],
        "side":       ["direction", "action", "buy_sell"],
        "trade_id":   ["id", "_id_str", "alert_id", "order_id"],
        "strategy":   ["setup_type", "strategy_name", "pattern"],
        "exit_price": ["close_price", "fill_price_exit", "avg_exit_price"],
    }
    for orig, candidates in rename_candidates.items():
        orig_n = cnt.get(orig, 0)
        print(f"\n  '{orig}' present={orig_n}/{len(sample)} "
              f"({orig_n / len(sample) * 100:.0f}%)")
        for c in candidates:
            n = cnt.get(c, 0)
            if n > 0:
                pct = n / len(sample) * 100
                mark = " ← LIKELY RENAME" if pct > 50 else ""
                print(f"      candidate '{c}': {n} ({pct:.0f}%){mark}")

    # Full key-set dump of the most recent CLOSED doc to confirm.
    print("\n" + "=" * 92)
    print("Section 3 — Full key list from most recent CLOSED doc")
    print("=" * 92)
    recent = col.find_one({"status": {"$regex": "closed", "$options": "i"}},
                          sort=[("created_at", -1)])
    if recent:
        for k in sorted(recent.keys()):
            v = recent[k]
            vs = str(v)[:50]
            print(f"  {k:>30} : {vs}")
    print("\nDONE.\n")


if __name__ == "__main__":
    main()
