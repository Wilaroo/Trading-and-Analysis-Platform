#!/usr/bin/env python3
"""
diag_live_setup_fires.py  (READ-ONLY live-fire monitor).

Reports, per setup_type, how many alerts fired over the last --days sessions (from
live_alerts), plus the rewritten/suppressed setups called out explicitly so you can
confirm the audit changes are behaving:
  • second_chance / orb_long_confirmed  -> should be FIRING (rewritten doctrines)
  • vwap_bounce                         -> should be ZERO (suppressed v354)
  • approaching_orb                     -> should be ZERO (branch removed in v355)
Also shows auto-executed counts from bot_trades if present. NOTHING IS WRITTEN.

Usage (repo root, DGX):
  .venv/bin/python backend/scripts/diag_live_setup_fires.py --days 5
"""
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone


def _arg(flag, default, cast):
    if flag in sys.argv:
        try:
            return cast(sys.argv[sys.argv.index(flag) + 1])
        except Exception:
            return default
    return default


def _load_db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    from pymongo import MongoClient
    return MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=20000)[env["DB_NAME"]]


def _ts(doc):
    for k in ("created_at", "timestamp", "ts", "alert_time"):
        v = doc.get(k)
        if v:
            return v
    return None


def _to_dt(v):
    try:
        if isinstance(v, datetime):
            return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def main():
    days = _arg("--days", 5, int)
    hours = _arg("--hours", 0, int)   # if >0, scope to last N hours (post-deploy check)
    db = _load_db()
    if hours > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        span = f"last {hours}h"
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        span = f"last {days}d"

    fires = Counter()
    total = 0
    for a in db.live_alerts.find({}, {"_id": 0, "setup_type": 1, "created_at": 1,
                                      "timestamp": 1, "ts": 1, "alert_time": 1}):
        dt = _to_dt(_ts(a))
        if dt and dt >= cutoff and a.get("setup_type"):
            fires[a["setup_type"]] += 1
            total += 1

    print(f"\n=== live_alerts fires — {span} (cutoff {cutoff.isoformat(timespec='minutes')}) — total {total} ===\n")
    for st, n in fires.most_common():
        print(f"  {st:<28} {n}")

    print("\n=== audit-change watchlist ===")
    watch = {
        "second_chance": "FIRING (v353 rewrite)",
        "orb": "ORB base — should FIRE (v355/v355.1)",
        "orb_long_confirmed": "ORB verbatim — should FIRE (v355/v355.1)",
        "approaching_orb": "ZERO after v355 deploy (branch removed)",
        "vwap_bounce": "ZERO after v354 deploy (suppressed)",
        "backside": "FIRING (v352)",
        "off_sides_short": "FIRING (v350 short)",
    }
    for st, note in watch.items():
        n = fires.get(st, 0)
        flag = ""
        if "ZERO after" in note and n > 0:
            flag = "  <-- legacy if window pre-deploy; UNEXPECTED if --hours since deploy"
        if "FIRE" in note and n == 0:
            flag = "  <-- 0 fires (ok if quiet tape / pre-session window)"
        print(f"  {st:<22} {n:>4}   {note}{flag}")

    # auto-executed (bot_trades) by setup if available
    try:
        bt = Counter()
        for t in db.bot_trades.find({}, {"_id": 0, "setup_type": 1, "created_at": 1,
                                         "timestamp": 1, "entry_time": 1}):
            dt = _to_dt(t.get("created_at") or t.get("timestamp") or t.get("entry_time"))
            if dt and dt >= cutoff and t.get("setup_type"):
                bt[t["setup_type"]] += 1
        if bt:
            print(f"\n=== bot_trades (auto-executed) — last {days}d ===\n")
            for st, n in bt.most_common():
                print(f"  {st:<28} {n}")
    except Exception as e:
        print(f"\n(bot_trades read skipped: {e})")
    print()


if __name__ == "__main__":
    main()
