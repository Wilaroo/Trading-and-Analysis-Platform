#!/usr/bin/env python3
"""
EOD SURVIVOR ATTRIBUTION (read-only) — did any position survive the EOD sweep?

For each trading day in the lookback, classifies every CLOSED bot_trade by WHEN it
closed relative to the bot's EOD sweep (which runs ~15:45 ET and finishes by ~15:46):

  • SWEPT     — closed_at <= 15:46 ET  → the EOD sweep (or earlier strategy/stop) got it.
  • SURVIVOR  — closed_at  > 15:46 ET AND it was already open before 15:45
                → the EOD sweep did NOT flatten it; it lived into the 16:00 close and
                  was closed by an OCA leg / strategy / you. THESE are the EOD-trust gaps.
  • LATE_OPEN — opened after 15:40 ET (rare; bot is usually flatten-only by then) — not a miss.

For every SURVIVOR it prints entry time, how long it survived past the sweep, the
close path, and P&L. It also cross-checks the bot_events.eod_auto_close summary so you
can see "sweep said it closed N, but M positions were still alive at 16:00".

Entry time uses `executed_at` (fill time) with `created_at` fallback.
Robust to closed_at/executed_at being ISO string OR BSON datetime.

Usage:
  cd ~/Trading-and-Analysis-Platform
  .venv/bin/python backend/scripts/diag_eod_survivor_attribution.py [DAYS]   # default 7
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
DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 7

# EOD sweep fires ~15:45 ET. Give it a 60s grace to finish all MKT closes.
SWEEP_START = (15, 45)
SWEEP_DONE = (15, 46)   # anything closed strictly after this that was already open = survivor
LATE_OPEN_CUTOFF = (15, 40)  # opened after this is treated as a late/edge open, not an EOD miss


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


def _hm(et_dt):
    return (et_dt.hour, et_dt.minute)


def main():
    db = _load_db()
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS)
    print(f"EOD SURVIVOR ATTRIBUTION — last {DAYS} days (since {cutoff.date()})")
    print("SWEPT = closed by/at the 15:45 sweep · SURVIVOR = lived PAST the sweep into the close\n")

    # day -> list of (entry_et, closed_et, klass, reason, pnl, symbol)
    by_day = defaultdict(list)

    for t in db.bot_trades.find({"status": "closed"}).sort("_id", -1).limit(8000):
        cdt = _parse_dt(t.get("closed_at")) or _parse_dt(t.get("timestamp"))
        if cdt is None or cdt < cutoff:
            continue
        edt = _parse_dt(t.get("executed_at")) or _parse_dt(t.get("created_at"))
        c_et = cdt.astimezone(ET)
        e_et = edt.astimezone(ET) if edt else None
        day = c_et.strftime("%Y-%m-%d")
        reason = t.get("close_reason") or ""
        pnl = float(t.get("realized_pnl") or t.get("net_pnl") or 0)
        sym = t.get("symbol", "?")

        # Only consider the EOD context: closes that happened at/after the sweep window.
        if _hm(c_et) < SWEEP_START:
            klass = "SWEPT"  # closed before EOD (strategy/stop earlier in day) — not an EOD concern
        elif e_et and _hm(e_et) > LATE_OPEN_CUTOFF and e_et.strftime("%Y-%m-%d") == day:
            klass = "LATE_OPEN"
        elif _hm(c_et) > SWEEP_DONE:
            klass = "SURVIVOR"
        else:
            klass = "SWEPT"
        by_day[day].append((e_et, c_et, klass, reason, pnl, sym))

    # Per-day summary + survivor detail
    grand_surv = 0
    for day in sorted(by_day, reverse=True):
        rows = by_day[day]
        swept = [r for r in rows if r[2] == "SWEPT"]
        surv = [r for r in rows if r[2] == "SURVIVOR"]
        late = [r for r in rows if r[2] == "LATE_OPEN"]
        grand_surv += len(surv)

        # authoritative sweep summary for the day
        ev = list(db.bot_events.find(
            {"event_type": "eod_auto_close", "date": day}
        ).sort("timestamp", -1).limit(5))
        ev_closed = sum(int(e.get("positions_closed") or 0) for e in ev)
        ev_ibcnt = max([int(e.get("ib_position_count") or 0) for e in ev], default=0)

        print(f"── {day} "
              f"| sweep_event: closed={ev_closed} ib_count={ev_ibcnt} "
              f"| SWEPT(@/after15:45)={len(swept)} SURVIVORS={len(surv)} late_open={len(late)}")
        if surv:
            print(f"   ⚠ {len(surv)} position(s) survived the EOD sweep and closed into the 16:00 auction:")
            for e_et, c_et, _, reason, pnl, sym in sorted(surv, key=lambda r: r[1]):
                entry_s = e_et.strftime("%H:%M") if e_et else "  ?  "
                surv_min = int((c_et - c_et.replace(hour=SWEEP_DONE[0], minute=SWEEP_DONE[1],
                                                     second=0, microsecond=0)).total_seconds() // 60)
                print(f"      {sym:<6} entry={entry_s} ET  closed={c_et.strftime('%H:%M')} ET "
                      f"(+{surv_min}m past sweep)  via {reason:<32} pnl=${pnl:+.2f}")
        else:
            print("   ✅ no survivors — the sweep owned every open position.")

    print(f"\nTOTAL SURVIVORS across {DAYS} days: {grand_surv}")
    if grand_surv:
        print("→ Each survivor was open before 15:45 but the EOD sweep did not flatten it. "
              "On a tape where its OCA leg doesn't fill at the close, it holds OVERNIGHT NAKED. "
              "This is exactly the gap v19.34.301 (ib_direct naked-flatten guard) closes.")
    else:
        print("→ No EOD survivors in the window. EOD trust is intact for this period.")


if __name__ == "__main__":
    main()
