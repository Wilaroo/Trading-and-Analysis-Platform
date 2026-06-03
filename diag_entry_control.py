#!/usr/bin/env python3
"""
diag_entry_control.py — read-only evidence for the two P0 entry-control issues:
  P0-1: bot opened 27 simultaneous positions (cap should be ~5-25).
  P0-2: CEG entered while the scanner was paused.

P0-1 analysis:
  - peak CONCURRENT open positions per day (interval-sweep on executed->closed)
  - entry CLUSTERS: >=3 distinct symbols entered within 60s = one scan cycle
    firing a burst past the cap (the suspected race).
  - distinguishes ONE burst vs accumulation across many cycles.

P0-2 analysis:
  - the CEG trade(s) today: created_at vs executed_at, order type (market/limit),
    entered_by, close_reason. A fresh MARKET entry in an in-flight batch => the
    per-entry-gate fix covers it. A pre-existing LIMIT fill => latent broker order.

READ-ONLY.  .venv/bin/python /tmp/diag_entry_control.py [--symbol CEG] [--days 5]
"""
import argparse
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from pymongo import MongoClient


def _dt(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def _et(dt):
    return (dt - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S") if dt else "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="CEG")
    ap.add_argument("--days", type=int, default=5)
    args = ap.parse_args()
    db = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017")).get_database(
        os.environ.get("DB_NAME", "tradecommand"))
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()

    trades = list(db.bot_trades.find(
        {"$or": [{"executed_at": {"$gte": since}}, {"created_at": {"$gte": since}}]}, {"_id": 0}))
    print(f"\n{'='*76}\nentry-control diag — last {args.days}d  (trades={len(trades)})\n{'='*76}")

    # ---- P0-1a: peak concurrent positions per day ----
    print("\n--- peak CONCURRENT open positions per day (interval sweep) ---")
    by_day = defaultdict(list)
    for t in trades:
        ex = _dt(t.get("executed_at") or t.get("created_at"))
        cl = _dt(t.get("closed_at")) or datetime.now(timezone.utc)
        if ex:
            by_day[(ex - timedelta(hours=4)).date()].append((ex, cl, t.get("symbol", "?")))
    for day in sorted(by_day):
        events = []
        for ex, cl, _ in by_day[day]:
            events.append((ex, 1)); events.append((cl, -1))
        events.sort()
        cur = peak = 0
        peak_t = None
        for ts, delta in events:
            cur += delta
            if cur > peak:
                peak, peak_t = cur, ts
        print(f"  {day}  entries={len(by_day[day]):<3} PEAK CONCURRENT={peak:<3} at {_et(peak_t)} ET")

    # ---- P0-1b: entry bursts (>=3 symbols within 60s) ----
    print("\n--- entry BURSTS (>=3 distinct symbols within 60s = one cycle) ---")
    ents = sorted([( _dt(t.get("executed_at") or t.get("created_at")), t.get("symbol", "?"),
                     t.get("setup_type", "?")) for t in trades if _dt(t.get("executed_at") or t.get("created_at"))],
                  key=lambda x: x[0])
    i = 0
    bursts = 0
    while i < len(ents):
        j = i
        syms = []
        while j < len(ents) and (ents[j][0] - ents[i][0]).total_seconds() <= 60:
            syms.append(ents[j][1]); j += 1
        if len(set(syms)) >= 3:
            bursts += 1
            print(f"  {_et(ents[i][0])} ET  {len(set(syms))} symbols in <=60s: {', '.join(syms[:12])}")
            i = j
        else:
            i += 1
    if not bursts:
        print("  none — 27 likely accumulated across many cycles (drift undercount), not a single burst.")

    # ---- P0-2: the symbol-in-question trades ----
    sym = args.symbol.upper()
    print(f"\n--- {sym} trades (P0-2: entered-while-paused?) ---")
    stq = [t for t in trades if str(t.get("symbol", "")).upper() == sym]
    if not stq:
        print(f"  no {sym} trades in window.")
    for t in sorted(stq, key=lambda x: x.get("executed_at") or x.get("created_at") or ""):
        created = _dt(t.get("created_at"))
        execd = _dt(t.get("executed_at"))
        lag = f"{(execd-created).total_seconds():.0f}s" if (created and execd) else "?"
        print(f"  created={_et(created)}  executed={_et(execd)}  (lag {lag})")
        print(f"    side={t.get('direction') or t.get('side')}  shares={t.get('shares')}  "
              f"entry={t.get('fill_price') or t.get('entry_price')}  order_type={t.get('order_type','?')}  "
              f"limit_price={t.get('limit_price','?')}")
        print(f"    entered_by={t.get('entered_by','?')}  status={t.get('status')}  "
              f"close_reason={t.get('close_reason','-')}  setup={t.get('setup_type')}")

    print()


if __name__ == "__main__":
    main()
