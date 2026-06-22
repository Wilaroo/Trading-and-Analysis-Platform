#!/usr/bin/env python3
"""
diag_a9_entry_provenance.py — READ-ONLY. Answers: were the post-restart
Stage-2 breakout fills FRESH real-time decisions, or a STALE backlog that
only flushed once the scanner came back?

For every open bot_trade it joins to the originating alert (by alert_id, with
a symbol+setup fallback) and prints:
  * when the position OPENED (executed_at / created_at)
  * when the ALERT was CREATED (the moment the system decided)
  * LAG between them  (seconds the alert "sat" before it fired)
  * entry vs the alert's trigger price (fired at the level, or chased?)
  * TQS score at decision time (the system's real-time quality verdict)
  * a VERDICT per position.

Classification (times in UTC):
  FRESH        — alert created AFTER the resurrection (>= RESTART) and fired
                 within FRESH_LAG_MIN minutes -> a real-time decision.
  BACKLOGGED   — alert created BEFORE the scanner death (<= DEATH) but the
                 position opened AFTER the resurrection -> stale flush.
  PRE_EXISTING — position opened before today -> part of the standing book.
  REVIEW       — anything that doesn't fit cleanly (inspect by hand).

GET-only against Mongo. No writes.

Run from the repo root:
    PYTHONPATH=backend .venv/bin/python backend/scripts/diag_a9_entry_provenance.py
"""
import os
from pathlib import Path
from datetime import datetime, timezone

# --- scanner timeline for 2026-06-22 (UTC) ---
DEATH = "2026-06-22T15:00:00+00:00"      # last clean alert ~15:04Z
RESTART = "2026-06-22T17:50:00+00:00"    # manual /start ~17:51Z, --force boot ~17:55Z
FRESH_LAG_MIN = 20                       # alert->fire lag that still counts as real-time
TODAY = "2026-06-22"


def _load_env():
    for cand in ["backend/.env", ".env",
                 os.path.join(os.path.dirname(__file__), "..", ".env")]:
        p = Path(cand)
        if p.is_file():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def _dt(s):
    if not s:
        return None
    try:
        s = str(s).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _f(d, *keys, default=0.0):
    for k in keys:
        v = d.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return default


def _s(d, *keys, default=""):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return str(v)
    return default


def main():
    _load_env()
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=20000)[os.environ["DB_NAME"]]
    death, restart = _dt(DEATH), _dt(RESTART)

    # Open positions.
    trades = list(db["bot_trades"].find({"status": "open"}))
    if not trades:
        trades = list(db["bot_trades"].find({"status": {"$nin": ["closed", "cancelled", "exited", "flat"]}}))
    print(f"== A9 entry-provenance · now={datetime.now(timezone.utc).isoformat()} ==")
    print(f"   DEATH={DEATH}  RESTART={RESTART}  fresh-lag<= {FRESH_LAG_MIN}m\n")
    print(f"open bot_trades: {len(trades)}\n")

    # Pre-index today's alerts for the symbol+setup fallback join.
    alert_by_id = {}
    sym_setup = {}
    for a in db["live_alerts"].find({"created_at": {"$regex": f"^{TODAY}"}}):
        aid = a.get("id")
        if aid:
            alert_by_id[aid] = a
        sym_setup.setdefault((a.get("symbol"), a.get("setup_type")), []).append(a)

    hdr = (f"{'SYM':<6} {'SETUP':<18} {'OPENED(UTC)':<20} {'ALERT_CREATED':<20} "
           f"{'LAG':>8} {'ENTRY':>9} {'TRIG':>9} {'TQS':>5}  VERDICT")
    print(hdr); print("-" * len(hdr))

    counts = {}
    for t in sorted(trades, key=lambda x: _s(x, "executed_at", "created_at")):
        sym = _s(t, "symbol", default="?")
        setup = _s(t, "setup_type", "setup", "strategy_name", default="?")
        opened = _dt(_s(t, "executed_at", "created_at", "entry_time", "opened_at"))
        entry = _f(t, "entry_price", "avg_entry_price", "avg_cost")
        aid = _s(t, "alert_id")

        alert = alert_by_id.get(aid)
        if not alert:
            cands = sym_setup.get((sym, setup), [])
            if cands and opened:
                cands2 = [c for c in cands if (_dt(c.get("created_at")) and _dt(c.get("created_at")) <= opened)]
                if cands2:
                    alert = max(cands2, key=lambda c: _dt(c.get("created_at")))
                elif cands:
                    alert = min(cands, key=lambda c: abs((_dt(c.get("created_at")) - opened).total_seconds()) if _dt(c.get("created_at")) else 9e9)

        a_created = _dt(alert.get("created_at")) if alert else None
        trig = _f(alert, "trigger_price", "current_price", "entry_price") if alert else 0.0
        tqs = _f(alert, "tqs_score") if alert else 0.0

        lag_str = "—"
        if opened and a_created:
            lag_s = (opened - a_created).total_seconds()
            lag_str = f"{lag_s/60:.0f}m" if abs(lag_s) < 36000 else f"{lag_s/3600:.1f}h"

        # classify
        verdict = "REVIEW"
        if opened and not str(_s(t, "executed_at", "created_at")).startswith(TODAY):
            verdict = "PRE_EXISTING"
        elif a_created and restart and a_created >= restart:
            if opened and (opened - a_created).total_seconds() <= FRESH_LAG_MIN * 60:
                verdict = "FRESH"
            else:
                verdict = "FRESH?"
        elif a_created and death and a_created <= death and opened and restart and opened >= restart:
            verdict = "BACKLOGGED"
        elif not a_created:
            verdict = "NO_ALERT_LINK"

        counts[verdict] = counts.get(verdict, 0) + 1
        oc = opened.strftime("%m-%d %H:%M:%S") if opened else "—"
        ac = a_created.strftime("%m-%d %H:%M:%S") if a_created else "—"
        print(f"{sym:<6} {setup[:18]:<18} {oc:<20} {ac:<20} {lag_str:>8} "
              f"{entry:>9.2f} {trig:>9.2f} {tqs:>5.0f}  {verdict}")

    print("\n── provenance summary ──")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k:<14} {v}")
    print("\nREAD:")
    print("  FRESH/FRESH?  -> alert born AFTER restart; system decided in real time at fire.")
    print("  BACKLOGGED    -> alert born BEFORE the 15:00Z death, only fired post-restart (STALE flush).")
    print("  PRE_EXISTING  -> standing multi-day/position book opened earlier this week.")
    print("  NO_ALERT_LINK -> trade has no joinable alert (inspect alert_id plumbing).")


if __name__ == "__main__":
    main()
