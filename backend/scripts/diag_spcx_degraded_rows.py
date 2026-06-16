#!/usr/bin/env python3
"""diag_spcx_degraded_rows.py  —  READ-ONLY  (2026-06-16, v320g prep)

Pinpoints the SPCX `bot_trades` rows that are *actually* degraded after
the fleet-wide schema audit (diag_bot_trades_schema_audit.py) proved
the v1 schema rename ("entry_time" → "created_at", etc.) is NOT a
degradation. We expect a small number of specific EOD rows to be
missing isolated execution fields.

Approach (no writes):
  1. Build a canonical key-set from the most-recent CLOSED bot_trades
     doc (post-rename schema, len(keys) ~= 70). This is the SCHEMA SSOT.
  2. For every SPCX doc (CLOSED or OPEN), compute:
       missing_keys   = canonical_keys - doc_keys
       empty_keys     = keys present but value in {None, "", [], {}, 0.0}
                        for the small subset of fields we EXPECT to be
                        non-empty on a fully-reconciled close
                        (entry_price, exit_price, fill_price, shares,
                        realized_pnl, executed_at, closed_at, exit_order_id?)
  3. Group rows by their missing-field pattern so the surgical repair
     can be designed once per pattern (not per row).
  4. For each degraded EOD row, surface the timestamps the operator
     needs to cross-ref against IB executions:
         created_at, executed_at, closed_at, symbol, direction, shares
"""

import os
import sys
from collections import Counter, defaultdict
from datetime import datetime

from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass


SYMBOL = "SPCX"

# Fields we REQUIRE to be non-empty for a CLOSED EOD trade row to be
# considered "fully reconciled" (post-v19.34.6 schema).
REQUIRED_NONEMPTY_ON_CLOSE = (
    "symbol", "direction", "shares", "entry_price", "exit_price",
    "fill_price", "executed_at", "closed_at", "realized_pnl",
    "net_pnl", "entry_order_id", "stop_order_id", "status",
)

# Subset of fields whose absence is OK on intentionally-degraded rows
# (e.g., synthetic / reconciled-only trades). We don't flag these.
SOFT_OPTIONAL = (
    "synthetic_source", "etf_class", "is_etf", "target_order_ids",
    "scale_out_config", "trailing_stop_config", "explanation",
    "entry_context", "prior_verdicts", "prior_verdict_conflict",
)


def hr(t):
    print("\n" + "=" * 92 + f"\n{t}\n" + "=" * 92)


def _is_empty(v):
    if v is None:
        return True
    if isinstance(v, str) and v.strip() == "":
        return True
    if isinstance(v, (list, dict, tuple)) and len(v) == 0:
        return True
    if isinstance(v, (int, float)) and v == 0 and not isinstance(v, bool):
        # Zero is suspicious only on price/PnL/share fields — caller filters.
        return True
    return False


def _trim(s, n=22):
    if not isinstance(s, str):
        return str(s)
    return s if len(s) <= n else s[:n - 1] + "…"


def main():
    mu, dn = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not mu or not dn:
        print("ERROR: MONGO_URL / DB_NAME env not set")
        sys.exit(1)
    db = MongoClient(mu, serverSelectionTimeoutMS=8000)[dn]
    bt = db["bot_trades"]

    # 1. Canonical schema from most-recent closed doc (any symbol).
    canon = bt.find_one({"status": "closed",
                         "exit_price": {"$exists": True, "$ne": None}},
                        sort=[("closed_at", -1)])
    if not canon:
        print("ERROR: no closed canonical doc found in bot_trades.")
        sys.exit(1)
    canon_keys = set(canon.keys()) - {"_id"}
    print(f"Canonical schema sourced from doc id={canon.get('id')} "
          f"(symbol={canon.get('symbol')}, closed_at={canon.get('closed_at')}). "
          f"{len(canon_keys)} keys.")

    # 2. SPCX universe.
    n_spcx_all = bt.count_documents({"symbol": SYMBOL})
    n_spcx_closed = bt.count_documents({"symbol": SYMBOL, "status": "closed"})
    n_spcx_open = bt.count_documents({"symbol": SYMBOL, "status": "open"})
    hr(f"Section 1 — {SYMBOL} population")
    print(f"  total bot_trades for {SYMBOL}: {n_spcx_all:,}")
    print(f"   - closed: {n_spcx_closed:,}")
    print(f"   - open  : {n_spcx_open:,}")
    if n_spcx_all == 0:
        print("\n  Nothing to audit.")
        return

    rows = list(bt.find({"symbol": SYMBOL}).sort("closed_at", -1))

    # 3. Per-row missing-key audit.
    pattern_groups = defaultdict(list)   # missing-key-tuple → [rows]
    empty_flags_by_row = []              # [(row, [empty_field, ...])]
    fully_clean = 0

    for doc in rows:
        doc_keys = set(doc.keys()) - {"_id"}
        missing = canon_keys - doc_keys - set(SOFT_OPTIONAL)
        empties = []
        for f in REQUIRED_NONEMPTY_ON_CLOSE:
            if f not in doc:
                continue  # already counted in `missing`
            v = doc.get(f)
            # zero-PnL is legal; only flag zero on price/share fields.
            if f in ("realized_pnl", "net_pnl"):
                if v is None:
                    empties.append(f)
            elif f in ("shares",):
                if v is None or v == 0:
                    empties.append(f)
            elif f in ("entry_price", "exit_price", "fill_price"):
                if v is None or v == 0:
                    empties.append(f)
            else:
                if _is_empty(v):
                    empties.append(f)

        if doc.get("status") != "closed":
            # Open trades are not degraded; just count missing-pattern for
            # signal but skip in the empty-flag report.
            pattern_groups[tuple(sorted(missing))].append(doc)
            continue

        if not missing and not empties:
            fully_clean += 1
        else:
            pattern_groups[tuple(sorted(missing))].append(doc)
            if empties:
                empty_flags_by_row.append((doc, empties))

    hr(f"Section 2 — missing-key patterns ({len(pattern_groups)} distinct)")
    print(f"  fully-clean closed rows: {fully_clean:,} / {n_spcx_closed:,}")
    if fully_clean == n_spcx_closed and not empty_flags_by_row:
        print("  ✓ No degraded SPCX rows detected. No surgical repair needed.")
        return

    for missing_keys, group in sorted(pattern_groups.items(),
                                      key=lambda kv: -len(kv[1])):
        n = len(group)
        if not missing_keys:
            label = "(no missing keys — value-emptiness flagged elsewhere)"
        else:
            label = ", ".join(missing_keys[:8])
            if len(missing_keys) > 8:
                label += f" …(+{len(missing_keys) - 8} more)"
        print(f"\n  {n:>4} rows missing: {label}")
        for d in group[:5]:
            print(f"      id={d.get('id')}  status={d.get('status'):>6}  "
                  f"created_at={_trim(d.get('created_at'))}  "
                  f"closed_at={_trim(d.get('closed_at'))}  "
                  f"shares={d.get('shares')}  "
                  f"entered_by={_trim(d.get('entered_by'),18)}")
        if n > 5:
            print(f"      …and {n - 5} more")

    hr("Section 3 — value-emptiness on REQUIRED fields (closed rows only)")
    if not empty_flags_by_row:
        print("  ✓ no empty required fields on closed rows.")
    else:
        print(f"  {len(empty_flags_by_row):,} rows have one+ empty required fields:\n")
        bucket = Counter()
        for _, empties in empty_flags_by_row:
            bucket.update(empties)
        for f, n in bucket.most_common():
            print(f"    {f:>20}  empty in {n:>4} rows")
        print("\n  first 10 degraded rows (for surgical-repair cross-ref):")
        print(f"     {'id':>10} {'created_at':>22} {'closed_at':>22} "
              f"{'dir':>5} {'shares':>6}  empty_fields")
        for d, empties in empty_flags_by_row[:10]:
            print(f"     {str(d.get('id'))[:10]:>10} "
                  f"{_trim(d.get('created_at')):>22} "
                  f"{_trim(d.get('closed_at')):>22} "
                  f"{str(d.get('direction'))[:5]:>5} "
                  f"{str(d.get('shares'))[:6]:>6}  "
                  f"{','.join(empties)}")

    hr("Surgical-repair guidance")
    print(f"  • Group by missing-pattern: {len(pattern_groups)} distinct patterns")
    print("  • Repair plan should cross-ref `ib_executions` by ")
    print(f"      (symbol={SYMBOL}, exec_time≈created_at OR closed_at, "
          f"shares match).")
    print("  • Per-pattern repair to be expressed in repair_v320g_spcx_backfill.py")
    print("    once this diag's output is committed to memory.")
    print("\nDONE.")


if __name__ == "__main__":
    main()
