#!/usr/bin/env python3
"""
EOD-TRUST RECONCILIATION (read-only) — who actually closed last week's positions?

Buckets every CLOSED bot_trade from the last N days by close_reason into:
  • EOD_AUTO     — the bot's automated EOD sequence closed it   (eod_auto_close / eod_window_* / eod_auto_close_v162)
  • UI_OPERATOR  — YOU closed it via an app button              (manual / manual_panel_close / manual_eod_close / manual_close)
  • IB_EXTERNAL  — closed at IB directly (TWS) or bracket filled externally, bot reconciled it
                   (external_close* / operator_external_flatten / oca_closed_externally* / *_external_close)
  • STRATEGY     — normal strategy exit (target / stop / trail / time-decay)
  • REAPED/OTHER — stale-pending reaper rejects + anything uncategorised

Then cross-checks against the authoritative bot_events.eod_auto_close summary, and
FLAGS any UI_OPERATOR / IB_EXTERNAL close that happened INSIDE the EOD window
(15:40–16:30 ET) — those are the "bot should have closed it at EOD but I had to"
cases that test EOD trust.

Robust to closed_at being stored as either an ISO string OR a BSON datetime.

Usage: cd ~/Trading-and-Analysis-Platform && .venv/bin/python backend/scripts/eod_trust_reconcile.py [DAYS]
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
    """closed_at may be ISO string OR datetime. Return tz-aware UTC datetime or None."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _bucket(reason: str) -> str:
    r = (reason or "").lower()
    # order matters: external first, then operator-manual, then eod, then strategy
    if "external" in r or "oca_closed_external" in r:
        return "IB_EXTERNAL"
    if "manual" in r or "operator" in r or "panel_close" in r:
        return "UI_OPERATOR"
    if "eod" in r:
        return "EOD_AUTO"
    if "reaper" in r or "stale_pending" in r:
        return "REAPED/OTHER"
    if any(k in r for k in ("target", "stop", "trail", "time_decay", "decay", "tp_", "profit")):
        return "STRATEGY"
    return "REAPED/OTHER"


def main():
    db = _load_db()
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS)
    print(f"EOD-TRUST RECONCILIATION — closed trades in the last {DAYS} days "
          f"(since {cutoff.date()})\n")

    # Pull recent closed trades by _id (ObjectId embeds creation time → robust),
    # then filter in Python by parsed closed_at (handles str OR datetime).
    rows = []
    for t in db.bot_trades.find({"status": "closed"}).sort("_id", -1).limit(5000):
        cdt = _parse_dt(t.get("closed_at")) or _parse_dt(t.get("timestamp"))
        if cdt is None or cdt < cutoff:
            continue
        rows.append((cdt, t))

    # day -> bucket -> [count, pnl, symbols]
    by_day = defaultdict(lambda: defaultdict(lambda: [0, 0.0, []]))
    eod_window_manual = []  # (et_time, symbol, bucket, reason, pnl)
    for cdt, t in rows:
        et = cdt.astimezone(ET)
        day = et.strftime("%Y-%m-%d")
        b = _bucket(t.get("close_reason"))
        pnl = float(t.get("realized_pnl") or t.get("net_pnl") or 0)
        cell = by_day[day][b]
        cell[0] += 1
        cell[1] += pnl
        cell[2].append(t.get("symbol", "?"))
        # EOD-window cleanup flag (15:40–16:30 ET) for operator/external closes
        if b in ("UI_OPERATOR", "IB_EXTERNAL") and (15, 40) <= (et.hour, et.minute) <= (16, 30):
            eod_window_manual.append((et.strftime("%Y-%m-%d %H:%M"), t.get("symbol", "?"),
                                      b, t.get("close_reason", ""), pnl))

    buckets = ["EOD_AUTO", "UI_OPERATOR", "IB_EXTERNAL", "STRATEGY", "REAPED/OTHER"]
    print(f"{'date':<12} " + " ".join(f"{b:>13}" for b in buckets))
    tot = defaultdict(lambda: [0, 0.0])
    for day in sorted(by_day, reverse=True):
        cells = []
        for b in buckets:
            c, p, _ = by_day[day][b]
            tot[b][0] += c
            tot[b][1] += p
            cells.append(f"{c:>4} ${p:>7.0f}" if c else f"{'·':>13}")
        print(f"{day:<12} " + " ".join(cells))
    print(f"{'TOTAL':<12} " + " ".join(f"{tot[b][0]:>4} ${tot[b][1]:>7.0f}" for b in buckets))

    # Authoritative EOD summary from bot_events.
    print("\n=== bot_events.eod_auto_close (authoritative EOD summary) ===")
    for d in db.bot_events.find({"event_type": "eod_auto_close"}).sort("timestamp", -1).limit(12):
        cdt = _parse_dt(d.get("timestamp"))
        if cdt and cdt >= cutoff:
            print(f"  {d.get('date')} {d.get('close_time_et'):<9} "
                  f"closed={d.get('positions_closed'):<3} failed={d.get('positions_failed'):<2} "
                  f"ib_count={d.get('ib_position_count'):<3} pnl=${d.get('total_pnl',0):>8.2f} "
                  f"failed_syms={d.get('failed_symbols')} early={d.get('early_exit_reason')}")

    # THE KEY SIGNAL: closes you had to do in the EOD window.
    print("\n=== ⚠ EOD-WINDOW CLEANUP (manual/IB closes 15:40–16:30 ET — possible EOD misses) ===")
    if not eod_window_manual:
        print("  NONE — every position in the EOD window was closed by the bot. ✅")
    else:
        for ts, sym, b, reason, pnl in sorted(eod_window_manual, reverse=True):
            print(f"  {ts}  {sym:<6} {b:<12} {reason:<32} pnl=${pnl:+.2f}")
        print(f"\n  >>> {len(eod_window_manual)} position(s) you/IB closed in the EOD window — "
              f"investigate why the bot didn't auto-close these.")


if __name__ == "__main__":
    main()
