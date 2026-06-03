#!/usr/bin/env python3
"""
backfill_v19_34_240_hygiene.py — one-time, IDEMPOTENT de-pollution for the
trade-outcome hygiene work (v19.34.240).

Three jobs (all best-effort, all safe to re-run):
  1. REBUILD `strategy_stats` from GENUINE closed `bot_trades` only, over a
     lookback window. This is the important one — it CORRECTS the currently
     polluted EV scoreboard (the diag showed accumulation_entry was ~94%
     phantom/drift artifacts inflating R to +13/+16).
  2. RETRO-TAG existing `alert_outcomes` rows with genuine / hygiene_tag so the
     gameplan edge ranker + any reader can filter historical pollution.
  3. BACKFILL `bot_trades` mfe_r / mae_r from the realized entry->exit excursion
     where the manage loop left them 0 (Part B observability).

Run on the DGX:  .venv/bin/python /tmp/backfill_v19_34_240_hygiene.py [--days 120] [--dry-run]
READ-MODIFY: writes only to strategy_stats / alert_outcomes / bot_trades stat
fields. Touches NO order logic and NO open positions.
"""
import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from pymongo import MongoClient

# import the canonical hygiene classifier (same one the live path uses)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
sys.path.insert(0, os.path.join(os.getcwd(), "backend"))
from services.trade_outcome_hygiene import classify_close, excursion_floor  # noqa: E402


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _base_setup(s: str) -> str:
    s = str(s or "").strip().lower()
    for suf in ("_long", "_short"):
        if s.endswith(suf):
            return s[: -len(suf)]
    return s


def _hold_seconds(t):
    a = t.get("executed_at") or t.get("created_at")
    b = t.get("closed_at")
    if not a or not b:
        return None
    try:
        da = datetime.fromisoformat(str(a).replace("Z", "+00:00"))
        db_ = datetime.fromisoformat(str(b).replace("Z", "+00:00"))
        return (db_ - da).total_seconds()
    except Exception:
        return None


def _r_multiple(t):
    entry = _f(t.get("fill_price") or t.get("entry_price"))
    stop = _f((t.get("protective_stop") or {}).get("original_stop")) or _f(t.get("stop_price"))
    ex = _f(t.get("exit_price"))
    d = str(t.get("direction") or t.get("side") or "long").lower()
    if entry <= 0 or ex <= 0:
        return 0.0
    rps = abs(entry - stop) if stop > 0 else entry * 0.02
    if rps <= 0:
        rps = entry * 0.02
    move = (ex - entry) if d.startswith("l") else (entry - ex)
    return move / rps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    db = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017")).get_database(
        os.environ.get("DB_NAME", "tradecommand")
    )
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    DRY = args.dry_run
    tag = "[DRY-RUN] " if DRY else ""
    print(f"\n{tag}v19.34.240 hygiene backfill — lookback {args.days}d (since {since[:10]})\n")

    closed = list(db.bot_trades.find(
        {"status": "closed", "closed_at": {"$gte": since}}, {"_id": 0}))
    print(f"closed bot_trades in window: {len(closed)}")

    # ---- JOB 1: rebuild strategy_stats from GENUINE trades only ----
    agg = defaultdict(lambda: {"wins": 0, "losses": 0, "r_sum": 0.0, "pnl_sum": 0.0, "n": 0})
    genuine_n = artifact_n = 0
    for t in closed:
        g, _ = classify_close(
            close_reason=t.get("close_reason"),
            entered_by=str(t.get("entered_by", "") or ""),
            entry_price=_f(t.get("fill_price") or t.get("entry_price")),
            exit_price=_f(t.get("exit_price")),
            net_pnl=_f(t.get("net_pnl") or t.get("realized_pnl")),
            hold_seconds=_hold_seconds(t),
            setup_type=str(t.get("setup_type") or t.get("setup_variant") or ""),
        )
        if not g:
            artifact_n += 1
            continue
        genuine_n += 1
        base = _base_setup(t.get("setup_type") or t.get("setup_variant"))
        if not base:
            continue
        r = _r_multiple(t)
        if abs(r) > 20.0:
            continue
        pnl = _f(t.get("net_pnl") or t.get("realized_pnl"))
        a = agg[base]
        a["n"] += 1
        a["r_sum"] += r
        a["pnl_sum"] += pnl
        if pnl > 0:
            a["wins"] += 1
        else:
            a["losses"] += 1
    print(f"  genuine={genuine_n}  artifacts_excluded={artifact_n}")
    print("\n  rebuilt strategy_stats (genuine-only):")
    print(f"  {'setup':<26}{'n':>4}{'win%':>7}{'avgR':>8}{'netPnL':>11}")
    for base, a in sorted(agg.items(), key=lambda kv: -kv[1]["n"]):
        n = a["n"] or 1
        win = a["wins"] / n * 100
        avg_r = a["r_sum"] / n
        print(f"  {base:<26}{a['n']:>4}{win:>6.0f}%{avg_r:>+8.2f}{a['pnl_sum']:>+11.0f}")
        if not DRY:
            db.strategy_stats.update_one(
                {"setup_type": base},
                {"$set": {
                    "setup_type": base,
                    "total_trades": a["n"],
                    "wins": a["wins"], "losses": a["losses"],
                    "win_rate": round(a["wins"] / n, 4),
                    "avg_r": round(avg_r, 4),
                    "expectancy_r": round(avg_r, 4),
                    "net_pnl": round(a["pnl_sum"], 2),
                    "genuine_only": True,
                    "recomputed_by": "backfill_v19_34_240",
                    "recomputed_at": datetime.now(timezone.utc).isoformat(),
                }},
                upsert=True,
            )

    # ---- JOB 2: retro-tag alert_outcomes ----
    ao = list(db.alert_outcomes.find({"created_at": {"$gte": since}}, {"_id": 1}))
    ao_full = list(db.alert_outcomes.find({"created_at": {"$gte": since}}))
    tagged = 0
    for o in ao_full:
        if "genuine" in o:
            continue
        g, htag = classify_close(
            close_reason=o.get("close_reason") or o.get("reason"),
            entered_by=str(o.get("entered_by", "") or ""),
            entry_price=_f(o.get("entry_price") or o.get("fill_price")),
            exit_price=_f(o.get("exit_price")),
            net_pnl=_f(o.get("net_pnl") or o.get("pnl")),
            hold_seconds=None,
        )
        if not DRY:
            db.alert_outcomes.update_one(
                {"_id": o["_id"]}, {"$set": {"genuine": g, "hygiene_tag": htag}})
        if not g:
            tagged += 1
    print(f"\n  alert_outcomes scanned={len(ao)}  newly tagged non-genuine={tagged}")

    # ---- JOB 3: backfill bot_trades mfe_r / mae_r excursion floor ----
    filled = 0
    for t in closed:
        if _f(t.get("mfe_r")) != 0 or _f(t.get("mae_r")) != 0:
            continue
        entry = _f(t.get("fill_price") or t.get("entry_price"))
        ex = _f(t.get("exit_price"))
        stop = _f((t.get("protective_stop") or {}).get("original_stop")) or _f(t.get("stop_price"))
        d = str(t.get("direction") or t.get("side") or "long")
        mfe, mae = excursion_floor(d, entry, ex, stop)
        if mfe == 0 and mae == 0:
            continue
        filled += 1
        if not DRY:
            tid = t.get("trade_id") or t.get("id")
            if tid:
                db.bot_trades.update_one(
                    {"$or": [{"trade_id": tid}, {"id": tid}]},
                    {"$set": {"mfe_r": round(mfe, 3), "mae_r": round(mae, 3),
                              "excursion_floor_source": "backfill_v19_34_240"}})
    print(f"  bot_trades excursion floor filled={filled}")

    print(f"\n{tag}done.{' (no writes)' if DRY else ''}\n")


if __name__ == "__main__":
    main()
