#!/usr/bin/env python3
"""
diag_fundamental_sources.py — READ-ONLY probe of every candidate feed for the
TQS *fundamental* pillar, so the wiring patches (R0-R4) are written against
REAL data shapes instead of guesses.

The pillar needs, per symbol:
  • catalyst / recent news + sentiment      (30%)
  • short_interest_percent                  (20%)
  • float_shares                            (20%)
  • institutional_ownership_percent         (15%)
  • days_to_earnings / earnings_score       (15%)

This probes, for a handful of OPEN-BOOK symbols:
  1. finra_short_interest / ib_short_data   → short interest (shares) + fields
  2. Finnhub /stock/profile2                → shareOutstanding / float (FREE?)
  3. Finnhub /stock/metric (share fields)   → any float/SI exposed
  4. news_service.get_ticker_news           → count + does it carry sentiment?
  5. earnings_service.get_earnings_calendar → FREE earnings calendar shape

100% read-only. Makes a few live Finnhub/IB read calls (no writes, no restart).

Run (DGX, from repo root):
    cd ~/Trading-and-Analysis-Platform
    .venv/bin/python backend/scripts/diag_fundamental_sources.py
"""
import asyncio
import json
import os
import sys

# --- make `services.*` importable + load backend env --------------------------
for _cand in (
    os.path.join(os.getcwd(), "backend"),
    os.path.expanduser("~/Trading-and-Analysis-Platform/backend"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."),
):
    _cand = os.path.abspath(_cand)
    if os.path.isdir(_cand) and _cand not in sys.path:
        sys.path.insert(0, _cand)

try:
    from dotenv import load_dotenv
    for _envp in ("backend/.env",
                  os.path.expanduser("~/Trading-and-Analysis-Platform/backend/.env")):
        if os.path.exists(_envp):
            load_dotenv(_envp)
            break
except Exception:
    pass

import requests  # noqa: E402
from pymongo import MongoClient  # noqa: E402

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "tradecommand")
FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY")


def _open_book(db):
    syms = sorted({d.get("symbol") for d in db["bot_trades"].find(
        {"status": {"$in": ["pending", "open", "partial"]}}, {"symbol": 1})
        if d.get("symbol")})
    return syms[:5] or ["AMD", "AVGO", "ALAB"]


def _short_collections(db, syms):
    print("\n══ 1. SHORT INTEREST feeds (finra_short_interest / ib_short_data) ══")
    for coll in ("finra_short_interest", "ib_short_data"):
        n = db[coll].count_documents({})
        print(f"  {coll:<22} docs={n}")
        if n:
            sample = db[coll].find_one({}, {"_id": 0})
            print(f"    sample fields: {sorted(sample.keys())}")
            print(f"    sample: {json.dumps(sample, default=str)[:400]}")
    # per open-book coverage
    have = db["finra_short_interest"].count_documents({"symbol": {"$in": syms}})
    print(f"  open-book FINRA coverage: {have}/{len(syms)}  {syms}")


def _finnhub_profile2(syms):
    print("\n══ 2. Finnhub /stock/profile2 (float / shareOutstanding — FREE?) ══")
    if not FINNHUB_KEY:
        print("  🔴 No FINNHUB_API_KEY in env — skipping")
        return
    sym = syms[0]
    try:
        r = requests.get("https://finnhub.io/api/v1/stock/profile2",
                         params={"symbol": sym, "token": FINNHUB_KEY}, timeout=15)
        print(f"  {sym}: HTTP {r.status_code}")
        if r.status_code == 200:
            d = r.json() or {}
            print(f"    keys: {sorted(d.keys())}")
            print(f"    shareOutstanding={d.get('shareOutstanding')}  "
                  f"(millions; float≈shares for liquid names)")
        else:
            print(f"    body: {r.text[:200]}")
    except Exception as e:
        print(f"    error: {e}")


def _finnhub_metric_share_fields(syms):
    print("\n══ 3. Finnhub /stock/metric — any share/float/SI fields exposed? ══")
    if not FINNHUB_KEY:
        print("  🔴 No FINNHUB_API_KEY — skipping")
        return
    sym = syms[0]
    try:
        r = requests.get("https://finnhub.io/api/v1/stock/metric",
                         params={"symbol": sym, "metric": "all",
                                 "token": FINNHUB_KEY}, timeout=15)
        if r.status_code == 200:
            m = (r.json() or {}).get("metric", {}) or {}
            hits = {k: v for k, v in m.items()
                    if any(t in k.lower() for t in
                           ("share", "float", "short"))}
            print(f"  {sym}: share/float/short-ish metric fields:")
            print(f"    {json.dumps(hits, default=str)[:500] or '(none)'}")
        else:
            print(f"  {sym}: HTTP {r.status_code} {r.text[:150]}")
    except Exception as e:
        print(f"    error: {e}")


async def _news(syms):
    print("\n══ 4. news_service.get_ticker_news (catalyst feed) ══")
    try:
        from services.news_service import get_news_service
        svc = get_news_service()
        sym = syms[0]
        items = await asyncio.wait_for(svc.get_ticker_news(sym, max_items=5),
                                       timeout=20)
        print(f"  {sym}: {len(items)} items")
        if items:
            print(f"    item keys: {sorted(items[0].keys())}")
            print(f"    has 'sentiment'? "
                  f"{'sentiment' in items[0] or 'sentiment_score' in items[0]}")
            print(f"    sample: {json.dumps(items[0], default=str)[:400]}")
    except Exception as e:
        print(f"  error: {e}")


async def _earnings(syms):
    print("\n══ 5. earnings_service.get_earnings_calendar (FREE Finnhub) ══")
    try:
        from services.earnings_service import get_earnings_service
        svc = get_earnings_service()
        sym = syms[0]
        cal = await asyncio.wait_for(svc.get_earnings_calendar(sym), timeout=20)
        print(f"  {sym}: keys={sorted((cal or {}).keys())}")
        print(f"    sample: {json.dumps(cal, default=str)[:500]}")
    except Exception as e:
        print(f"  error: {e}")


async def main():
    db = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)[DB_NAME]
    syms = _open_book(db)
    print(f"Probing open-book symbols: {syms}")
    print(f"FINNHUB_API_KEY present: {bool(FINNHUB_KEY)}")

    _short_collections(db, syms)
    _finnhub_profile2(syms)
    _finnhub_metric_share_fields(syms)
    await _news(syms)
    await _earnings(syms)

    print("\n══ READ ══")
    print("  This tells us which feeds are ALIVE and their exact field shapes,")
    print("  so R0-R4 wiring maps the right keys. Empty short collections → the")
    print("  operator runs the FINRA fetch first; missing shareOutstanding →")
    print("  float must come from IB instead of Finnhub free.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
