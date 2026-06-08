#!/usr/bin/env python3
"""
Audit Phase 4 — REALIZED-EDGE + PHANTOM-COST diagnostic  (READ-ONLY).

MFE is unreliable here (52% of trades close via `oca_closed_externally`, so the local
MFE loop barely ticks before the OCA fills at IB). This script measures the TRUE
outcome from realized prices instead:

  A. Realized R-multiple distribution  -> is there actual edge? (expectancy in R)
  B. Win rate / avg win R / avg loss R / expectancy, overall + per close-reason group
  C. wrong_direction_phantom_swept cost -> what do the phantom sweeps actually cost ($/R)?

R is computed from prices:  long  R = (exit-fill)/(fill-stop)
                            short R = (fill-exit)/(stop-fill)
Trades with no usable exit/stop are skipped from the R stats (counted separately).

READ-ONLY: .find with {"_id":0} only. No writes. Safe on the live DGX.

Run:
    cd ~/Trading-and-Analysis-Platform/backend
    ../.venv/bin/python scripts/audit_phase4_edge_diagnostic.py --days 21
    # --days 0 for all-time
"""
import argparse
import os
import sys
from collections import Counter, defaultdict
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
    mongo = os.environ.get("MONGO_URL")
    db = os.environ.get("DB_NAME")
    if not mongo or not db:
        print("ERROR: MONGO_URL / DB_NAME not found in env or backend/.env")
        sys.exit(2)
    return mongo, db


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _r_multiple(t):
    """Realized R from fill/exit/stop prices, or None if not computable."""
    fill = _f(t.get("fill_price"))
    exit_p = _f(t.get("exit_price")) or _f(t.get("avg_exit_price"))
    stop = _f(t.get("stop_price"))
    if fill is None or exit_p is None or stop is None:
        return None
    direction = str((t.get("direction") or "")).lower().replace("tradedirection.", "")
    risk = abs(fill - stop)
    if risk <= 0:
        return None
    if "long" in direction:
        return (exit_p - fill) / risk
    if "short" in direction:
        return (fill - exit_p) / risk
    return None


def _group(reason):
    r = (reason or "").lower()
    if "phantom" in r or "zombie" in r or "orphan" in r or "wrong_direction" in r:
        return "phantom/zombie/orphan"
    if "oca_closed_externally" in r or r in ("stop_loss", "target_hit"):
        return "clean bracket/stop/target"
    if "eod" in r:
        return "EOD flatten"
    if "operator" in r or "manual" in r or "v5_operator" in r:
        return "operator/manual"
    if "consolidat" in r or "external_close" in r or "shrunk_to_zero" in r:
        return "reconciliation/consolidation"
    if "scalp_time_decay" in r:
        return "scalp time-decay"
    return "other"


def _stats(rs):
    if not rs:
        return None
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    n = len(rs)
    return {
        "n": n,
        "win_rate": len(wins) / n * 100,
        "avg_win_r": (sum(wins) / len(wins)) if wins else 0.0,
        "avg_loss_r": (sum(losses) / len(losses)) if losses else 0.0,
        "expectancy_r": sum(rs) / n,
        "total_r": sum(rs),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=21)
    args = ap.parse_args()

    mongo_url, db_name = _load_env()
    from pymongo import MongoClient
    db = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)[db_name]

    q = {"fill_price": {"$ne": None}, "status": "closed"}
    if args.days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
        q["$or"] = [{"executed_at": {"$gte": cutoff}}, {"created_at": {"$gte": cutoff}}]

    proj = {"_id": 0, "symbol": 1, "direction": 1, "close_reason": 1,
            "fill_price": 1, "exit_price": 1, "avg_exit_price": 1, "stop_price": 1,
            "realized_pnl": 1}
    trades = list(db["bot_trades"].find(q, proj))
    total = len(trades)

    print("=" * 72)
    print(f"AUDIT PHASE 4 — REALIZED-EDGE + PHANTOM-COST   ({db_name})")
    print(f"closed filled trades: {total}"
          + (f"  (last {args.days}d)" if args.days else "  (all time)"))
    print("=" * 72)
    if total == 0:
        print("No closed trades found.")
        return

    # ── A/B: realized R overall + per group ──
    all_r, no_r = [], 0
    by_group_r = defaultdict(list)
    by_group_pnl = defaultdict(float)
    by_group_n = Counter()
    pnl_total = 0.0
    for t in trades:
        g = _group(t.get("close_reason"))
        by_group_n[g] += 1
        pnl = _f(t.get("realized_pnl")) or 0.0
        pnl_total += pnl
        by_group_pnl[g] += pnl
        r = _r_multiple(t)
        if r is None:
            no_r += 1
            continue
        all_r.append(r)
        by_group_r[g].append(r)

    print(f"\n── A. Realized R distribution (computable: {len(all_r)}, "
          f"skipped no-price: {no_r}) ──")
    if all_r:
        buckets = Counter()
        for r in all_r:
            if r <= -1.5:
                buckets["<= -1.5R (overshot stop)"] += 1
            elif r <= -0.5:
                buckets["-1.5R..-0.5R (loss)"] += 1
            elif r < 0.5:
                buckets["-0.5R..+0.5R (scratch)"] += 1
            elif r < 1.5:
                buckets["+0.5R..+1.5R (small win)"] += 1
            elif r < 3.0:
                buckets["+1.5R..+3R (good)"] += 1
            else:
                buckets[">= +3R (runner)"] += 1
        order = ["<= -1.5R (overshot stop)", "-1.5R..-0.5R (loss)",
                 "-0.5R..+0.5R (scratch)", "+0.5R..+1.5R (small win)",
                 "+1.5R..+3R (good)", ">= +3R (runner)"]
        for k in order:
            n = buckets.get(k, 0)
            print(f"  {n:5d}  {k}   ({n/len(all_r)*100:.0f}%)")

    s = _stats(all_r)
    if s:
        print(f"\n── B. Edge (overall, n={s['n']}) ──")
        print(f"  win rate:      {s['win_rate']:.1f}%")
        print(f"  avg win:       +{s['avg_win_r']:.2f}R")
        print(f"  avg loss:      {s['avg_loss_r']:.2f}R")
        print(f"  EXPECTANCY:    {s['expectancy_r']:+.3f}R per trade")
        print(f"  total realized_pnl (all closes): ${pnl_total:,.0f}")

    print("\n── B2. By close-reason group (n | win% | expR | total $) ──")
    for g in sorted(by_group_n, key=lambda x: -by_group_n[x]):
        gs = _stats(by_group_r.get(g))
        win = f"{gs['win_rate']:.0f}%" if gs else "n/a"
        exp = f"{gs['expectancy_r']:+.2f}R" if gs else "n/a"
        print(f"  {by_group_n[g]:5d} {g:28s} win={win:>5s} "
              f"exp={exp:>7s}  pnl=${by_group_pnl[g]:>10,.0f}")

    # ── C: phantom-sweep cost ──
    ph = [t for t in trades if "phantom" in (t.get("close_reason") or "").lower()
          or "wrong_direction" in (t.get("close_reason") or "").lower()
          or "zombie" in (t.get("close_reason") or "").lower()
          or "orphan" in (t.get("close_reason") or "").lower()]
    ph_pnl = sum(_f(t.get("realized_pnl")) or 0.0 for t in ph)
    ph_r = [_r_multiple(t) for t in ph]
    ph_r = [r for r in ph_r if r is not None]
    print("\n── C. wrong-direction / phantom / zombie / orphan sweep COST ──")
    print(f"  count:              {len(ph)} / {total} ({len(ph)/total*100:.1f}%)")
    print(f"  total realized_pnl: ${ph_pnl:,.0f}")
    if ph_r:
        print(f"  avg realized R:     {sum(ph_r)/len(ph_r):+.2f}R  (n={len(ph_r)} w/ prices)")
    print("  (if pnl is strongly negative, phantom sweeps are an active capital leak —")
    print("   P0 root-cause before unmanaged trading. If ~0, they're net scratches.)")

    print("\n" + "=" * 72)
    print("DONE — read-only. No documents were modified.")
    print("=" * 72)


if __name__ == "__main__":
    main()
