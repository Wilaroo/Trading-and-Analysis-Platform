#!/usr/bin/env python3
"""
diag_horizon_slot_occupancy.py  (read-only)
===========================================
Answers the slot-allocation question (C): are the scarce 25 position
slots being hogged by longer-horizon (swing/position/investment) trades,
starving fresh scalp/intraday setups — and how often does a full book
actually block a NEW entry?

Prints:
  1. CURRENT open book by horizon vs the live max_open_positions cap,
     with each open trade's age (long-horizon = long occupancy).
  2. HISTORICAL (last --days): trades taken by horizon (count + %),
     and median hold-time per horizon (turnover).
  3. trade_drops (last 7d): how often gate/reason == max_open_positions
     fired (i.e. a candidate was rejected because the book was full),
     and which symbols/setups got blocked = the opportunity cost.

Read-only. Connects using MONGO_URL + DB_NAME from backend/.env.

Usage (from repo root):
    source .venv/bin/activate
    curl -s <paste-url> | python3
  or
    python3 backend/scripts/diag_horizon_slot_occupancy.py --days 30
"""
from __future__ import annotations
import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load_env():
    for cand in (Path.cwd() / "backend" / ".env", Path(__file__).resolve().parents[1] / ".env"):
        if cand.exists():
            for line in cand.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def _db():
    from pymongo import MongoClient
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME", "tradecommand")
    if not url:
        print("ERROR: MONGO_URL not set (and backend/.env not found).")
        sys.exit(1)
    print(f"[db] {name} @ {url.split('@')[-1]}")
    return MongoClient(url)[name]


HORIZONS = ("scalp", "intraday", "swing", "position", "investment")
LONG_HORIZON = ("swing", "position", "investment")


def _enum(v):
    return getattr(v, "value", v)


def horizon(t):
    for f in ("timeframe", "trade_type", "scan_tier"):
        v = str(_enum(t.get(f)) or "").lower().strip()
        if v in HORIZONS:
            return v
    return "unknown"


def _age_min(iso):
    try:
        e = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - e).total_seconds() / 60.0
    except Exception:
        return None


def _cap(db):
    try:
        bs = db["bot_state"].find_one({}, {"_id": 0}) or {}
        for path in (("risk_params", "max_open_positions"), ("max_open_positions",)):
            d = bs
            ok = True
            for k in path:
                if isinstance(d, dict) and k in d:
                    d = d[k]
                else:
                    ok = False
                    break
            if ok and isinstance(d, (int, float)):
                return int(d)
    except Exception:
        pass
    return 25


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()
    _load_env()
    db = _db()
    cap = _cap(db)

    # 1. current open book
    opens = list(db["bot_trades"].find(
        {"status": {"$in": ["open", "OPEN", "Open"]}},
        {"_id": 0, "symbol": 1, "timeframe": 1, "trade_type": 1, "scan_tier": 1,
         "executed_at": 1, "entry_time": 1},
    ))
    print("\n" + "=" * 70)
    print(f"CURRENT OPEN BOOK — {len(opens)}/{cap} slots used")
    print("=" * 70)
    by_h = defaultdict(list)
    for t in opens:
        by_h[horizon(t)].append(t)
    long_used = 0
    for h in list(HORIZONS) + ["unknown"]:
        rows = by_h.get(h)
        if not rows:
            continue
        if h in LONG_HORIZON:
            long_used += len(rows)
        ages = [a for a in (_age_min(r.get("executed_at") or r.get("entry_time")) for r in rows) if a is not None]
        med = sorted(ages)[len(ages) // 2] if ages else 0
        print(f"  {h:<11} {len(rows):>3} slots   median age={med/60:.1f}h")
    if opens:
        print(f"\n  long-horizon (swing/position/investment) occupying: "
              f"{long_used}/{len(opens)} open slots ({long_used/len(opens)*100:.0f}%)")

    # 2. historical mix + turnover
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    hist = list(db["bot_trades"].find(
        {"executed_at": {"$gte": cutoff}},
        {"_id": 0, "timeframe": 1, "trade_type": 1, "scan_tier": 1,
         "executed_at": 1, "closed_at": 1, "status": 1},
    ))
    print("\n" + "-" * 70)
    print(f"TRADES TAKEN — last {args.days}d (n={len(hist)})")
    print("-" * 70)
    hb = defaultdict(list)
    for t in hist:
        hb[horizon(t)].append(t)
    for h in list(HORIZONS) + ["unknown"]:
        rows = hb.get(h)
        if not rows:
            continue
        holds = []
        for r in rows:
            if r.get("closed_at") and r.get("executed_at"):
                try:
                    e = datetime.fromisoformat(str(r["executed_at"]).replace("Z", "+00:00"))
                    c = datetime.fromisoformat(str(r["closed_at"]).replace("Z", "+00:00"))
                    holds.append((c - e).total_seconds() / 3600.0)
                except Exception:
                    pass
        med = sorted(holds)[len(holds) // 2] if holds else 0
        print(f"  {h:<11} {len(rows):>4}  ({len(rows)/len(hist)*100:4.0f}%)   median hold={med:.1f}h")

    # 3. full-book rejections
    print("\n" + "-" * 70)
    print("FULL-BOOK REJECTIONS — trade_drops last 7d (gate/reason ~ max_open_positions)")
    print("-" * 70)
    try:
        drops = list(db["trade_drops"].find({}, {"_id": 0}))
    except Exception:
        drops = []
    full = [d for d in drops
            if "max_open" in (str(d.get("gate", "")) + str(d.get("reason_code", "")) + str(d.get("reason", ""))).lower()]
    print(f"  total trade_drops in collection: {len(drops)}")
    print(f"  blocked by FULL BOOK           : {len(full)}")
    if full:
        bysym = defaultdict(int)
        for d in full:
            bysym[(d.get("symbol") or "?")] += 1
        top = sorted(bysym.items(), key=lambda x: -x[1])[:12]
        print("  most-blocked symbols (sym: times turned away while book was full):")
        for sym, c in top:
            print(f"      {sym:<6} {c}")
        print("\n  -> these are scalp/intraday ideas you COULD have taken if long-")
        print("     horizon trades weren't holding the slots. High count => hard-cap helps.")

    print("\nDone (read-only).")


if __name__ == "__main__":
    main()
