#!/usr/bin/env python3
"""
verify_v19_34_202.py — live end-to-end proof of the IB-sourced fundamentals
path (float + short-interest%).

IMPORTANT: the IB ReportSnapshot fetch only works INSIDE the backend process
(that's where the live clientId-11 ib_direct socket lives). A standalone script
has no IB connection, so we trigger the fetch via the backend's own TQS endpoint
(`/api/tqs/breakdown/{symbol}` → fundamental pillar → get_cached_fundamentals →
ib_direct), then read the freshly-written cache doc back from Mongo.

Run (DGX, from repo root, IB Gateway up + backend running):
    cd ~/Trading-and-Analysis-Platform
    .venv/bin/python backend/scripts/verify_v19_34_202.py            # AMD AVGO ALAB
"""
import os
import sys
import time

try:
    from dotenv import load_dotenv
    for _p in ("backend/.env",
               os.path.expanduser("~/Trading-and-Analysis-Platform/backend/.env")):
        if os.path.exists(_p):
            load_dotenv(_p)
            break
except Exception:
    pass

import requests  # noqa: E402
from pymongo import MongoClient  # noqa: E402

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "tradecommand")
BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8001")
FIELDS = ["source", "float_shares", "shares_outstanding",
          "short_interest_percent", "days_to_cover", "market_cap", "beta"]


def main():
    symbols = [s.upper() for s in (sys.argv[1:] or ["AMD", "AVGO", "ALAB"])]
    db = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)[DB_NAME]
    col = db["symbol_fundamentals_cache"]

    for sym in symbols:
        print(f"\n{'='*60}\n {sym}\n{'='*60}")
        col.delete_one({"symbol": sym})
        print("  cleared cache row → triggering in-backend TQS fetch…")
        try:
            r = requests.get(f"{BACKEND}/api/tqs/breakdown/{sym}",
                             params={"direction": "long"}, timeout=90)
            print(f"  /api/tqs/breakdown/{sym} → HTTP {r.status_code}")
        except Exception as e:
            print(f"  🔴 endpoint call failed: {e}  (is the backend up?)")
            continue

        # the cache write happens synchronously inside the request; re-read it
        doc = None
        for _ in range(6):
            doc = col.find_one({"symbol": sym}, {"_id": 0})
            if doc:
                break
            time.sleep(0.5)
        if not doc:
            print("  🔴 no cache doc written (fetch returned nothing)")
            continue
        for f in FIELDS:
            print(f"    {f:<26} {doc.get(f)}")
        ok_float = doc.get("float_shares") is not None
        ok_si = doc.get("short_interest_percent") is not None
        src = str(doc.get("source", ""))
        print(f"  → IB float: {'✓' if ok_float else '✗'}   "
              f"FINRA short%: {'✓' if ok_si else '✗'}   "
              f"ib_direct in source: {'✓' if 'ib_direct' in src else '✗'}")

    print("\n══ READ ══")
    print("  float_shares + short_interest_percent populated and 'ib_direct' in")
    print("  source = the IB ReportSnapshot + FINRA wiring works end-to-end.")
    print("  The rest of the cache backfills on its own 24h TTL.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
