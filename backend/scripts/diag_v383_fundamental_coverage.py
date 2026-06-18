#!/usr/bin/env python3
"""v383 READ-ONLY fundamental-data COVERAGE audit (Path B / "are we capturing fundamentals?").
Joins the EVALUATED universe (distinct symbols in live_alerts) against every fundamentals
source and reports real-data coverage % on the symbols that actually matter. Changes nothing.
Usage: PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v383_fundamental_coverage.py --days 5"""
import os, sys
from datetime import datetime, timezone, timedelta

for _l in open("backend/.env"):
    if "=" in _l and not _l.startswith("#"):
        k, v = _l.strip().split("=", 1); os.environ.setdefault(k.strip(), v.strip())
from pymongo import MongoClient

a = sys.argv
days = float(a[a.index("--days") + 1]) if "--days" in a else 5
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
pct = lambda n, d: f"{100.0*n/d:.0f}%" if d else "n/a"
since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

uni = sorted(db.live_alerts.distinct("symbol", {"created_at": {"$gte": since}, "tqs_score": {"$gt": 0}}))
U = len(uni)
print(f"== Fundamental coverage on the EVALUATED universe: {U} distinct symbols (last {days}d) ==")
print(f"FINNHUB_API_KEY set: {bool(os.environ.get('FINNHUB_API_KEY'))}\n")

def cov(coll, field, q=None):
    base = {"symbol": {"$in": uni}}
    if q: base.update(q)
    have = db[coll].distinct("symbol", {**base, field: {"$ne": None, "$exists": True}})
    return len([s for s in have if s in set(uni)])

fc = "symbol_fundamentals_cache"
print(f"{fc}: {db[fc].count_documents({})} docs total")
for f in ("float_shares", "short_interest_percent", "days_to_cover", "institutional_ownership_percent"):
    c = cov(fc, f)
    print(f"  evaluated symbols with real {f:<32}: {c}/{U}  ({pct(c,U)})")

fin = "finra_short_interest"
nf = db[fin].count_documents({})
print(f"\n{fin}: {nf} docs")
if nf:
    dates = db[fin].distinct("settlement_date")
    latest = max(dates) if dates else "?"
    c = len([s for s in db[fin].distinct("symbol", {"settlement_date": latest}) if s in set(uni)])
    print(f"  latest settlement_date: {latest}; evaluated-universe coverage @latest: {c}/{U} ({pct(c,U)})")

ic = "institutional_ownership_cache"
ni = db[ic].count_documents({})
print(f"\n{ic}: {ni} docs")
if ni:
    c = cov(ic, "institutional_ownership_percent")
    last = list(db[ic].find({}, {"fetched_at": 1, "updated_at": 1}).sort("_id", -1).limit(1))
    ts = (last[0].get("fetched_at") or last[0].get("updated_at")) if last else "?"
    print(f"  most-recent fetched_at: {ts}; evaluated coverage: {c}/{U} ({pct(c,U)})")

# F2b scoping — earnings_calendar coverage (already-captured EPS/rev BEAT/MISS surprise)
ec = "earnings_calendar"
ne = db[ec].count_documents({})
print(f"\n{ec}: {ne} docs")
if ne:
    rep = len([s for s in db[ec].distinct("symbol", {"is_reported": True}) if s in set(uni)])
    surp = len([s for s in db[ec].distinct("symbol", {"eps_result": {"$in": ["BEAT", "MISS", "MET"]}}) if s in set(uni)])
    print(f"  evaluated symbols with a reported earnings row: {rep}/{U} ({pct(rep,U)})")
    print(f"  evaluated symbols with an EPS BEAT/MISS surprise: {surp}/{U} ({pct(surp,U)})")

print("\nREAD: any line <<50% means the Fundamental pillar is BLIND for most evaluated trades")
print("(forced to neutral-50). Fix = warm-fill that source across the universe, not de-weighting.")
