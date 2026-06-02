#!/usr/bin/env python3
"""
diag_execution_pillar.py  (READ-ONLY)

Confirms WHY the TQS Execution pillar is pinned at a constant (48.80) for every
alert. The pillar reads `get_trader_profile()` which is fed by:
  - the `trader_profiles` default doc (overall_win_rate, consecutive_losses)
  - the `trade_outcomes` collection (recent execution history)
Both are written ONLY by learning_loop.record_trade_outcome. If that path is
stale/orphaned (like strategy_stats was pre-v216), the pillar can't discriminate.

Prints, for the last N days, the freshness of trade_outcomes vs the live
alert_outcomes collection, and the actual trader-profile fields the pillar reads.
Writes nothing.
"""
import os
from datetime import datetime, timezone, timedelta


def _load_env():
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME")
    for c in ("/app/backend/.env", "./backend/.env", "backend/.env", ".env"):
        if (url and name) or not os.path.exists(c):
            continue
        for line in open(c):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k == "MONGO_URL" and not url:
                url = v
            elif k == "DB_NAME" and not name:
                name = v
    return url or "mongodb://localhost:27017", name or "tradecommand"


def _recent(coll, field, days=7):
    """Count docs whose `field` (ISO or datetime) is within `days`."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    n = 0
    latest = None
    for d in coll.find({}, {field: 1}).sort([("_id", -1)]).limit(2000):
        v = d.get(field)
        dt = None
        if isinstance(v, datetime):
            dt = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        elif isinstance(v, str) and v:
            try:
                dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            except Exception:
                dt = None
        if dt:
            if latest is None or dt > latest:
                latest = dt
            if dt >= cutoff:
                n += 1
    return n, latest


def main():
    from pymongo import MongoClient
    url, name = _load_env()
    db = MongoClient(url, serverSelectionTimeoutMS=5000)[name]
    print(f"DB: {name}\n" + "=" * 70)

    to_total = db["trade_outcomes"].count_documents({})
    ao_total = db["alert_outcomes"].count_documents({})
    print(f"trade_outcomes total : {to_total}")
    print(f"alert_outcomes total : {ao_total}")

    # freshness — trade_outcomes uses created_at; alert_outcomes uses closed_at
    to_recent, to_latest = _recent(db["trade_outcomes"], "created_at", 7)
    ao_recent, ao_latest = _recent(db["alert_outcomes"], "closed_at", 7)
    print(f"\ntrade_outcomes  last-7d: {to_recent:5d}   newest: {to_latest}")
    print(f"alert_outcomes  last-7d: {ao_recent:5d}   newest: {ao_latest}")
    if ao_recent and not to_recent:
        print("  ⬅ ORPHAN SIGNATURE: closes are landing in alert_outcomes but NOT "
              "trade_outcomes → trader profile starves → execution pillar pins.")

    print("\n" + "=" * 70)
    prof = db["trader_profiles"].find_one({"profile_id": "default"}) or {}
    if not prof:
        print("trader_profiles 'default' doc: MISSING ⬅ pillar uses fresh defaults "
              "(win_rate=0.5, consecutive_losses=0) → constant 48.80")
    else:
        tilt = prof.get("current_tilt_state", {}) or {}
        print("trader_profiles 'default':")
        print(f"  total_trades        : {prof.get('total_trades')}")
        print(f"  overall_win_rate    : {prof.get('overall_win_rate')}   (pillar streak/history input)")
        print(f"  overall_ev_r        : {prof.get('overall_ev_r')}")
        print(f"  consecutive_losses  : {tilt.get('consecutive_losses')}   (pillar tilt input)")
        print(f"  is_tilted           : {tilt.get('is_tilted')}")
        print(f"  trades_today        : {prof.get('trades_today')}")
        print(f"  avg_r_capture_pct   : {prof.get('avg_r_capture_percent')}")
        print(f"  updated_at/last     : {prof.get('updated_at') or prof.get('last_updated')}")

    print("\n" + "=" * 70)
    print("Recent trade_outcomes sample (newest 5):")
    for d in db["trade_outcomes"].find({}).sort([("_id", -1)]).limit(5):
        print(f"  {str(d.get('created_at'))[:19]}  {d.get('symbol'):8s} "
              f"{str(d.get('setup_type'))[:18]:18s} {d.get('outcome'):6s} "
              f"R={d.get('actual_r')}  pnl={d.get('pnl')}")
    print("\nDone. Read-only.")


if __name__ == "__main__":
    main()
