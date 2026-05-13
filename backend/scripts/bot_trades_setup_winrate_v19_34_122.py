"""
bot_trades_setup_winrate_v19_34_122.py
─────────────────────────────────────────────────────────────────────────────
Setup-by-setup win-rate, R-multiple, and net-PnL breakdown directly from
`bot_trades` (LIVE-only, PAPER excluded). Used when `alert_outcomes` is
empty (the grading subsystem isn't populating it).

Run on the DGX:
    cd ~/Trading-and-Analysis-Platform/backend
    MONGO_URL=mongodb://localhost:27017 DB_NAME=tradecommand \
        python3 scripts/bot_trades_setup_winrate_v19_34_122.py --days 30
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--min-samples", type=int, default=3)
    ap.add_argument("--include-paper", action="store_true",
                    help="Include PAPER trades (default: LIVE only)")
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL")
    if not mongo_url:
        print("ERROR: MONGO_URL not set.")
        sys.exit(1)

    from pymongo import MongoClient
    client = MongoClient(mongo_url)
    db = client[os.environ.get("DB_NAME", "tradecommand")]

    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    query = {
        "status": {"$in": ["closed", "CLOSED"]},
        "$or": [
            {"closed_at":   {"$gte": cutoff}},
            {"exit_time":   {"$gte": cutoff}},
            {"executed_at": {"$gte": cutoff}},
        ],
    }

    buckets = defaultdict(list)
    total = 0
    paper_skipped = 0
    for t in db.bot_trades.find(query, {
        "_id": 0, "setup_type": 1, "direction": 1, "net_pnl": 1,
        "realized_pnl": 1, "r_multiple": 1, "executor_mode": 1, "mode": 1,
        "closed_at": 1, "exit_time": 1,
    }):
        mode = (t.get("executor_mode") or t.get("mode") or "LIVE").upper()
        if not args.include_paper and mode == "PAPER":
            paper_skipped += 1
            continue
        st = (t.get("setup_type") or "<missing>").lower()
        for sfx in ("_long", "_short", "_confirmed"):
            if st.endswith(sfx):
                st = st[: -len(sfx)]
                break
        pnl = t.get("net_pnl")
        if pnl is None:
            pnl = t.get("realized_pnl") or 0.0
        try:
            pnl = float(pnl)
        except (TypeError, ValueError):
            pnl = 0.0
        r = t.get("r_multiple")
        try:
            r = float(r) if r is not None else None
        except (TypeError, ValueError):
            r = None
        buckets[st].append({"pnl": pnl, "r": r})
        total += 1

    print(f"\n=== bot_trades · last {args.days} days · "
          f"{total} closed{' (paper excluded: ' + str(paper_skipped) + ')' if paper_skipped else ''} ===\n")
    print(f"{'setup_type':<30} {'n':>5} {'W':>4} {'L':>4} "
          f"{'WR':>6} {'R/trade':>9} {'net_PnL':>14} {'verdict':<10}")
    print("─" * 90)

    rows = []
    for setup, items in buckets.items():
        n = len(items)
        if n < args.min_samples:
            continue
        wins = sum(1 for x in items if x["pnl"] > 0)
        losses = sum(1 for x in items if x["pnl"] < 0)
        wr = wins / n if n else 0.0
        net = sum(x["pnl"] for x in items)
        rs = [x["r"] for x in items if x["r"] is not None]
        avg_r = (sum(rs) / len(rs)) if rs else 0.0
        if wr < 0.25 and n >= 5:
            verdict = "🔴 KILL"
        elif wr < 0.35 and net < 0:
            verdict = "🟡 review"
        elif wr >= 0.55 and net > 0:
            verdict = "🟢 keep"
        else:
            verdict = "⚪ neutral"
        rows.append((setup, n, wins, losses, wr, avg_r, net, verdict))

    rows.sort(key=lambda r: r[6])
    for setup, n, w, l, wr, avg_r, net, verdict in rows:
        print(f"{setup:<30} {n:>5d} {w:>4d} {l:>4d} "
              f"{wr*100:>5.1f}% {avg_r:>+8.2f}R ${net:>+12,.0f} {verdict}")

    print()
    kills = [r[0] for r in rows if r[7].startswith("🔴")]
    reviews = [r[0] for r in rows if r[7].startswith("🟡")]
    keeps = [r[0] for r in rows if r[7].startswith("🟢")]
    print(f"Summary: {len(kills)} KILL · {len(reviews)} REVIEW · {len(keeps)} KEEP · {len(rows)} total")
    if kills:
        print(f"\n🔴 KILL list (disable in _enabled_setups): {', '.join(kills)}")
    if reviews:
        print(f"🟡 REVIEW list: {', '.join(reviews)}")
    if keeps:
        print(f"🟢 KEEP list: {', '.join(keeps)}")
    print()


if __name__ == "__main__":
    main()
