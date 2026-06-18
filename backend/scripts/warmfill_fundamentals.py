#!/usr/bin/env python3
"""v384 F1 warm-fill — populate symbol_fundamentals_cache for the EVALUATED universe.
SELF-CONTAINED + FREE: Finnhub profile2 (float/market-cap, keyed) + local finra_short_interest
(short shares + days_to_cover) -> compute SI% -> upsert. No IB socket needed. Idempotent.
Run on DGX (off-hours ok):
  PYTHONPATH=backend .venv/bin/python backend/scripts/warmfill_fundamentals.py --days 5 [--throttle 1.1] [--limit 0]
Then re-run diag_v383 to confirm float / short_interest_percent / days_to_cover coverage jumps."""
import os, sys, time
from datetime import datetime, timezone, timedelta

for _l in open("backend/.env"):
    if "=" in _l and not _l.startswith("#"):
        k, v = _l.strip().split("=", 1); os.environ.setdefault(k.strip(), v.strip())
import httpx
from pymongo import MongoClient

a = sys.argv
def arg(f, d, c=str):
    return c(a[a.index(f) + 1]) if f in a else d
days = arg("--days", 5, float); throttle = arg("--throttle", 1.1, float); limit = arg("--limit", 0, int)
KEY = os.environ.get("FINNHUB_API_KEY")
assert KEY, "FINNHUB_API_KEY not set"
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
uni = sorted(db.live_alerts.distinct("symbol", {"created_at": {"$gte": since}, "tqs_score": {"$gt": 0}}))
if limit: uni = uni[:limit]
print(f"warm-fill: {len(uni)} symbols (last {days}d), throttle {throttle}s -> ~{len(uni)*throttle/60:.0f} min")

fin = {d["symbol"]: d for d in db.finra_short_interest.find(
    {"symbol": {"$in": uni}}, {"_id": 0, "symbol": 1, "short_interest": 1, "days_to_cover": 1})}
ok = float_n = si_n = dtc_n = 0
for i, sym in enumerate(uni):
    merged = {}
    try:
        r = httpx.get("https://finnhub.io/api/v1/stock/profile2",
                      params={"symbol": sym, "token": KEY}, timeout=15).json()
        so = r.get("shareOutstanding")  # millions
        if so and float(so) > 0:
            merged["float_shares"] = float(so) * 1_000_000
            merged["market_cap"] = r.get("marketCapitalization")
            float_n += 1
    except Exception as e:
        print(f"  {sym}: finnhub err {e}")
    f = fin.get(sym)
    if f:
        if f.get("days_to_cover"): merged["days_to_cover"] = f["days_to_cover"]; dtc_n += 1
        si_sh = f.get("short_interest")
        if si_sh: merged["short_interest_shares"] = si_sh
        if si_sh and merged.get("float_shares"):
            merged["short_interest_percent"] = round(100.0 * si_sh / merged["float_shares"], 2); si_n += 1
    if merged:
        now = datetime.now(timezone.utc)
        merged.update({"symbol": sym, "fetched_at": now, "expires_at": now + timedelta(hours=48),
                       "source": "warmfill_finnhub+finra"})
        db.symbol_fundamentals_cache.update_one({"symbol": sym}, {"$set": merged}, upsert=True); ok += 1
    if (i + 1) % 50 == 0:
        print(f"  {i+1}/{len(uni)}  float={float_n} si%={si_n} dtc={dtc_n}")
    time.sleep(throttle)
print(f"\nDONE: upserted {ok}/{len(uni)}  float={float_n} short_interest%={si_n} days_to_cover={dtc_n}")
print("Re-run: PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v383_fundamental_coverage.py --days 5")
