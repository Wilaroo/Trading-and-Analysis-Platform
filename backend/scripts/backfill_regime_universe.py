#!/usr/bin/env python3
"""
Targeted Regime-Universe Backfill
=================================
Populates `ib_historical_data` for ONLY the symbols the Market Regime Engine
needs, so regime / breadth / FTD compute on fresh, complete daily bars instead
of leaning on per-cycle live IB fallbacks.

Why this exists
---------------
The full-universe collector floods the queue (tens of thousands pending). This
script enqueues just the regime trio + sector ETFs + VIX and POLLS those exact
request_ids to completion, so it returns in minutes even while the universe
scan is running. It reuses the SAME queue + IB Data Pusher path the universe
backfill uses (the pusher must be running — it already is if your universe scan
is going).

Run (from the backend dir, pusher running):
    cd backend
    python3 scripts/backfill_regime_universe.py            # daily only (regime/breadth/FTD)
    python3 scripts/backfill_regime_universe.py --intraday  # + 1h/5m/1m for the index trio (multi-TF prep)

Safe to re-run: requests dedupe on (symbol, bar_size, end_date); bars upsert.
"""
import os
import sys
import argparse
from datetime import datetime, timezone

# Make `services...` importable when run from backend/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from pymongo import MongoClient
from services.historical_data_queue_service import init_historical_data_queue_service

# --- Regime universe (must match market_regime_engine.py) -------------------
INDEX_TRIO = ["SPY", "QQQ", "IWM"]
SECTOR_ETFS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLC", "XLY", "XLP", "XLU", "XLRE", "XLB"]
VIX = ["VIX"]
DAILY_UNIVERSE = INDEX_TRIO + ["DIA"] + SECTOR_ETFS + VIX

# bar_size -> IB duration. Daily covers sma_200 (needs >=200) + FTD 25-day window.
DAILY_PLAN = {"1 day": "2 Y"}
# Intraday is for the upcoming multi-timeframe regime layer (index trio only).
INTRADAY_PLAN = {"1 hour": "2 M", "5 mins": "10 D", "1 min": "3 D"}

PER_REQUEST_TIMEOUT = 240.0  # IB can be slow; pusher interleaves with universe scan


def _upsert_bars(coll, symbol, bar_size, bars):
    stored = 0
    for bar in bars:
        d = bar.get("date") or bar.get("time")
        if not d:
            continue
        coll.update_one(
            {"symbol": symbol, "bar_size": bar_size, "date": d},
            {"$set": {
                "open": bar.get("open"),
                "high": bar.get("high"),
                "low": bar.get("low"),
                "close": bar.get("close"),
                "volume": bar.get("volume"),
                "collected_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        stored += 1
    return stored


def _fetch_one(queue, coll, symbol, bar_size, duration):
    rid = queue.create_request(symbol=symbol, duration=duration, bar_size=bar_size)
    print(f"  → queued {symbol:<5} {bar_size:<7} ({duration})  [{rid}] … waiting", flush=True)
    result = queue.get_request_result(rid, timeout=PER_REQUEST_TIMEOUT)
    if result is None:
        print(f"    ⏱  TIMEOUT {symbol} {bar_size} — is the IB Data Pusher running?")
        return 0
    if result.get("status") != "completed" or not result.get("data"):
        print(f"    ✗ FAILED {symbol} {bar_size}: {result.get('error') or 'no data'}")
        return 0
    n = _upsert_bars(coll, symbol, bar_size, result["data"])
    print(f"    ✓ {symbol} {bar_size}: stored {n} bars")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intraday", action="store_true",
                    help="also backfill 1h/5m/1m for SPY/QQQ/IWM (multi-TF prep)")
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    client = MongoClient(mongo_url)
    db = client[db_name]
    coll = db["ib_historical_data"]
    queue = init_historical_data_queue_service(db)

    print(f"=== Targeted Regime-Universe Backfill ({db_name}) ===")
    plan = []
    for sym in DAILY_UNIVERSE:
        for bs, dur in DAILY_PLAN.items():
            plan.append((sym, bs, dur))
    if args.intraday:
        for sym in INDEX_TRIO:
            for bs, dur in INTRADAY_PLAN.items():
                plan.append((sym, bs, dur))
    print(f"Plan: {len(plan)} requests across {len(set(p[0] for p in plan))} symbols\n")

    total = 0
    for sym, bs, dur in plan:
        total += _fetch_one(queue, coll, sym, bs, dur)

    # --- Verify: latest 2 daily bars per regime symbol -----------------------
    print("\n=== Verification (latest daily bar per symbol) ===")
    for sym in DAILY_UNIVERSE:
        rows = list(coll.find(
            {"symbol": sym, "bar_size": "1 day"},
            {"_id": 0, "date": 1, "close": 1},
        ).sort("date", -1).limit(2))
        if len(rows) >= 2 and rows[1].get("close"):
            chg = (rows[0]["close"] - rows[1]["close"]) / rows[1]["close"] * 100
            n = coll.count_documents({"symbol": sym, "bar_size": "1 day"})
            print(f"  {sym:<5} {n:>4} daily bars | latest {str(rows[0]['date'])[:10]} "
                  f"close={rows[0]['close']} chg={chg:+.2f}%")
        else:
            print(f"  {sym:<5} ⚠ insufficient daily bars ({len(rows)})")

    print(f"\nDone. Stored {total} bars total. "
          f"Force a regime refresh to pick them up:\n"
          f'  curl -s "localhost:8001/api/market-regime/current?force_refresh=true" | python3 -m json.tool')


if __name__ == "__main__":
    main()
