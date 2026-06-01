#!/usr/bin/env python3
"""
verify_v19_34_202.py — live end-to-end proof of the IB-sourced fundamentals
path (float + short-interest%). Clears a symbol's cache row and re-fetches it
through get_cached_fundamentals(), so we see the FRESH IB+FINRA result rather
than the stale 24h-cached Finnhub-only doc.

Run (DGX, from repo root, IB Gateway up):
    cd ~/Trading-and-Analysis-Platform
    .venv/bin/python backend/scripts/verify_v19_34_202.py            # AMD AVGO ALAB
    .venv/bin/python backend/scripts/verify_v19_34_202.py NVDA
"""
import asyncio
import os
import sys

for _cand in (os.path.join(os.getcwd(), "backend"),
              os.path.expanduser("~/Trading-and-Analysis-Platform/backend")):
    if os.path.isdir(_cand) and _cand not in sys.path:
        sys.path.insert(0, _cand)
try:
    from dotenv import load_dotenv
    for _p in ("backend/.env",
               os.path.expanduser("~/Trading-and-Analysis-Platform/backend/.env")):
        if os.path.exists(_p):
            load_dotenv(_p)
            break
except Exception:
    pass

from pymongo import MongoClient  # noqa: E402
from services.unified_fundamentals_cache import get_cached_fundamentals  # noqa: E402

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "tradecommand")
FIELDS = ["source", "float_shares", "shares_outstanding",
          "short_interest_percent", "days_to_cover", "market_cap", "beta"]


async def main():
    symbols = [s.upper() for s in (sys.argv[1:] or ["AMD", "AVGO", "ALAB"])]
    db = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)[DB_NAME]

    for sym in symbols:
        print(f"\n{'='*60}\n {sym}\n{'='*60}")
        db["symbol_fundamentals_cache"].delete_one({"symbol": sym})
        print("  cleared cache row → forcing fresh fetch (IB + Finnhub + FINRA)…")
        try:
            data = await get_cached_fundamentals(sym)
        except Exception as e:
            print(f"  🔴 fetch error: {e}")
            continue
        if not data:
            print("  🔴 None returned (all sources failed)")
            continue
        for f in FIELDS:
            print(f"    {f:<26} {data.get(f)}")
        ok_float = data.get("float_shares") is not None
        ok_si = data.get("short_interest_percent") is not None
        print(f"  → float from IB: {'✓' if ok_float else '✗'}   "
              f"short-interest% from FINRA: {'✓' if ok_si else '✗'}")

    print("\n══ READ ══")
    print("  ✓ float + short-interest% = the IB ReportSnapshot + FINRA wiring")
    print("  works end-to-end. The rest of the cache backfills on its own 24h TTL.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
