"""
setup_winrate_breakdown_v19_34_121.py
─────────────────────────────────────────────────────────────────────────────
Setup-by-setup win-rate, R-multiple, and net-PnL breakdown from
`alert_outcomes` over a configurable lookback window.

Output: one row per setup_type, sorted by net_pnl ascending (worst first)
so the operator sees which setups are bleeding the account.

Run on the DGX:
    cd ~/Trading-and-Analysis-Platform/backend
    MONGO_URL=mongodb://localhost:27017 DB_NAME=tradecommand \
        python3 scripts/setup_winrate_breakdown_v19_34_121.py
    # default: last 30 days

    # or specify lookback:
    python3 scripts/setup_winrate_breakdown_v19_34_121.py --days 7

Critical for triage: if a setup has WR < 30% across 20+ samples, disable it
in `_enabled_setups` until tape-replay confirms an edge.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="Lookback window")
    ap.add_argument("--min-samples", type=int, default=3, help="Hide setups with fewer trades")
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "tradecommand")
    if not mongo_url:
        print("ERROR: MONGO_URL not set.")
        sys.exit(1)

    from pymongo import MongoClient
    client = MongoClient(mongo_url)
    db = client[db_name]

    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    cursor = db.alert_outcomes.find(
        {"closed_at": {"$gte": cutoff}},
        {
            "_id": 0, "setup_type": 1, "direction": 1, "outcome": 1,
            "pnl": 1, "r_multiple": 1, "trade_grade": 1, "closed_at": 1,
        },
    )

    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    total_rows = 0
    for row in cursor:
        st = (row.get("setup_type") or "<missing>").lower()
        # Normalize direction-suffixed variants so `mean_reversion_long` and
        # `mean_reversion_short` aggregate together (we want SETUP edge,
        # not per-direction-cell edge here).
        for suffix in ("_long", "_short", "_confirmed"):
            if st.endswith(suffix):
                st = st[: -len(suffix)]
                break
        buckets[st].append(row)
        total_rows += 1

    print(f"\n=== Setup performance · last {args.days} days · {total_rows} closed alerts ===\n")
    print(f"{'setup_type':<28} {'n':>5} {'WR':>6} {'R/trade':>9} {'net_PnL':>12} {'verdict':<14}")
    print("─" * 80)

    rows = []
    for setup, items in buckets.items():
        n = len(items)
        if n < args.min_samples:
            continue
        wins = sum(1 for r in items if (r.get("pnl") or 0) > 0)
        losses = sum(1 for r in items if (r.get("pnl") or 0) < 0)
        wr = wins / n if n else 0.0
        net = sum(float(r.get("pnl") or 0) for r in items)
        r_mults = [float(r.get("r_multiple") or 0) for r in items if r.get("r_multiple") is not None]
        avg_r = (sum(r_mults) / len(r_mults)) if r_mults else 0.0
        if wr < 0.25 and n >= 5:
            verdict = "🔴 KILL"
        elif wr < 0.35 and net < 0:
            verdict = "🟡 review"
        elif wr >= 0.55 and net > 0:
            verdict = "🟢 keep"
        else:
            verdict = "⚪ neutral"
        rows.append({
            "setup": setup, "n": n, "wins": wins, "losses": losses,
            "wr": wr, "avg_r": avg_r, "net": net, "verdict": verdict,
        })

    # Worst PnL first — operator scans the top of the list for offenders.
    rows.sort(key=lambda r: r["net"])
    for r in rows:
        print(
            f"{r['setup']:<28} {r['n']:>5d} {r['wr']*100:>5.1f}% "
            f"{r['avg_r']:>+8.2f}R ${r['net']:>+11,.0f} {r['verdict']:<14}"
        )

    print()
    n_kill = sum(1 for r in rows if r["verdict"].startswith("🔴"))
    n_review = sum(1 for r in rows if r["verdict"].startswith("🟡"))
    print(f"Summary: {n_kill} setup(s) flagged KILL · {n_review} flagged REVIEW · {len(rows)} total setups with ≥{args.min_samples} samples")
    print()
    if n_kill:
        print("KILL candidates → disable these in `_enabled_setups`:")
        for r in rows:
            if r["verdict"].startswith("🔴"):
                print(f"  - {r['setup']}  ({r['wins']}W / {r['losses']}L, "
                      f"WR {r['wr']*100:.1f}%, net ${r['net']:,.0f})")
        print()


if __name__ == "__main__":
    main()
