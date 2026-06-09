#!/usr/bin/env python3
"""
Targeted Regime-Universe Backfill (IB-DIRECT, queue-free)
========================================================
Populates `ib_historical_data` for ONLY the symbols the Market Regime Engine
needs (regime trio + sector ETFs + VIX), plus intraday 1h/5m/1m for the index
trio used by the multi-timeframe lanes.

Why the rewrite (v2)
--------------------
The first version enqueued into the historical_data_requests queue — which on
this DGX is drained by the Windows IB Data Pusher behind a ~500k-deep universe
collection, so our requests starved. This deployment fetches history DIRECTLY
via IB through `GET /api/ib/historical/{symbol}` (ib-direct, no queue). This
script hits that endpoint per (symbol, timeframe), then upserts the bars into
`ib_historical_data` so the regime engine's _get_tf_bars() can read them.

Run (backend running on :8001, IB connected):
    python3 scripts/backfill_regime_universe.py            # daily only
    python3 scripts/backfill_regime_universe.py --intraday  # + 1h/5m/1m for trio

Safe to re-run (bars upsert). If IB is momentarily busy a symbol returns 503 —
just re-run; completed symbols are skipped fast.
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

BASE = os.environ.get("REGIME_BACKFILL_BASE", "http://localhost:8001")

INDEX_TRIO = ["SPY", "QQQ", "IWM"]
SECTOR_ETFS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLC", "XLY", "XLP", "XLU", "XLRE", "XLB"]
VIX = ["VIX"]
DAILY_UNIVERSE = INDEX_TRIO + ["DIA"] + SECTOR_ETFS + VIX

DAILY_PLAN = {"1 day": "2 Y"}
INTRADAY_PLAN = {"1 hour": "2 M", "5 mins": "10 D", "1 min": "3 D"}


def _http_fetch(symbol, bar_size, duration):
    q = urllib.parse.urlencode({"duration": duration, "bar_size": bar_size, "prefer_ib": "true"})
    url = f"{BASE}/api/ib/historical/{urllib.parse.quote(symbol)}?{q}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, str(e)


def _upsert_bars(coll, symbol, bar_size, bars):
    stored = 0
    for bar in bars:
        if not isinstance(bar, dict):
            continue  # some symbols (e.g. VIX index) can return non-dict rows
        d = bar.get("date") or bar.get("time")
        if not d:
            continue
        coll.update_one(
            {"symbol": symbol, "bar_size": bar_size, "date": d},
            {"$set": {
                "open": bar.get("open"), "high": bar.get("high"),
                "low": bar.get("low"), "close": bar.get("close"),
                "volume": bar.get("volume"),
                "source": "ib",
                "collected_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        stored += 1
    return stored


def _do(coll, symbol, bar_size, duration):
    print(f"  → {symbol:<5} {bar_size:<7} ({duration}) …", end=" ", flush=True)
    resp, err = _http_fetch(symbol, bar_size, duration)
    if err:
        print(f"✗ {err} (IB busy? re-run later)")
        return 0
    bars = resp.get("bars") or []
    if not bars:
        print(f"✗ no bars (source={resp.get('source')})")
        return 0
    n = _upsert_bars(coll, symbol, bar_size, bars)
    print(f"✓ {n} bars (source={resp.get('source')})")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intraday", action="store_true",
                    help="also backfill 1h/5m/1m for SPY/QQQ/IWM (multi-TF prep)")
    args = ap.parse_args()

    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    coll = db["ib_historical_data"]

    print(f"=== Targeted Regime-Universe Backfill (IB-DIRECT via {BASE}) ===")
    plan = [(s, bs, dur) for s in DAILY_UNIVERSE for bs, dur in DAILY_PLAN.items()]
    if args.intraday:
        plan += [(s, bs, dur) for s in INDEX_TRIO for bs, dur in INTRADAY_PLAN.items()]
    print(f"Plan: {len(plan)} fetches across {len(set(p[0] for p in plan))} symbols\n")

    total = sum(_do(coll, s, bs, dur) for s, bs, dur in plan)

    print("\n=== Verification (latest daily bar per symbol) ===")
    for sym in DAILY_UNIVERSE:
        rows = list(coll.find({"symbol": sym, "bar_size": "1 day"},
                              {"_id": 0, "date": 1, "close": 1}).sort("date", -1).limit(2))
        if len(rows) >= 2 and rows[1].get("close"):
            chg = (rows[0]["close"] - rows[1]["close"]) / rows[1]["close"] * 100
            n = coll.count_documents({"symbol": sym, "bar_size": "1 day"})
            print(f"  {sym:<5} {n:>4} daily bars | latest {str(rows[0]['date'])[:10]} "
                  f"close={rows[0]['close']} chg={chg:+.2f}%")
        else:
            print(f"  {sym:<5} ⚠ insufficient daily bars ({len(rows)})")

    if args.intraday:
        print("\n=== Intraday lane coverage (index trio) ===")
        for sym in INDEX_TRIO:
            for bs in INTRADAY_PLAN:
                n = coll.count_documents({"symbol": sym, "bar_size": bs})
                print(f"  {sym:<5} {bs:<7}: {n} bars")

    print(f"\nDone. Stored {total} bars. Force a regime refresh:\n"
          f'  curl -s "localhost:8001/api/market-regime/current?force_refresh=true" '
          f"| python3 -c \"import sys,json;print(json.dumps(json.load(sys.stdin).get('multi_tf'),indent=2))\"")


if __name__ == "__main__":
    main()
