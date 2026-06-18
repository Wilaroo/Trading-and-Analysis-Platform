#!/usr/bin/env python3
"""
diag_v365_leak_recency.py  (READ-ONLY leak-recency forensic).

The question this answers: are the suppressed setups (squeeze / vwap_bounce /
fashionably_late + first_move_up/down) ACTUALLY still firing on the *current*
(post-suppression) code, or are the counts that diag_live_setup_fires.py shows
just STALE pre-deploy fires from a session that ran BEFORE the suppression
patches were deployed + the backend restarted?

It prints, per watched setup, the MOST RECENT fire timestamps + ids from BOTH
live_alerts and bot_trades, plus "now", so you can compare the latest fire
against your last backend restart / today's market open.

VERDICT logic: if the latest fire for a suppressed setup is OLDER than the
moment suppression went live (your last restart), there is NO live leak — the
counts are pre-deploy residue. NOTHING IS WRITTEN.

Usage (repo root, DGX):
  .venv/bin/python backend/scripts/diag_v365_leak_recency.py --days 4
  # optional: pin the deploy/restart moment to get an automatic verdict:
  .venv/bin/python backend/scripts/diag_v365_leak_recency.py --days 4 --since "2026-06-17T16:30:00-04:00"
"""
import sys
from datetime import datetime, timedelta, timezone


WATCH = ["squeeze", "vwap_bounce", "fashionably_late", "first_move_up", "first_move_down"]


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


def _to_dt(v):
    try:
        if isinstance(v, datetime):
            return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _ts_of(doc, keys):
    for k in keys:
        v = doc.get(k)
        dt = _to_dt(v) if v else None
        if dt:
            return dt, k
    return None, None


def _recent_fires(db, coll, setup, cutoff, ts_keys, extra_proj):
    proj = {"_id": 0, "setup_type": 1, "id": 1, "symbol": 1, "strategy_name": 1}
    for k in ts_keys:
        proj[k] = 1
    for k in extra_proj:
        proj[k] = 1
    rows = []
    for d in db[coll].find({"setup_type": setup}, proj):
        dt, src = _ts_of(d, ts_keys)
        if dt and dt >= cutoff:
            rows.append((dt, src, d))
    rows.sort(key=lambda r: r[0], reverse=True)
    return rows


def main():
    days = _arg("--days", 4, int)
    since_raw = _arg("--since", None, str)
    since_dt = _to_dt(since_raw) if since_raw else None
    db = _load_db()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    print(f"\n=== diag_v365_leak_recency — now {now.isoformat(timespec='seconds')} ===")
    print(f"    window: last {days}d (cutoff {cutoff.isoformat(timespec='minutes')})")
    if since_dt:
        print(f"    suppression-live pin (--since): {since_dt.isoformat(timespec='seconds')}")
    print()

    alert_keys = ("created_at", "timestamp", "ts", "alert_time")
    trade_keys = ("created_at", "timestamp", "entry_time", "executed_at", "pre_submit_at")

    any_live_leak = False
    for setup in WATCH:
        la = _recent_fires(db, "live_alerts", setup, cutoff, alert_keys, ["priority"])
        bt = _recent_fires(db, "bot_trades", setup, cutoff, trade_keys, ["entered_by", "status"])
        print(f"--- {setup} ---")
        print(f"    live_alerts: {len(la)} in window   |   bot_trades: {len(bt)} in window")

        for label, rows in (("live_alerts", la), ("bot_trades", bt)):
            if not rows:
                print(f"      {label}: (none)")
                continue
            latest_dt = rows[0][0]
            age_h = (now - latest_dt).total_seconds() / 3600.0
            print(f"      {label}: latest {latest_dt.isoformat(timespec='seconds')} "
                  f"({age_h:.1f}h ago)")
            for dt, src, d in rows[:5]:
                idv = d.get("id") or d.get("symbol") or "?"
                extra = d.get("entered_by") or d.get("strategy_name") or ""
                print(f"          {dt.isoformat(timespec='seconds')}  [{src}]  {idv}  {extra}")
            if since_dt:
                post = [r for r in rows if r[0] >= since_dt]
                if post:
                    any_live_leak = True
                    print(f"      *** {len(post)} {label} fire(s) AFTER suppression-live "
                          f"({since_dt.isoformat(timespec='minutes')}) — REAL LEAK ***")
                else:
                    print(f"      OK — 0 {label} fires after suppression-live "
                          f"(all are pre-deploy residue)")
        print()

    print("=== verdict ===")
    if since_dt:
        if any_live_leak:
            print("  REAL LEAK: at least one suppressed setup fired AFTER suppression went live.")
        else:
            print("  NO LIVE LEAK: every suppressed-setup fire predates suppression-live —")
            print("  the diag_live_setup_fires counts are stale pre-deploy residue.")
    else:
        print("  Compare each 'latest' timestamp above against your LAST backend restart")
        print("  (when v359/v357/v354 went live). If the latest fire is OLDER than that")
        print("  restart, there is NO live leak — it's pre-deploy residue. Re-run with")
        print("  --since \"<restart ISO ts>\" for an automatic verdict, and re-confirm")
        print("  with zero new fires after today's RTH open.")
    print()


if __name__ == "__main__":
    main()
