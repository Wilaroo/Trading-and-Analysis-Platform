#!/usr/bin/env python3
"""
Targeted Regime-Universe Backfill (v4) — IB-only via the right source per type
=============================================================================
Lesson learned on this DGX: the "IB-direct" historical endpoint
(`_ib_service.get_historical_data`) returns 0 bars — it's a push-only
deployment. The REAL IB historical source is the queue → Windows IB Data
Pusher → IB Gateway → ib_historical_data (same path the universe scan uses).

So:
  • DAILY  (regime/breadth/FTD): read via GET /api/ib/historical?prefer_ib=true
    (served straight from the IB-sourced ib_historical_data collection).
  • INTRADAY (multi-TF lanes): enqueue in historical_data_requests and let the
    pusher fulfill from IB, then upsert the result tagged source="ib". This
    overwrites any Alpaca-sourced recent-window bars with genuine IB bars.

Run (backend up, IB Data Pusher running, queue ideally drained):
    python3 scripts/backfill_regime_universe.py            # daily only
    python3 scripts/backfill_regime_universe.py --intraday  # + IB intraday for trio
"""
import os
import sys
import json
import argparse
import urllib.request
import urllib.parse
from datetime import datetime, timezone

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND_DIR)


def _load_env():
    if os.environ.get("MONGO_URL") and os.environ.get("DB_NAME"):
        return
    try:
        from dotenv import load_dotenv
        load_dotenv()
        if os.environ.get("MONGO_URL") and os.environ.get("DB_NAME"):
            return
    except Exception:
        pass
    env_path = os.path.join(_BACKEND_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

from pymongo import MongoClient
from services.historical_data_queue_service import init_historical_data_queue_service

BASE = os.environ.get("REGIME_BACKFILL_BASE", "http://localhost:8001")

INDEX_TRIO = ["SPY", "QQQ", "IWM"]
SECTOR_ETFS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLC", "XLY", "XLP", "XLU", "XLRE", "XLB"]
DAILY_UNIVERSE = INDEX_TRIO + ["DIA"] + SECTOR_ETFS  # VIX historical skipped (live VIX used)
INTRADAY_PLAN = {"1 hour": "2 M", "5 mins": "10 D", "1 min": "3 D"}
PER_REQUEST_TIMEOUT = 180.0


# ---------- DAILY via endpoint (IB-sourced ib_historical_data) ----------
def _daily_via_endpoint(coll, symbol):
    q = urllib.parse.urlencode({"duration": "2 Y", "bar_size": "1 day", "prefer_ib": "true"})
    url = f"{BASE}/api/ib/historical/{urllib.parse.quote(symbol)}?{q}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=120) as r:
            resp = json.loads(r.read().decode())
    except Exception as e:
        print(f"  → {symbol:<5} 1 day  … ✗ {e}")
        return 0
    bars = resp.get("bars") or []
    print(f"  → {symbol:<5} 1 day  … ✓ {len(bars)} bars (source={resp.get('source')})")
    return len(bars)


# ---------- INTRADAY via queue (pusher → IB) ----------
def _upsert(coll, symbol, bar_size, bars):
    n = 0
    for b in bars:
        if not isinstance(b, dict):
            continue
        d = b.get("date") or b.get("time")
        if not d:
            continue
        coll.update_one(
            {"symbol": symbol, "bar_size": bar_size, "date": d},
            {"$set": {"open": b.get("open"), "high": b.get("high"), "low": b.get("low"),
                      "close": b.get("close"), "volume": b.get("volume"), "source": "ib",
                      "collected_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
        n += 1
    return n


def _intraday_via_queue(queue, coll, symbol, bar_size, duration):
    rid = queue.create_request(symbol=symbol, duration=duration, bar_size=bar_size)
    print(f"  → {symbol:<5} {bar_size:<7} ({duration}) [queue {rid}] … waiting", flush=True)
    result = queue.get_request_result(rid, timeout=PER_REQUEST_TIMEOUT)
    if result is None:
        print(f"    ⏱ TIMEOUT — is the IB Data Pusher running / queue drained?")
        return 0
    if result.get("status") != "completed" or not result.get("data"):
        print(f"    ✗ {result.get('error') or 'no data'}")
        return 0
    n = _upsert(coll, symbol, bar_size, result["data"])
    print(f"    ✓ stored {n} IB bars")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intraday", action="store_true")
    args = ap.parse_args()

    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    coll = db["ib_historical_data"]
    queue = init_historical_data_queue_service(db)

    print(f"=== Regime backfill v4 (daily=endpoint, intraday=queue→IB) via {BASE} ===\n")
    print("DAILY:")
    for s in DAILY_UNIVERSE:
        _daily_via_endpoint(coll, s)

    total_intraday = 0
    if args.intraday:
        print("\nINTRADAY (IB via pusher queue):")
        for s in INDEX_TRIO:
            for bs, dur in INTRADAY_PLAN.items():
                total_intraday += _intraday_via_queue(queue, coll, s, bs, dur)

        print("\n=== Intraday lane freshness (index trio) ===")
        for sym in INDEX_TRIO:
            for bs in INTRADAY_PLAN:
                row = list(coll.find({"symbol": sym, "bar_size": bs},
                                     {"_id": 0, "date": 1, "source": 1}).sort("date", -1).limit(1))
                if row:
                    print(f"  {sym:<5} {bs:<7}: latest {str(row[0]['date'])[:16]} "
                          f"(source={row[0].get('source', 'untagged')})")
                else:
                    print(f"  {sym:<5} {bs:<7}: none")

    print(f"\nDone. Intraday IB bars stored: {total_intraday}. Verify:\n"
          f'  curl -s "localhost:8001/api/market-regime/current?force_refresh=true" '
          f"| python3 -c \"import sys,json;print(json.dumps(json.load(sys.stdin).get('multi_tf'),indent=2))\"")


if __name__ == "__main__":
    main()
