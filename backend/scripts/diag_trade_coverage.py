#!/usr/bin/env python3
"""
diag_trade_coverage.py  —  v19.34.311  (2026-06-10)   READ-ONLY

Answers two questions before we act on the EV finding:
  1) Is the 119 gate-tracked outcomes a biased subset, or ~all real trades?
     -> compares to closed `bot_trades` in the same window.
  2) Ground-truth P&L: is the bot actually net-losing, or is the 119-subset
     skewed?  -> sums realized P&L straight from bot_trades (the canonical
     execution record), bucketed by win/loss, vs the gate-log subset.

Run:
    cd ~/Trading-and-Analysis-Platform && \
      .venv/bin/python backend/scripts/diag_trade_coverage.py
"""
import os
import sys
from collections import Counter
from datetime import datetime, timezone

from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")


def hr(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    if not MONGO_URL or not DB_NAME:
        print("ERROR: MONGO_URL / DB_NAME not set in backend/.env")
        sys.exit(1)
    db = MongoClient(MONGO_URL, serverSelectionTimeoutMS=8000)[DB_NAME]

    # ---- 1) closed bot_trades = canonical execution truth ----
    hr("1) BOT_TRADES — closed-trade population & ground-truth P&L")
    bt = db["bot_trades"]
    closed = list(bt.find(
        {"status": "closed"},
        {"_id": 0, "symbol": 1, "setup_type": 1, "entered_by": 1,
         "realized_pnl": 1, "net_pnl": 1, "pnl": 1, "closed_at": 1},
    ))
    print(f"  total closed bot_trades: {len(closed):,}")

    # pnl field varies by vintage — prefer net_pnl, then realized_pnl, then pnl
    def pnl_of(t):
        for k in ("net_pnl", "realized_pnl", "pnl"):
            v = _num(t.get(k))
            if v is not None:
                return v
        return 0.0

    wins = [t for t in closed if pnl_of(t) > 0]
    losses = [t for t in closed if pnl_of(t) < 0]
    flats = [t for t in closed if pnl_of(t) == 0]
    tot_pnl = sum(pnl_of(t) for t in closed)
    n = len(closed) or 1
    print(f"  win/loss/flat: {len(wins)}/{len(losses)}/{len(flats)}  "
          f"(win-rate {100*len(wins)/n:.1f}%)")
    print(f"  TOTAL realized P&L (bot_trades): {tot_pnl:+,.2f}  "
          f"avg/trade {tot_pnl/n:+.2f}")

    # exclude edge artifacts (reconciled_*/imported/watchlist) for a clean read
    def genuine(t):
        eb = str(t.get("entered_by", "")).lower()
        return not (eb.startswith("reconciled") or eb in ("imported_from_ib", "watchlist", "manual"))
    gen = [t for t in closed if genuine(t)]
    gpnl = sum(pnl_of(t) for t in gen)
    gn = len(gen) or 1
    gw = sum(1 for t in gen if pnl_of(t) > 0)
    print(f"  GENUINE (bot_fired) only: {len(gen)} trades  "
          f"win-rate {100*gw/gn:.1f}%  P&L {gpnl:+,.2f}  avg {gpnl/gn:+.2f}")

    # entered_by breakdown
    eb_dist = Counter(str(t.get("entered_by", "?")) for t in closed)
    print("  entered_by breakdown:")
    for k, v in eb_dist.most_common():
        print(f"     {k:>26}: {v:,}")

    # ---- 2) coverage: gate-tracked vs closed trades ----
    hr("2) COVERAGE — gate outcome-tracking vs closed trades")
    cg = db["confidence_gate_log"]
    tracked = cg.count_documents({"outcome_tracked": True})
    gate_total = cg.count_documents({})
    print(f"  confidence_gate_log total decisions : {gate_total:,}")
    print(f"  confidence_gate_log outcome_tracked : {tracked:,}")
    print(f"  closed bot_trades (all)             : {len(closed):,}")
    print(f"  closed bot_trades (genuine)         : {len(gen):,}")
    if len(gen):
        print(f"  => gate sees outcomes for ~{100*tracked/max(1,len(gen)):.0f}% "
              f"of genuine closed trades")
    print("  (NOTE: gate_total is inflated by per-scan-tick re-evaluations of the")
    print("   same alert — it is NOT the trade-opportunity count.)")

    # ---- 3) gate-tracked subset P&L (the 119) for comparison ----
    hr("3) GATE-TRACKED SUBSET vs FULL — is the 119 biased?")
    sub = list(cg.find({"outcome_tracked": True},
                       {"_id": 0, "trade_outcome": 1, "outcome_pnl": 1}))
    spnl = sum(_num(d.get("outcome_pnl")) or 0 for d in sub)
    sw = sum(1 for d in sub if str(d.get("trade_outcome")).lower() in ("win", "won"))
    sn = len(sub) or 1
    print(f"  gate-tracked subset: {len(sub)} trades  "
          f"win-rate {100*sw/sn:.1f}%  P&L {spnl:+,.2f}  avg {spnl/sn:+.2f}")
    print(f"  full bot_trades:     {len(closed)} trades  "
          f"win-rate {100*len(wins)/n:.1f}%  P&L {tot_pnl:+,.2f}  avg {tot_pnl/n:+.2f}")
    print("\n  If the two rows disagree sharply, the 119 is a biased sample and the")
    print("  EV-tightening conclusion needs the FULL bot_trades set, not the gate log.")

    print("\nDONE.  (Nothing was written.)\n")


if __name__ == "__main__":
    main()
