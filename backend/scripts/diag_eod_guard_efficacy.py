#!/usr/bin/env python3
"""
EOD-GUARD EFFICACY (read-only) — is v19.34.260 (EOD-window flatten-instead-of-adopt)
actually firing, and did orphan-survivors stop after it went live?

For the last N days it shows, per ET day:
  • ADOPTED_IN_EOD_WINDOW — bot_trades with entered_by="reconciled_external" whose
      executed_at (adoption time) landed at/after 15:40 ET. These are the dangerous
      "adopted an orphan right at/after the Reg-T cutoff" rows that v260 is meant to
      PREVENT. Should trend to ZERO once v260 is live.
  • V260_FLATTENS — bot_events.eod_window_orphan_flatten rows (the guard FIRING:
      flattening an orphan instead of adopting it). Presence proves the guard is wired
      and active.
  • EOD_ORPHAN_SWEEP — bot_events.eod_orphan_sweep summary (the v162 working-order sweep).

Use it to confirm the cutover: ADOPTED_IN_EOD_WINDOW should drop to 0 on/after the day
V260_FLATTENS starts appearing.

Usage:
  cd ~/Trading-and-Analysis-Platform
  .venv/bin/python backend/scripts/diag_eod_guard_efficacy.py [DAYS]   # default 12
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
DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 12
EOD_WINDOW = (15, 40)


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
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS)
    print(f"EOD-GUARD EFFICACY — last {DAYS} days. "
          f"ADOPTED_IN_EOD_WINDOW should drop to 0 once V260_FLATTENS appears.\n")

    adopted = defaultdict(list)   # day -> [(adopt_time_et, symbol)]
    for t in db.bot_trades.find(
        {"entered_by": "reconciled_external"}
    ).sort("_id", -1).limit(4000):
        ex = _et(t.get("executed_at") or t.get("created_at"))
        if not ex or _parse_dt(t.get("executed_at") or t.get("created_at")) < cutoff:
            continue
        if (ex.hour, ex.minute) >= EOD_WINDOW:
            adopted[ex.strftime("%Y-%m-%d")].append((ex.strftime("%H:%M:%S"), t.get("symbol", "?")))

    v260 = defaultdict(int)       # day -> count of guard firings
    v260_detail = defaultdict(list)
    for e in db.bot_events.find(
        {"event_type": "eod_window_orphan_flatten"}
    ).sort("timestamp", -1).limit(2000):
        d = _et(e.get("timestamp"))
        if not d or _parse_dt(e.get("timestamp")) < cutoff:
            continue
        day = d.strftime("%Y-%m-%d")
        v260[day] += 1
        v260_detail[day].append((d.strftime("%H:%M:%S"), e.get("symbol", e.get("symbols", "?"))))

    sweep = defaultdict(lambda: [0, 0])  # day -> [queued, errors]
    for e in db.bot_events.find(
        {"event_type": "eod_orphan_sweep"}
    ).sort("timestamp", -1).limit(2000):
        d = _et(e.get("timestamp"))
        if not d or _parse_dt(e.get("timestamp")) < cutoff:
            continue
        day = d.strftime("%Y-%m-%d")
        sweep[day][0] += int(e.get("queued") or 0)
        sweep[day][1] += int(e.get("errors") or 0)

    all_days = sorted(set(list(adopted) + list(v260) + list(sweep)), reverse=True)
    print(f"{'date':<12} {'ADOPTED_IN_EOD_WIN':>20} {'V260_FLATTENS':>14} {'ORPHAN_SWEEP(q/err)':>20}")
    for day in all_days:
        a = len(adopted.get(day, []))
        f = v260.get(day, 0)
        q, err = sweep.get(day, [0, 0])
        flag = "  <<< DANGER (adopted past cutoff, v260 did NOT catch)" if a and not f else ""
        print(f"{day:<12} {a:>20} {f:>14} {f'{q}/{err}':>20}{flag}")

    # Detail the dangerous adoptions and the guard firings.
    if any(adopted.values()):
        print("\n=== Orphans adopted in the EOD window (the survivors v260 must prevent) ===")
        for day in sorted(adopted, reverse=True):
            for ts, sym in sorted(adopted[day]):
                print(f"   {day} {ts}  {sym}")
    if any(v260.values()):
        print("\n=== v260 guard FIRINGS (flattened instead of adopted — guard is live) ===")
        for day in sorted(v260_detail, reverse=True):
            for ts, sym in sorted(v260_detail[day]):
                print(f"   {day} {ts}  {sym}")
    else:
        print("\n⚠ NO v260 eod_window_orphan_flatten events recorded in this window — "
              "either no orphan appeared past the cutoff since v260 went live, OR the "
              "guard is not actually firing. If ADOPTED_IN_EOD_WINDOW is also 0 on recent "
              "days, the guard simply had nothing to catch (good). If it's >0 on recent "
              "days, the guard has a gap.")


if __name__ == "__main__":
    main()
