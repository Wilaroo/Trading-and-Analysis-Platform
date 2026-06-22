#!/usr/bin/env python3
"""
diag_outcomes_discover.py — find & qualify realized-outcome data (READ-ONLY)
============================================================================

Answers two things before we build the full A-E outcome harness:
  1. WHERE do realized outcomes live, and how much usable data is there?
  2. Does the CURRENT score (persisted tqs_score = scheme A) already show ANY
     signal — i.e. do higher-scored trades actually win more / earn more R?

Data model (discovered from the codebase):
  • bot_trades  — closed trades carry BOTH the realized result (fill/exit/stop,
                  realized_pnl) AND a tqs_breakdown + tqs_score SNAPSHOT stamped
                  at execution. This is the cleanest validation pool.
  • trade_outcomes  — GENUINE-only closes, hygiene-classified, with actual_r /
                  planned_r / outcome (keyed by bot_trade_id).
  • alert_outcomes  — every close (genuine + artifact), with r_multiple / outcome
                  / genuine flag (keyed by trade_id).
We join bot_trades <-> outcomes by trade id to get a hygiene-correct R and the
`genuine` flag, then bucket by persisted tqs_score to see if there's an edge.

100% READ-ONLY. No writes, no IB.

USAGE (on the DGX, from repo root):
    .venv/bin/python diag_outcomes_discover.py                 # all-time
    .venv/bin/python diag_outcomes_discover.py --days 30
    .venv/bin/python diag_outcomes_discover.py --genuine-only  # drop artifacts
"""

import os
import sys
import math
import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta

CANDIDATES = ["bot_trades", "trade_outcomes", "alert_outcomes", "ev_tracking",
              "strategy_stats", "learning_stats", "regime_trade_log",
              "trade_history", "trades", "playbook_trades"]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def _dir(d):
    return str(getattr(d, "value", d) or "long").lower()

def _parse_dt(v):
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None

def _pct(v, p):
    if not v:
        return None
    s = sorted(v); k = (len(s) - 1) * p / 100.0
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    return s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (k - lo)

def _pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def realized_r_from_trade(bt):
    """Compute R from a bot_trades doc when no hygiene R is joinable."""
    entry = _f(bt.get("fill_price"))
    direction = _dir(bt.get("direction"))
    stop = _f(bt.get("stop_price")) or _f(bt.get("stop_loss"))
    xp = _f(bt.get("exit_price"))
    if not xp:
        realized = _f(bt.get("realized_pnl"))
        shares = _f(bt.get("shares"))
        if entry and realized is not None and shares and shares > 0:
            pps = realized / shares
            xp = entry + pps if direction == "long" else entry - pps
    if not (entry and xp and stop):
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    pps = (xp - entry) if direction == "long" else (entry - xp)
    r = pps / risk
    return max(-20.0, min(20.0, r))


def discover(db):
    print("=" * 92)
    print("  OUTCOME-DATA DISCOVERY")
    print("=" * 92)
    names = set(db.list_collection_names())
    print(f"  {'collection':<22}{'docs':>10}   newest sample of date field")
    for c in CANDIDATES:
        if c not in names:
            print(f"  {c:<22}{'(absent)':>10}")
            continue
        coll = db[c]
        n = coll.count_documents({})
        datef = None
        for cand in ("closed_at", "exit_time", "timestamp", "created_at", "date"):
            d = coll.find_one({cand: {"$exists": True}}, {cand: 1, "_id": 0})
            if d:
                datef = f"{cand}={d.get(cand)!r}"
                break
        print(f"  {c:<22}{n:>10}   {datef or '(no date field found)'}")


def main():
    ap = argparse.ArgumentParser(description="discover & qualify outcome data")
    ap.add_argument("--days", type=int, default=None, help="window (default all-time)")
    ap.add_argument("--genuine-only", action="store_true",
                    help="restrict validation to hygiene-genuine closes")
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL")
    if not mongo_url:
        print("ERROR: MONGO_URL not set."); sys.exit(2)
    from pymongo import MongoClient
    db = MongoClient(mongo_url, serverSelectionTimeoutMS=4000)[
        os.environ.get("DB_NAME", "tradecommand")]

    discover(db)

    # ── load closed bot_trades ───────────────────────────────────────────
    q = {"status": {"$in": ["closed", "CLOSED"]}}
    if args.days:
        q["closed_at"] = {"$gte": (datetime.now(timezone.utc)
                                   - timedelta(days=args.days)).isoformat()}
    proj = {"_id": 0, "id": 1, "trade_id": 1, "alert_id": 1, "symbol": 1,
            "setup_type": 1, "direction": 1, "fill_price": 1, "exit_price": 1,
            "stop_price": 1, "stop_loss": 1, "realized_pnl": 1, "shares": 1,
            "closed_at": 1, "tqs_score": 1, "tqs_breakdown": 1}
    closed = list(db["bot_trades"].find(q, proj))

    # hygiene R + genuine from outcome collections, keyed by trade id
    to_map = {}
    for d in db["trade_outcomes"].find(
            {}, {"_id": 0, "bot_trade_id": 1, "actual_r": 1, "genuine": 1, "outcome": 1}):
        k = d.get("bot_trade_id")
        if k:
            to_map[k] = d
    ao_map = {}
    for d in db["alert_outcomes"].find(
            {}, {"_id": 0, "trade_id": 1, "r_multiple": 1, "genuine": 1, "outcome": 1}):
        k = d.get("trade_id")
        if k:
            ao_map[k] = d

    print("\n" + "=" * 92)
    print(f"  VALIDATION POOL  (closed bot_trades{f', last {args.days}d' if args.days else ', all-time'})")
    print("=" * 92)
    n_closed = len(closed)
    n_bd = n_r = n_score = 0
    n_in_to = n_in_ao = 0
    rows = []  # (tqs_score, r, win, genuine, has_breakdown)
    for bt in closed:
        tid = bt.get("id") or bt.get("trade_id")
        has_bd = bool(bt.get("tqs_breakdown"))
        score = _f(bt.get("tqs_score"))
        to = to_map.get(tid)
        ao = ao_map.get(tid)
        if to:
            n_in_to += 1
        if ao:
            n_in_ao += 1
        # prefer hygiene R, fall back to recompute
        r = None; genuine = True; outcome = None
        if to and to.get("actual_r") is not None:
            r = _f(to.get("actual_r")); genuine = bool(to.get("genuine", True))
            outcome = to.get("outcome")
        elif ao and ao.get("r_multiple") is not None:
            r = _f(ao.get("r_multiple")); genuine = bool(ao.get("genuine", True))
            outcome = ao.get("outcome")
        else:
            r = realized_r_from_trade(bt)
            if ao is not None:
                genuine = bool(ao.get("genuine", True))
        if has_bd:
            n_bd += 1
        if score is not None and score > 0:
            n_score += 1
        if r is not None:
            n_r += 1
            win = (outcome == "won") if outcome in ("won", "lost", "scratch") else (r > 0)
            rows.append((score, r, win, genuine, has_bd))

    print(f"  closed trades:            {n_closed}")
    print(f"  carry tqs_breakdown:      {n_bd}  ({(n_bd/n_closed*100) if n_closed else 0:.1f}%)")
    print(f"  carry tqs_score>0:        {n_score}  ({(n_score/n_closed*100) if n_closed else 0:.1f}%)")
    print(f"  have a realized R:        {n_r}  ({(n_r/n_closed*100) if n_closed else 0:.1f}%)")
    print(f"  matched in trade_outcomes:{n_in_to}   matched in alert_outcomes: {n_in_ao}")

    # ── realized-R distribution (is there signal to find?) ───────────────
    pool = [x for x in rows if (x[3] or not args.genuine_only)]
    rs = [x[1] for x in pool]
    if rs:
        wins = sum(1 for x in pool if x[2])
        print(f"\n  REALIZED R{' (genuine only)' if args.genuine_only else ''}: "
              f"n={len(rs)}  win%={wins/len(rs)*100:.1f}  "
              f"min={min(rs):.2f}  p25={_pct(rs,25):.2f}  p50={_pct(rs,50):.2f}  "
              f"p75={_pct(rs,75):.2f}  max={max(rs):.2f}  mean={sum(rs)/len(rs):+.3f}R")

    # ── prelim signal check: does the CURRENT score separate winners? ────
    usable = [x for x in pool if x[0] is not None and x[0] > 0]
    print("\n" + "-" * 92)
    print(f"  PRELIM SIGNAL CHECK — usable (score>0 + R{' + genuine' if args.genuine_only else ''}): "
          f"{len(usable)}")
    if len(usable) >= 15:
        usable.sort(key=lambda x: x[0])
        n = len(usable)
        thirds = [usable[:n // 3], usable[n // 3:2 * n // 3], usable[2 * n // 3:]]
        print(f"  {'tercile (by tqs_score=A)':<26}{'n':>5}{'score rng':>14}"
              f"{'win%':>8}{'avg R':>9}")
        for name, grp in zip(("low", "mid", "high"), thirds):
            if not grp:
                continue
            sc = [g[0] for g in grp]; gr = [g[1] for g in grp]
            wr = sum(1 for g in grp if g[2]) / len(grp) * 100
            print(f"  {name:<26}{len(grp):>5}{f'{min(sc):.1f}-{max(sc):.1f}':>14}"
                  f"{wr:>8.1f}{sum(gr)/len(gr):>+9.3f}")
        cor = _pearson([g[0] for g in usable], [g[1] for g in usable])
        print(f"\n  Pearson corr(tqs_score, realized R) = "
              f"{cor:+.3f}" if cor is not None else "  corr: n/a")
        print("  READ: if high tercile win% / avg R clearly > low tercile (and corr > ~0.1),")
        print("  the CURRENT score already carries signal -> worth building the full A-E")
        print("  discrimination harness. If flat/negative -> the inputs, not the aggregation,")
        print("  are the problem (light the dark feeds first).")
    else:
        print("  Not enough graded+scored closes to judge yet. This is itself a finding:")
        print("  the alert->outcome conversion is too sparse. Options: widen --days, run the")
        print("  learning reconciler to backfill alert_outcomes, or trade more before deciding.")
    print("\n" + "=" * 92)


if __name__ == "__main__":
    main()
