#!/usr/bin/env python3
"""
v19.34.163 — Shadow Decisions Field Sanity Check
=================================================

Examines the actual field-value distribution in `shadow_decisions` to
explain why Pipeline Funnel reports 100% pass-through at every stage.

Three possible root causes:
  (A) Bot really does pass everything (unlikely at 100%)
  (B) Fields are missing/null on docs → $in clauses behave weirdly
  (C) Field NAMES changed and the legacy query is hitting wrong path

This script enumerates real value distributions so we know which.
"""
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from pymongo import MongoClient

_SD = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(os.path.dirname(_SD), ".env"))

db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
col = db["shadow_decisions"]

print("=" * 78)
print("  SHADOW_DECISIONS FIELD AUDIT")
print(f"  Total docs: {col.count_documents({})}")
print("=" * 78)

# Sample fresh doc to see actual schema
sample = col.find_one(sort=[("trigger_time", -1)]) or col.find_one()
if sample:
    sample.pop("_id", None)
    print(f"\n[ SAMPLE — most recent doc ]")
    for k in sorted(sample.keys())[:50]:
        v = sample[k]
        vt = type(v).__name__
        vp = str(v)[:60]
        print(f"  {k:<35} {vt:<12} {vp}")

# Last-30d window check using different timestamp fields
cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
print(f"\n[ LAST 30d WINDOW COUNTS ]  cutoff_iso={cutoff_iso}")
for ts_field in ("trigger_time", "timestamp", "created_at", "decision_time"):
    n = col.count_documents({ts_field: {"$gte": cutoff_iso}})
    print(f"  {ts_field:<20}  count_30d={n:>6}")

# Value distributions on key filter fields
print(f"\n[ FIELD VALUE DISTRIBUTIONS — last 30d via trigger_time ]")
fields = [
    "combined_recommendation",
    "risk_assessment.recommendation",
    "was_executed",
    "decision",
    "outcome",
    "verdict",
]
window = {"trigger_time": {"$gte": cutoff_iso}}
for fld in fields:
    print(f"\n  {fld}:")
    try:
        # Aggregate distinct value counts
        if "." in fld:
            parent, child = fld.split(".", 1)
            pipeline = [
                {"$match": window},
                {"$group": {"_id": f"${parent}.{child}", "n": {"$sum": 1}}},
                {"$sort": {"n": -1}},
                {"$limit": 10},
            ]
        else:
            pipeline = [
                {"$match": window},
                {"$group": {"_id": f"${fld}", "n": {"$sum": 1}}},
                {"$sort": {"n": -1}},
                {"$limit": 10},
            ]
        for row in col.aggregate(pipeline):
            v = row["_id"]
            n = row["n"]
            print(f"    {str(v)[:40]:<42} n={n:>6}")
    except Exception as e:
        print(f"    ERROR: {e}")

# Module votes audit — find the actual field path used
print(f"\n[ MODULE VOTE FIELD PATHS in sample doc ]")
if sample:
    def walk(d, prefix=""):
        for k, v in (d.items() if isinstance(d, dict) else []):
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                yield from walk(v, path)
            elif isinstance(v, list) and v and isinstance(v[0], dict):
                yield (path, f"list[{len(v)}] of dict")
            elif any(t in k.lower() for t in ["vote", "module", "agent", "council"]):
                yield (path, repr(v)[:40])
    found = list(walk(sample))
    if found:
        for p, v in found:
            print(f"  {p:<55}  {v}")
    else:
        print(f"  (no fields containing vote/module/agent/council found)")

# Cross-check: institutional and timeseries had 0 votes per scorecard.
# If they exist under a different path, we want to find them.
print(f"\n[ INSTITUTIONAL / TIMESERIES MODULE PATHS — recent docs ]")
for mod in ("institutional", "timeseries"):
    found_paths = set()
    for doc in col.find(window).limit(20):
        for k in doc:
            if mod in k.lower():
                found_paths.add(k)
            if isinstance(doc.get(k), dict):
                for k2 in doc[k]:
                    if mod in k2.lower():
                        found_paths.add(f"{k}.{k2}")
    print(f"  {mod:<15}  paths_found={list(found_paths) or '<<none>>'}")

print("\n[ DONE ]")
