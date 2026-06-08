#!/usr/bin/env python3
"""
EOD LATE-OPEN DISAMBIGUATION (read-only) — are "late opens" real entries or reconciled orphans?

The survivor-attribution script labels a close as LATE_OPEN when `executed_at` (entry/fill
time) lands after 15:40 ET. But `executed_at` is ALSO stamped at *adoption time* for
positions the reconciler adopts (`entered_by == "reconciled_external"`), so a late
`executed_at` can be a harmless artifact rather than the bot genuinely opening into the close.

This script, for a given DATE (ET), dumps every bot_trade that CLOSED at/after 15:45 ET and
breaks them down by `entered_by`:
   • bot_fired           — bot's own evaluation opened it. A late executed_at HERE is a real
                           "opened into the close" event → worth investigating.
   • reconciled_external — reconciler adopted an IB orphan; executed_at = adoption time, NOT a
                           real late entry → harmless artifact.
   • manual              — operator-created.

For each row it prints created_at, executed_at, closed_at (all ET), close_reason and pnl so
you can see the true lifecycle.

Usage:
  cd ~/Trading-and-Analysis-Platform
  .venv/bin/python backend/scripts/diag_eod_lateopen_disambig.py [DATE]   # default = most recent day with closes
"""
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from pymongo import MongoClient

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TARGET = sys.argv[1] if len(sys.argv) > 1 else None
SWEEP_START = (15, 45)


def _load_db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return MongoClient(env["MONGO_URL"])[env["DB_NAME"]]


def _parse_dt(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _et(v):
    d = _parse_dt(v)
    return d.astimezone(ET) if d else None


def main():
    db = _load_db()
    cutoff = datetime.now(timezone.utc) - timedelta(days=10)

    # Collect closed trades (last 10d) keyed by ET close-day.
    rows_by_day = defaultdict(list)
    for t in db.bot_trades.find({"status": "closed"}).sort("_id", -1).limit(8000):
        c = _et(t.get("closed_at")) or _et(t.get("timestamp"))
        if not c or _parse_dt(t.get("closed_at")) < cutoff:
            continue
        rows_by_day[c.strftime("%Y-%m-%d")].append(t)

    target = TARGET or (sorted(rows_by_day, reverse=True)[0] if rows_by_day else None)
    if not target:
        print("No closed trades found.")
        return

    print(f"EOD LATE-OPEN DISAMBIGUATION — {target} (closes at/after 15:45 ET)\n")
    grp = defaultdict(list)
    for t in rows_by_day.get(target, []):
        c = _et(t.get("closed_at")) or _et(t.get("timestamp"))
        if (c.hour, c.minute) < SWEEP_START:
            continue
        grp[t.get("entered_by", "unknown")].append(t)

    if not grp:
        print("  No positions closed at/after 15:45 ET on this date.")
        return

    real_late = 0
    for entered_by in sorted(grp):
        trades = grp[entered_by]
        print(f"=== entered_by = {entered_by}  ({len(trades)} closed @/after 15:45) ===")
        for t in sorted(trades, key=lambda x: _et(x.get("executed_at") or x.get("created_at")) or _et(x.get("closed_at"))):
            cr = _et(t.get("created_at"))
            ex = _et(t.get("executed_at"))
            cl = _et(t.get("closed_at"))
            pnl = float(t.get("realized_pnl") or t.get("net_pnl") or 0)
            ex_s = ex.strftime("%H:%M") if ex else "  ?  "
            flag = ""
            if entered_by == "bot_fired" and ex and (ex.hour, ex.minute) > (15, 40):
                flag = "  <<< REAL late entry (bot opened into the close)"
                real_late += 1
            print(f"   {t.get('symbol','?'):<6} setup={str(t.get('setup_type','?'))[:14]:<14} "
                  f"created={cr.strftime('%H:%M') if cr else '  ?  '} "
                  f"exec={ex_s} closed={cl.strftime('%H:%M') if cl else '  ?  '} "
                  f"| {str(t.get('close_reason','')):<34} pnl=${pnl:+.2f}{flag}")
        print()

    print(f"VERDICT: {real_late} genuine bot-fired entries opened AFTER 15:40 ET.")
    if real_late:
        print("→ The bot is opening positions into the close after/around the EOD sweep window. "
              "Investigate the entry gate's RegT/flatten-only cutoff — late opens add churn and "
              "can slip past the 15:45 sweep.")
    else:
        print("→ No genuine late opens. The late `executed_at` values are reconciled-orphan "
              "adoption timestamps (harmless artifact), not real entries into the close.")


if __name__ == "__main__":
    main()
