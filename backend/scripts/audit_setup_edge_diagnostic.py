#!/usr/bin/env python3
"""
Audit Phase 4/5 — SETUP-LEVEL EDGE + RECENCY-TREND diagnostic  (READ-ONLY).

CONTEXT: the 21-day edge numbers are a CONTAMINATED BASELINE — they predate the
F1-F5 data-trust fixes, the scanner-quality improvements, and the EOD-close work.
So this script is NOT a strategy verdict. It (1) breaks edge down by setup_type to
show WHICH setups bleed, and (2) shows a week-over-week recency trend so we can see
if the recent data-pipeline fixes are already moving the needle.

Win/loss is taken from realized_pnl SIGN (covers ALL closed trades, unlike R which
needs exit/stop prices). R-multiple shown where computable.

READ-ONLY: .find with {"_id":0} only. No writes.

Run:
    cd ~/Trading-and-Analysis-Platform/backend
    ../.venv/bin/python scripts/audit_setup_edge_diagnostic.py --days 45
"""
import argparse
import os
import sys
from collections import defaultdict
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
    fill = _f(t.get("fill_price"))
    exit_p = _f(t.get("exit_price")) or _f(t.get("avg_exit_price"))
    stop = _f(t.get("stop_price"))
    if fill is None or exit_p is None or stop is None:
        return None
    d = str(t.get("direction") or "").lower()
    risk = abs(fill - stop)
    if risk <= 0:
        return None
    if "long" in d:
        return (exit_p - fill) / risk
    if "short" in d:
        return (fill - exit_p) / risk
    return None


def _trade_dt(t):
    for k in ("executed_at", "created_at", "closed_at"):
        v = t.get(k)
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                continue
        if isinstance(v, datetime):
            return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return None


def _summarize(rows, label):
    n = len(rows)
    if n == 0:
        return
    pnl = sum(_f(t.get("realized_pnl")) or 0.0 for t in rows)
    wins = sum(1 for t in rows if (_f(t.get("realized_pnl")) or 0.0) > 0)
    rs = [r for r in (_r_multiple(t) for t in rows) if r is not None]
    exp = (sum(rs) / len(rs)) if rs else None
    exp_s = f"{exp:+.2f}R" if exp is not None else "  n/a"
    print(f"  {n:5d} {label:30s} win={wins/n*100:4.0f}%  exp={exp_s:>7s}  "
          f"pnl=${pnl:>10,.0f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=45)
    args = ap.parse_args()

    mongo_url, db_name = _load_env()
    from pymongo import MongoClient
    db = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)[db_name]

    q = {"fill_price": {"$ne": None}, "status": "closed"}
    if args.days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
        q["$or"] = [{"executed_at": {"$gte": cutoff}}, {"created_at": {"$gte": cutoff}}]

    proj = {"_id": 0, "symbol": 1, "direction": 1, "setup_type": 1, "close_reason": 1,
            "fill_price": 1, "exit_price": 1, "avg_exit_price": 1, "stop_price": 1,
            "realized_pnl": 1, "executed_at": 1, "created_at": 1, "closed_at": 1}
    trades = list(db["bot_trades"].find(q, proj))
    total = len(trades)

    print("=" * 78)
    print(f"AUDIT — SETUP-LEVEL EDGE + RECENCY TREND   ({db_name})")
    print(f"closed filled trades: {total}"
          + (f"  (last {args.days}d)" if args.days else "  (all time)"))
    print("CONTAMINATED BASELINE — predates F1-F5 data fixes; read the TREND, not the level.")
    print("=" * 78)
    if total == 0:
        print("No closed trades found.")
        return

    # 1) by setup_type
    by_setup = defaultdict(list)
    for t in trades:
        by_setup[str(t.get("setup_type") or "(none)")].append(t)
    print("\n── 1. Edge by setup_type (sorted by total pnl) ──")
    for st in sorted(by_setup, key=lambda s: sum(_f(t.get("realized_pnl")) or 0.0
                                                 for t in by_setup[s])):
        _summarize(by_setup[st], st[:30])

    # 2) recency trend — 7-day buckets
    print("\n── 2. Recency trend (7-day buckets, newest first) ──")
    now = datetime.now(timezone.utc)
    buckets = defaultdict(list)
    undated = 0
    for t in trades:
        dt = _trade_dt(t)
        if dt is None:
            undated += 1
            continue
        wk = int((now - dt).days // 7)
        buckets[wk].append(t)
    for wk in sorted(buckets):
        lo, hi = wk * 7, wk * 7 + 7
        _summarize(buckets[wk], f"days {lo:2d}-{hi:2d} ago")
    if undated:
        print(f"  ({undated} trades had no parseable date)")

    # 3) target-hit vs stop-hit within clean bracket exits
    print("\n── 3. Clean bracket/stop exits — winners vs losers ──")
    clean = [t for t in trades if (t.get("close_reason") or "").lower()
             in ("oca_closed_externally_v19_31", "stop_loss", "target_hit")
             or "oca_closed_externally" in (t.get("close_reason") or "").lower()]
    cw = [t for t in clean if (_f(t.get("realized_pnl")) or 0.0) > 0]
    cl = [t for t in clean if (_f(t.get("realized_pnl")) or 0.0) < 0]
    cs = [t for t in clean if (_f(t.get("realized_pnl")) or 0.0) == 0]
    print(f"  clean exits: {len(clean)}  |  winners: {len(cw)}  losers: {len(cl)}  "
          f"flat: {len(cs)}")
    if clean:
        win_pnl = sum(_f(t.get("realized_pnl")) or 0.0 for t in cw)
        loss_pnl = sum(_f(t.get("realized_pnl")) or 0.0 for t in cl)
        print(f"  winners total: ${win_pnl:,.0f}   losers total: ${loss_pnl:,.0f}")
        print("  => if losers count >> winners count, stops are hitting far more than")
        print("     targets — an R:R / target-placement problem, not a managed-exit one.")

    print("\n" + "=" * 78)
    print("DONE — read-only. No documents were modified.")
    print("=" * 78)


if __name__ == "__main__":
    main()
