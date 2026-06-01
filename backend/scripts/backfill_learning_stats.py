#!/usr/bin/env python3
"""
backfill_learning_stats.py — rebuild `learning_stats` from `trade_outcomes`.

WHY: The setup pillar's win-rate (25%) + EV (20%) come from
`learning_loop.get_contextual_win_rate(setup_type=base)`, which returns the
default {win_rate: 0.5} whenever `learning_stats` has no row for that setup.
Live data showed `learning_stats` EMPTY despite 96 `trade_outcomes`, so the
setup pillar defaults to 50 for every trade → TQS compresses to C.

`run_daily_analysis` only aggregates *today's `reviewed:False`* outcomes and
clearly isn't persisting, so history never got built. This does a FULL,
idempotent rebuild from ALL outcomes.

KEY MATCH: the setup pillar normalizes setup_type as
    base = setup_type.lower().replace("_long","").replace("_short","")
and queries get_learning_stats(setup_type=base). So we aggregate by that exact
normalized key and write learning_stats with setup_type == context_key == base,
guaranteeing the pillar finds it (direction-agnostic, as the pillar intends).

Idempotent: upserts by context_key. Re-runnable any time (good stopgap until
the incremental path is hardened). Safe to schedule.

Run (DGX):
    DRY_RUN=1 .venv/bin/python backend/scripts/backfill_learning_stats.py   # preview
    .venv/bin/python backend/scripts/backfill_learning_stats.py             # apply
"""
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

from pymongo import MongoClient

DRY = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "yes")


def normalize_setup(setup_type: str) -> str:
    """EXACTLY mirror SetupQualityService normalization so the win-rate the
    pillar queries matches what we write."""
    return (setup_type or "").lower().replace("_long", "").replace("_short", "")


def calc_stats(outcomes):
    """Pure-python mirror of LearningStats.calculate_stats — only the fields
    get_contextual_win_rate / the setup pillar read, plus useful extras."""
    n = len(outcomes)
    wins = sum(1 for o in outcomes if o.get("outcome") == "won")
    losses = sum(1 for o in outcomes if o.get("outcome") == "lost")
    breakeven = sum(1 for o in outcomes if o.get("outcome") == "breakeven")
    decided = wins + losses
    win_rate = wins / decided if decided > 0 else 0.0

    def _r(o):
        try:
            return float(o.get("actual_r") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _pnl(o):
        try:
            return float(o.get("pnl") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    win_rs = [_r(o) for o in outcomes if o.get("outcome") == "won" and _r(o) > 0]
    loss_rs = [abs(_r(o)) for o in outcomes if o.get("outcome") == "lost"]
    avg_win_r = sum(win_rs) / len(win_rs) if win_rs else 0.0
    avg_loss_r = sum(loss_rs) / len(loss_rs) if loss_rs else 1.0
    total_r = sum(_r(o) for o in outcomes)
    avg_r = total_r / n if n else 0.0
    ev_r = (win_rate * avg_win_r) - ((1 - win_rate) * avg_loss_r)
    gross_profit = sum(_pnl(o) for o in outcomes if _pnl(o) > 0)
    gross_loss = abs(sum(_pnl(o) for o in outcomes if _pnl(o) < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else 0.0
    total_pnl = sum(_pnl(o) for o in outcomes)

    return {
        "total_trades": n, "wins": wins, "losses": losses, "breakeven": breakeven,
        "win_rate": round(win_rate, 4), "profit_factor": round(pf, 3),
        "total_r": round(total_r, 3), "avg_r_per_trade": round(avg_r, 3),
        "avg_win_r": round(avg_win_r, 3), "avg_loss_r": round(avg_loss_r, 3),
        "expected_value_r": round(ev_r, 3),
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(total_pnl / n, 2) if n else 0.0,
    }


def main():
    url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db = MongoClient(url, serverSelectionTimeoutMS=5000)[
        os.environ.get("DB_NAME", "tradecommand")]

    outcomes = list(db["trade_outcomes"].find({}))
    print(f"[backfill_learning_stats] {len(outcomes)} trade_outcomes "
          f"(dry_run={DRY})")
    if not outcomes:
        print("  (no outcomes — nothing to aggregate)")
        return 0

    groups = defaultdict(list)
    for o in outcomes:
        base = normalize_setup(o.get("setup_type"))
        if not base:
            continue
        groups[base].append(o)

    now_iso = datetime.now(timezone.utc).isoformat()
    print(f"  → {len(groups)} normalized setups\n")
    print(f"  {'setup':<24} {'n':>4} {'win%':>6} {'EV_R':>7} {'PF':>6}")
    print(f"  {'-'*52}")

    written = 0
    for base in sorted(groups):
        grp = groups[base]
        stats = calc_stats(grp)
        wr = stats["win_rate"] * 100
        print(f"  {base:<24} {stats['total_trades']:>4} {wr:>5.0f}% "
              f"{stats['expected_value_r']:>7.2f} {stats['profit_factor']:>6.2f}")
        if DRY:
            continue
        doc = {
            "context_key": base,
            "setup_type": base,
            "market_regime": None,
            "time_of_day": None,
            "last_updated": now_iso,
            **stats,
        }
        db["learning_stats"].update_one(
            {"context_key": base}, {"$set": doc}, upsert=True
        )
        written += 1

    print()
    if DRY:
        print(f"  DRY RUN — would upsert {len(groups)} learning_stats rows.")
    else:
        print(f"  ✓ upserted {written} learning_stats rows.")
        total = db["learning_stats"].count_documents({})
        print(f"  learning_stats now holds {total} contexts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
