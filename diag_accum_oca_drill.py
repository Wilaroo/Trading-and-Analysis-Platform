#!/usr/bin/env python3
"""
diag_accum_oca_drill.py — read-only drill into WHY `accumulation_entry`
(a POSITION setup) closes 84% intraday, dominated by `oca_closed_externally`.

Three questions:
  1. Per-trade tape: entry/exit/stop/target, hold time, close_reason, pnl —
     so we can SEE what the bracket looked like at close.
  2. Is MFE/MAE tracking populated ANYWHERE (last 30d, all setups)? If not,
     that's a separate observability bug, not specific to this setup.
  3. Is realized-R inflated by sub-1% stops (breakeven/tiny risk denominator)?

READ-ONLY.  .venv/bin/python /tmp/diag_accum_oca_drill.py [--days 120]
"""
import argparse
import os
from datetime import datetime, timezone, timedelta
from collections import Counter
from statistics import median

from pymongo import MongoClient

SETUP = "accumulation_entry"
NAME_FIELDS = ("setup_type", "setup_variant", "strategy_name")


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _matches(doc):
    return any(str(doc.get(k, "") or "").strip().lower() == SETUP for k in NAME_FIELDS)


def _hold_min(t):
    a, b = t.get("executed_at") or t.get("created_at"), t.get("closed_at")
    if not a or not b:
        return None
    try:
        da = datetime.fromisoformat(str(a).replace("Z", "+00:00"))
        db_ = datetime.fromisoformat(str(b).replace("Z", "+00:00"))
        return (db_ - da).total_seconds() / 60.0
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--rows", type=int, default=25)
    args = ap.parse_args()
    db = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017")).get_database(
        os.environ.get("DB_NAME", "tradecommand")
    )
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()

    closed = [t for t in db.bot_trades.find({"status": "closed"}, {"_id": 0})
              if _matches(t) and (t.get("closed_at") or "") >= since]

    print(f"\n{'='*92}\naccumulation_entry OCA/exit drill — last {args.days}d  (n={len(closed)})\n{'='*92}")
    if not closed:
        print("nothing to drill.")
        return

    # ---- 1. per-trade tape (newest first) ----
    print(f"\n--- per-trade tape (newest {args.rows}) ---")
    hdr = f"{'closed_at':<17}{'sym':<6}{'side':<5}{'hold':>7}{'entry':>9}{'exit':>9}{'stop':>9}{'targ':>9}{'pnl$':>9}  close_reason"
    print(hdr)
    for t in sorted(closed, key=lambda x: x.get("closed_at", ""), reverse=True)[:args.rows]:
        ps = t.get("protective_stop") or {}
        entry = _f(t.get("fill_price") or t.get("entry_price"))
        exit_ = _f(t.get("exit_price"))
        stop = _f(ps.get("original_stop")) or _f(ps.get("current_stop")) or _f(t.get("stop_price"))
        targ = _f((t.get("targets") or [{}])[0].get("price")) if t.get("targets") else _f(t.get("target_price"))
        hm = _hold_min(t)
        hs = f"{hm:.0f}m" if hm is not None and hm < 600 else (f"{hm/60:.0f}h" if hm is not None else "?")
        pnl = _f(t.get("net_pnl")) or _f(t.get("realized_pnl"))
        print(f"{str(t.get('closed_at',''))[:17]:<17}{t.get('symbol',''):<6}"
              f"{str(t.get('side') or t.get('direction','')):<5}{hs:>7}"
              f"{entry:>9.2f}{exit_:>9.2f}{stop:>9.2f}{targ:>9.2f}{pnl:>9.0f}  {t.get('close_reason','')}")

    # ---- hold distribution by close_reason ----
    print("\n--- hold-time (min) by close_reason ---")
    by = {}
    for t in closed:
        by.setdefault(t.get("close_reason", "?"), []).append(_hold_min(t))
    for reason, hs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        vals = [h for h in hs if h is not None]
        med = f"{median(vals):.0f}m" if vals else "?"
        print(f"  {reason:<32} n={len(hs):<3} median_hold={med}")

    # ---- 2. MFE/MAE population check (global, last 30d) ----
    g_since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    recent = list(db.bot_trades.find(
        {"status": "closed", "closed_at": {"$gte": g_since}},
        {"_id": 0, "mfe_r": 1, "mae_r": 1, "setup_type": 1}))
    nz = sum(1 for t in recent if _f(t.get("mfe_r")) != 0 or _f(t.get("mae_r")) != 0)
    print("\n--- MFE/MAE population (ALL setups, last 30d) ---")
    print(f"  {nz}/{len(recent)} closed trades have non-zero mfe_r OR mae_r"
          f"  ({(nz/len(recent)*100) if recent else 0:.0f}%)")
    print("  -> if ~0%, excursion tracking is globally not persisting (observability bug,")
    print("     and the reason the shaken-out detector is blind).")

    # ---- 3. inflated-R check (sub-1% stop) ----
    tight = 0
    for t in closed:
        ps = t.get("protective_stop") or {}
        entry = _f(t.get("fill_price") or t.get("entry_price"))
        stop = _f(ps.get("original_stop")) or _f(ps.get("current_stop")) or _f(t.get("stop_price"))
        if entry > 0 and stop > 0 and abs(entry - stop) / entry < 0.01:
            tight += 1
    print("\n--- R-inflation risk ---")
    print(f"  {tight}/{len(closed)} trades have a stop <1% from entry (tiny risk denom ->")
    print("     inflated realized-R; use MEDIAN R, not mean, for this setup).")

    # ---- close_reason summary ----
    print("\n--- close_reason counts ---")
    for r, c in Counter(t.get("close_reason", "?") for t in closed).most_common():
        print(f"  {c:>4}  {r}")
    print()


if __name__ == "__main__":
    main()
