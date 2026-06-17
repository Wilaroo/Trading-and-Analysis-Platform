#!/usr/bin/env python3
"""
v339 — EOD-LEAK TIMELINE (READ-ONLY) — live gap vs historical residue?

v338 found 32 genuine intraday/scalp trades (policy should_close_at_eod=True) that
RODE OVERNIGHT. Before touching the safety-critical Journey-3 EOD path we must know
whether those leaks are RECENT (a live enforcement gap that survives v245/v261/v301/
v322s) or HISTORICAL (pre-fix residue inside the 120d window, already sealed).

For every genuine bot-own closed trade whose policy=should_close_at_eod(True) AND
entry ET-date != exit ET-date, this prints:
  • entry ET datetime + time-of-day bucket (PRE 04:00-09:30 / RTH 09:30-15:45 /
    LATE 15:45-16:00 / AH 16:00-20:00 / ON 20:00-04:00)  ← LATE/AH/ON entries can
    legitimately miss the SAME-DAY 15:55 pass (the v261 re-sweep / next-boot sweep owns them)
  • days held, close_reason, symbol/side/setup
  • a per-MONTH histogram of leak entries (recency = is the gap still live?)
  • a tally of leaks whose entry was BEFORE the 15:45 EOD window on a weekday
    (these SHOULD have been caught by the same-day pass → the real live-gap suspects)

Fix-ship reference dates to compare against (entry date >= these = fix was already live):
  v19.34.245 (policy-authoritative EOD)     ~2026-06-02
  v19.34.261 (EOD re-sweep late arrivals)   ~2026-06-03
  v19.34.301 (pusher-independent naked guard)~2026-06-08
  v322s      (missed-EOD boot sweep)        ~2026-06-12

NOTHING IS WRITTEN.
Usage (repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v339_eod_leak_timeline.py --days 120
"""
import sys
from collections import Counter
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:
    _ET = None


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


def _g(d, *keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _dt(v):
    if v is None or v == "":
        return None
    try:
        f = float(v)
        if f > 1e12:
            f /= 1000.0
        if f > 1e8:
            return datetime.fromtimestamp(f, tz=timezone.utc)
    except (TypeError, ValueError):
        pass
    try:
        s = str(v).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _et(dt):
    return dt.astimezone(_ET) if (dt and _ET) else dt


def _tod_bucket(et_dt):
    hm = et_dt.hour * 60 + et_dt.minute
    if 240 <= hm < 570:
        return "PRE"
    if 570 <= hm < 945:
        return "RTH"
    if 945 <= hm < 960:
        return "LATE"
    if 960 <= hm < 1200:
        return "AH"
    return "ON"


def main():
    days = _arg("--days", 120, int)
    sys.path.insert(0, "backend")
    since = datetime.now(timezone.utc).timestamp() - days * 86400
    db = _load_db()

    from services.trade_outcome_hygiene import classify_close, is_adopted_entry
    from services.order_policy_registry import should_close_at_eod

    rows = []
    month_hist = Counter()
    tod_hist = Counter()
    same_day_pass_suspects = 0   # entered weekday BEFORE 15:45 → same-day pass should have caught it

    for t in db.bot_trades.find({"status": "closed"}, {"_id": 0}):
        entry_dt = _dt(_g(t, "executed_at", "created_at", "entry_time", "entry_time_ms", "opened_at"))
        exit_dt = _dt(_g(t, "closed_at", "exit_time", "closed_at_ms"))
        if entry_dt is None or entry_dt.timestamp() < since or exit_dt is None:
            continue
        cr = str(_g(t, "close_reason", "exit_reason") or "")
        eb = str(_g(t, "entered_by") or "")
        st = str(_g(t, "setup_type", "setup") or "")
        try:
            ok, _r = classify_close(close_reason=cr, entered_by=eb, entry_price=None,
                                    exit_price=None, net_pnl=None, hold_seconds=None, setup_type=st)
        except Exception:
            ok = True
        if not ok:
            continue
        try:
            if is_adopted_entry(entered_by=eb, source=str(_g(t, "source") or ""), close_reason=cr):
                continue
        except Exception:
            pass
        e_et, x_et = _et(entry_dt), _et(exit_dt)
        if e_et.date() >= x_et.date():
            continue
        try:
            if should_close_at_eod(t) is not True:
                continue
        except Exception:
            continue

        bucket = _tod_bucket(e_et)
        month_hist[e_et.strftime("%Y-%m")] += 1
        tod_hist[bucket] += 1
        weekday = e_et.weekday() < 5
        before_window = (e_et.hour * 60 + e_et.minute) < 945
        if weekday and before_window:
            same_day_pass_suspects += 1
        hold_d = (exit_dt - entry_dt).total_seconds() / 86400.0
        rows.append((e_et, x_et, bucket, hold_d, cr,
                     str(_g(t, "symbol") or "?"), str(_g(t, "side", "direction") or "?"),
                     st, weekday and before_window))

    rows.sort(key=lambda r: r[0])
    print(f"\n=== v339 EOD-LEAK TIMELINE — last {days}d — {len(rows)} leak trades ===\n")
    print(f"{'ENTRY (ET)':<17}{'tod':<5}{'held_d':>7}  {'sym':<6}{'side':<6}{'setup':<20}{'close_reason':<24}{'SAME-DAY-SUSPECT'}")
    for (e_et, x_et, bucket, hold_d, cr, sym, side, st, suspect) in rows:
        print(f"{e_et.strftime('%Y-%m-%d %H:%M'):<17}{bucket:<5}{hold_d:>7.1f}  {sym:<6}{side:<6}{st:<20}{cr:<24}{'  <== YES' if suspect else ''}")

    print(f"\nby ENTRY MONTH: {dict(sorted(month_hist.items()))}")
    print(f"by ENTRY time-of-day: {dict(tod_hist)}")
    print(f"\nSAME-DAY-PASS SUSPECTS (weekday entry BEFORE 15:45 → the 15:55 pass SHOULD have")
    print(f"  flattened them on entry day): {same_day_pass_suspects} of {len(rows)}")
    print("\n=== READING ===")
    print("• If leak entries cluster in OLD months (pre-2026-06) → mostly HISTORICAL residue;")
    print("  the v245/v261/v301/v322s stack likely already seals it → verify with 1-2 recent, then STAND DOWN.")
    print("• If SAME-DAY-PASS SUSPECTS are RECENT (entry >= ~2026-06-12) → a LIVE gap survives the")
    print("  stack → these entered mid-RTH, were should_close_at_eod=True, yet were NOT in _open_trades")
    print("  at 15:55 (state desync) OR check_eod_close skipped them → trace those specific trade_ids.")
    print("• LATE/AH/ON entries that rode over are EXPECTED to be owned by v261 re-sweep / next-boot")
    print("  missed-EOD sweep, NOT the same-day pass — judge those by whether they closed by next EOD.\n")


if __name__ == "__main__":
    main()
