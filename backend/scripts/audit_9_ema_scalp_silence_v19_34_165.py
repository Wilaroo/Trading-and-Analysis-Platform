#!/usr/bin/env python3
"""v19.34.165 — Why did the `9_ema_scalp` scanner go silent on March 11?

Investigation prompted by the v19.34.164 trade_drops fix: scanner emitted
251 `9_ema_scalp` alerts total ever (per `live_alerts`), but ZERO since
2026-03-11. This script reads the scanner's gating rules and the
historical data to triage the most likely cause without touching code.

Checks performed (read-only):
  1. Last 10 `9_ema_scalp` emissions from `live_alerts` (when did it die?)
  2. Daily emission histogram over the last 90d (cliff or gradual decay?)
  3. The 3 hard gates inside `enhanced_scanner.py`:
       a. Setup time-of-day window  — `_MORNING_ONLY` for 9_ema_scalp
       b. Universe filter            — symbol must be in scan universe
       c. Regime filter              — must be STRONG_UPTREND or MOMENTUM
  4. Last 30 days of `market_regime` history — was the regime ever in
     STRONG_UPTREND or MOMENTUM in the morning window since March 11?
  5. KOS-specific check — the only symbol that ever fired 9_ema_scalp;
     is it still in the scan universe?

Output: human-readable triage report with a verdict.

Usage:
    cd ~/Trading-and-Analysis-Platform && source .venv/bin/activate
    DB_NAME=tradecommand python backend/scripts/audit_9_ema_scalp_silence_v19_34_165.py
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient


def hr(title: str) -> None:
    print(f"\n{'=' * 70}\n  {title}\n{'=' * 70}")


def main() -> int:
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "tradecommand")
    db = MongoClient(mongo_url)[db_name]

    now = datetime.now(timezone.utc)

    # ─── 1. Last 10 emissions ────────────────────────────────────────
    hr("1. Last 10 `9_ema_scalp` scanner emissions (when did it die?)")
    rows = list(db.live_alerts.find(
        {"setup_type": {"$regex": "9_?ema_scalp", "$options": "i"}},
        {"_id": 0, "symbol": 1, "setup_type": 1, "created_at": 1,
         "direction": 1},
    ).sort("created_at", -1).limit(10))
    if not rows:
        print("  No `9_ema_scalp` emissions in `live_alerts` AT ALL.")
        return 0
    for r in rows:
        ts = r.get("created_at", "?")
        print(f"  {ts}  {r.get('symbol','?'):<6}  {r.get('setup_type','?')}"
              f"  {r.get('direction','?')}")
    last_ts = rows[0].get("created_at", "")
    print(f"\n  → Last emission: {last_ts}")
    try:
        last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
        gap = now - last_dt
        print(f"  → Gap since last: {gap.days} days, "
              f"{gap.seconds // 3600} hours")
    except Exception:
        pass

    # ─── 2. Daily histogram over last 90d ────────────────────────────
    hr("2. Daily emission histogram (last 90 days)")
    cutoff = (now - timedelta(days=90)).isoformat()
    bydate: Counter = Counter()
    for r in db.live_alerts.find(
        {"setup_type": {"$regex": "9_?ema_scalp", "$options": "i"},
         "created_at": {"$gte": cutoff}},
        {"_id": 0, "created_at": 1},
    ):
        ts = r.get("created_at", "")
        if isinstance(ts, str) and len(ts) >= 10:
            bydate[ts[:10]] += 1
    if not bydate:
        print("  Zero emissions in last 90d.")
    else:
        for day in sorted(bydate.keys()):
            bar = "█" * min(50, bydate[day])
            print(f"  {day}  {bydate[day]:>4}  {bar}")
        print(f"\n  → {sum(bydate.values())} total in last 90d "
              f"across {len(bydate)} distinct days.")

    # ─── 3. Scanner regime / time-of-day config ─────────────────────
    hr("3. Scanner gates for `9_ema_scalp` (from enhanced_scanner.py)")
    print("  Hard-coded constraints (NOT reading the file — these are the")
    print("  documented defaults; cross-verify if it doesn't add up):")
    print("    a. Time-of-day window:  _MORNING_ONLY (before ~11am ET)")
    print("    b. Regime filter:       STRONG_UPTREND or MOMENTUM")
    print("    c. Symbol tier:         momentum-tier / not swing-only")

    # ─── 4. Regime history check ─────────────────────────────────────
    hr("4. Was the regime ever in STRONG_UPTREND / MOMENTUM since 2026-03-11?")
    cutoff = "2026-03-11"
    regime_counts: Counter = Counter()
    try:
        for coll_name in ["market_regime_history", "market_regime",
                          "regime_snapshots"]:
            if coll_name not in db.list_collection_names():
                continue
            print(f"\n  Reading collection: {coll_name}")
            sample = db[coll_name].find_one({})
            if not sample:
                print("    (empty)")
                continue
            # Find a timestamp field
            ts_field = None
            for cand in ("ts", "timestamp", "created_at", "as_of", "date"):
                if cand in sample:
                    ts_field = cand
                    break
            regime_field = None
            for cand in ("regime", "current_regime", "market_regime", "name"):
                if cand in sample:
                    regime_field = cand
                    break
            if not ts_field or not regime_field:
                print(f"    schema unclear — fields: {list(sample.keys())[:10]}")
                continue
            n = 0
            for doc in db[coll_name].find(
                {ts_field: {"$gte": cutoff}},
                {"_id": 0, ts_field: 1, regime_field: 1},
            ).limit(20000):
                regime_counts[str(doc.get(regime_field))] += 1
                n += 1
            print(f"    Read {n} regime snapshots since {cutoff}")
            break
    except Exception as exc:
        print(f"  Error: {exc}")

    if regime_counts:
        for reg, ct in regime_counts.most_common(10):
            print(f"    {reg:<30}  {ct}")
        favorable = sum(
            ct for r, ct in regime_counts.items()
            if r.upper() in {"STRONG_UPTREND", "MOMENTUM"}
        )
        total = sum(regime_counts.values())
        pct = (favorable / total * 100) if total else 0
        print(f"\n  → Favorable regime hits: {favorable}/{total} ({pct:.1f}%)")
        if favorable == 0:
            print("  ⚠ VERDICT: Regime has NEVER been STRONG_UPTREND or MOMENTUM")
            print("    since the silence started → this is the most likely cause.")

    # ─── 5. KOS-specific universe check ──────────────────────────────
    hr("5. KOS-specific check (only symbol that ever fired 9_ema_scalp)")
    try:
        for coll in ["scan_universe", "watchlist", "active_symbols",
                     "trading_universe", "smart_watchlist"]:
            if coll in db.list_collection_names():
                cnt = db[coll].count_documents({
                    "$or": [
                        {"symbol": "KOS"},
                        {"ticker": "KOS"},
                        {"symbols": "KOS"},
                        {"_id": "KOS"},
                    ],
                })
                print(f"  {coll}: KOS present? {cnt > 0}  (matched {cnt} docs)")
    except Exception as exc:
        print(f"  Error: {exc}")

    # ─── 6. Final verdict guidance ───────────────────────────────────
    hr("Triage summary")
    print("  Most likely cause priority:")
    print("    1. ⓞ Regime gate — if §4 showed 0% favorable since 03-11")
    print("    2. ⓘ Symbol universe — if §5 shows KOS dropped from universe")
    print("    3. ⓞ Time-of-day gate — verify your bot's scan window")
    print("    4. ⓘ Setup detector deactivated — check enhanced_scanner.py")
    print("       around line 129 for `9_ema_scalp: _MORNING_ONLY` and verify")
    print("       no recent commit disabled the `_check_9_ema_scalp` method.")
    print("\n  Re-run after enabling v165 setups; if 9_ema_scalp is still")
    print("  silent post-enable, focus on §4 regime gate first.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
