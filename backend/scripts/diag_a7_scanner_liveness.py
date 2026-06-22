#!/usr/bin/env python3
"""A7 READ-ONLY scanner-liveness audit — "is the scanner producing NEW alerts, or
just showing hydrated positions/carry-forwards?" Pinpoints WHEN new-alert flow
stopped and whether it's intraday vs daily. WRITES NOTHING.

Usage (DGX, repo root):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_a7_scanner_liveness.py
"""
import os
from datetime import datetime, timezone, timedelta
from collections import Counter

for _l in open("backend/.env"):
    if "=" in _l and not _l.startswith("#"):
        k, v = _l.strip().split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from pymongo import MongoClient

db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
now = datetime.now(timezone.utc)
iso = lambda m: (now - timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%S")

print(f"== A7 scanner-liveness · now={now.strftime('%Y-%m-%dT%H:%M:%S')}Z ==\n")

print("live_alerts CREATED freshness (is the scanner emitting NEW alerts?):")
for m in (5, 15, 30, 60, 120, 240, 1440):
    n = db.live_alerts.count_documents({"created_at": {"$gte": iso(m)}})
    print(f"  last {m:>5}m: {n}")
print()

print("newest 12 live_alerts:")
for a in db.live_alerts.find(
        {}, {"_id": 0, "created_at": 1, "symbol": 1, "setup_type": 1,
             "priority": 1, "trade_style": 1, "time_window": 1, "scan_tier": 1}
        ).sort("created_at", -1).limit(12):
    print(f"  {str(a.get('created_at'))[:19]}  {a.get('symbol',''):6} "
          f"{a.get('setup_type',''):26} pri={a.get('priority','')} "
          f"style={a.get('trade_style','')} win={a.get('time_window','')} tier={a.get('scan_tier','')}")
print()

# hourly histogram today (UTC) — when did emission stop?
today = now.strftime("%Y-%m-%d")
hours = Counter()
styles_recent = Counter()
for a in db.live_alerts.find(
        {"created_at": {"$gte": today}},
        {"_id": 0, "created_at": 1, "trade_style": 1}):
    ca = str(a.get("created_at") or "")
    if len(ca) >= 13:
        hours[ca[11:13]] += 1
print(f"alerts created TODAY ({today} UTC) by hour:")
for h in sorted(hours):
    print(f"  {h}:00Z  {hours[h]:>5}  {'#'*min(60,hours[h])}")
print(f"  total today: {sum(hours.values())}")
print()

print("trade_style of alerts created in last 240m (intraday vs daily/swing):")
for a in db.live_alerts.find({"created_at": {"$gte": iso(240)}}, {"_id": 0, "trade_style": 1}):
    styles_recent[a.get("trade_style") or "?"] += 1
print("  " + (" · ".join(f"{k}={v}" for k, v in styles_recent.most_common()) or "(none)"))
print()

# bot reasoning stream liveness (the "no bot thoughts in 60m" symptom)
for coll in ("sentcom_thoughts", "scanner_thoughts", "ai_thoughts"):
    try:
        if coll not in db.list_collection_names():
            continue
        tot = db[coll].count_documents({})
        last60 = db[coll].count_documents({"created_at": {"$gte": iso(60)}})
        newest = list(db[coll].find({}, {"_id": 0, "created_at": 1, "kind": 1, "symbol": 1, "content": 1}).sort("created_at", -1).limit(3))
        print(f"{coll}: total={tot} last60m={last60}")
        for r in newest:
            print(f"   {str(r.get('created_at'))[:19]} {r.get('kind','')} {r.get('symbol','')} {str(r.get('content',''))[:70]}")
    except Exception as e:
        print(f"{coll}: err {e}")
