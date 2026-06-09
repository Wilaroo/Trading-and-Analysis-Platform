#!/usr/bin/env python3
"""
VIX History Backfill (IB-only, CBOE index via ib-direct)
========================================================
Pulls a long daily VIX (CBOE Market Volatility Index) series over the LIVE
ib-direct socket and stores it to ib_historical_data so the system can
percentile-rank current volatility against historical regimes (COVID 2020,
2018 volmageddon, tariff/rate spikes, geopolitical shocks, etc.).

Requires the v316b patch applied (adds ib_direct get_historical_data +
GET /api/system/ib-direct/historical/{symbol}) and the backend restarted.

Run:
    python3 scripts/backfill_vix_history.py                 # default 20 Y daily
    python3 scripts/backfill_vix_history.py --duration "10 Y"
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", default="20 Y", help='IB duration, e.g. "20 Y", "10 Y"')
    args = ap.parse_args()

    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    coll = db["ib_historical_data"]

    q = urllib.parse.urlencode({"duration": args.duration, "bar_size": "1 day",
                                "what_to_show": "TRADES", "use_rth": "true"})
    url = f"{BASE}/api/system/ib-direct/historical/VIX?{q}"
    print(f"=== VIX History Backfill (IB-direct, CBOE index) — {args.duration} daily ===")
    print(f"GET {url}\n")
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=120) as r:
            resp = json.loads(r.read().decode())
    except Exception as e:
        print(f"✗ request failed: {e}")
        return
    if not resp.get("success"):
        print(f"✗ {resp.get('error')}")
        return
    bars = resp.get("bars") or []
    if not bars:
        print("✗ 0 bars returned — check IB market-data subscription for CBOE indices ($VIX-X).")
        return

    stored = 0
    for b in bars:
        d = b.get("date")
        if not d:
            continue
        coll.update_one(
            {"symbol": "VIX", "bar_size": "1 day", "date": d},
            {"$set": {"open": b.get("open"), "high": b.get("high"), "low": b.get("low"),
                      "close": b.get("close"), "volume": b.get("volume"),
                      "source": "ib_direct",
                      "collected_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
        stored += 1

    closes = sorted(b["close"] for b in bars if b.get("close"))
    latest = bars[-1]
    n = len(closes)
    below = sum(1 for c in closes if c <= latest["close"])
    pct = below / n * 100 if n else 0
    print(f"✓ stored {stored} VIX daily bars (source=ib_direct)")
    print(f"  range: {str(bars[0]['date'])[:10]} → {str(bars[-1]['date'])[:10]}")
    print(f"  min={closes[0]:.2f}  max={closes[-1] if False else closes[n-1]:.2f}  "
          f"median={closes[n//2]:.2f}")
    print(f"  latest close={latest['close']:.2f}  →  ~{pct:.0f}th percentile of {n} sessions")
    print(f"  (>30 ≈ fear, >40 ≈ panic/capitulation, <15 ≈ complacency)")


if __name__ == "__main__":
    main()
