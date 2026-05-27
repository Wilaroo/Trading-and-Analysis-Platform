#!/usr/bin/env python3
"""
v19.34.163 — Diagnostics Tab Data Accuracy Audit
=================================================

Validates every backend collection the Diagnostics tab depends on:
  • Collection population (vs Diagnostics endpoint output)
  • Timestamp field TYPE (string ISO vs BSON datetime — common bug source)
  • Field name consistency
  • Date-range filter behavior

Read-only. Run any time. ~10 seconds.

Usage:
    cd ~/Trading-and-Analysis-Platform && source .venv/bin/activate
    PYTHONPATH=backend python backend/scripts/diagnostics_tab_audit.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from pymongo import MongoClient

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
load_dotenv(os.path.join(_BACKEND_DIR, ".env"))

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")


def fmt_type(val):
    if val is None:
        return "<<None>>"
    if isinstance(val, datetime):
        return f"datetime ({val.isoformat()})"
    if isinstance(val, str):
        return f"string ({val[:30]}...)" if len(val) > 30 else f"string ({val})"
    return f"{type(val).__name__} ({val!r})"


def check(label, ok, detail=""):
    icon = "✅" if ok else "❌"
    print(f"  {icon} {label:<55} {detail}")


def main():
    if not MONGO_URL or not DB_NAME:
        print("[FATAL] MONGO_URL / DB_NAME missing from backend/.env")
        return 2

    db = MongoClient(MONGO_URL)[DB_NAME]
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=30)
    cutoff_iso = cutoff_dt.isoformat()

    print("=" * 78)
    print(f"  DIAGNOSTICS TAB AUDIT  —  DB: {DB_NAME}")
    print(f"  Cutoff (30d): dt={cutoff_dt.isoformat()}")
    print(f"               iso='{cutoff_iso}'")
    print("=" * 78)

    # ─── Collections the diagnostics endpoints depend on ───────────────
    targets = [
        # (collection, timestamp_field, used_by_tab)
        ("bot_trades",                 "created_at",      "Trail Explorer, Trade Forensics"),
        ("shadow_decisions",           "timestamp",       "Trail Explorer, Module Scorecard, Funnel, Shadow"),
        ("scanner_alerts",             "timestamp",       "Funnel (emit count)"),
        ("sentcom_thoughts",           "created_at",      "Trail Explorer (drilldown)"),
        ("shadow_module_performance",  "updated_at",      "Module Scorecard"),
        ("shadow_module_weights",      None,              "Module Scorecard (weights map)"),
        ("alert_outcomes",             "closed_at",       "Trade Forensics, Day Tape"),
        ("rejection_events",           "ts",              "Rejections tab"),
        ("bracket_lifecycle_events",   "created_at",      "(supports churn audit)"),
    ]

    for col_name, ts_field, used_by in targets:
        print(f"\n[ {col_name} ]  used by: {used_by}")
        try:
            total = db[col_name].count_documents({})
            print(f"  total docs: {total}")
            if total == 0:
                print(f"  ⚠️  EMPTY — Diagnostics tab will show 0 for {used_by}")
                continue

            # Schema sample
            sample = db[col_name].find_one()
            sample_id = sample.get("_id") if sample else None
            print(f"  sample _id: {sample_id}")

            if ts_field is None:
                continue

            # Check the timestamp field type
            sample_ts = sample.get(ts_field) if sample else None
            print(f"  {ts_field} TYPE: {fmt_type(sample_ts)}")

            # Try BOTH datetime and string filters — whichever returns docs
            # is the "correct" filter type for this collection
            n_dt = db[col_name].count_documents({ts_field: {"$gte": cutoff_dt}})
            n_str = db[col_name].count_documents({ts_field: {"$gte": cutoff_iso}})
            print(f"  30d count via datetime filter: {n_dt:>6}")
            print(f"  30d count via ISO-string filter: {n_str:>6}")

            if n_dt > 0 and n_str == 0:
                print(f"  → CORRECT FILTER: datetime object (BSON Date)")
            elif n_str > 0 and n_dt == 0:
                print(f"  → CORRECT FILTER: ISO string")
            elif n_dt > 0 and n_str > 0:
                print(f"  → BOTH work (mixed types in collection — schema drift!)")
            else:
                print(f"  → NEITHER returns 30d docs (newest may be older or no ts indexed)")

            # Find newest doc to confirm latest timestamp
            newest = db[col_name].find_one(sort=[(ts_field, -1)])
            print(f"  newest {ts_field}: {fmt_type((newest or {}).get(ts_field))}")
        except Exception as e:
            print(f"  ❌ ERROR: {type(e).__name__}: {e}")

    # ─── Cross-validate Diagnostics endpoints against raw data ─────────
    print("\n" + "=" * 78)
    print("  CROSS-CHECK — what the Diagnostics endpoints would compute")
    print("=" * 78)

    # Funnel emit count = scanner_alerts in window (or shadow_decisions per
    # the latest comment in decision_trail.py)
    try:
        from services.decision_trail import build_pipeline_funnel
        funnel = build_pipeline_funnel(db, days=30)
        print("\n[ Pipeline Funnel (30d) ] — endpoint output:")
        for stage in funnel.get("stages", []):
            n = stage.get("count", 0)
            label = stage.get("label", stage.get("stage"))
            conv = stage.get("conversion_pct")
            conv_str = f"  conv={conv}%" if conv is not None else ""
            print(f"  {label:<20}  count={n:>6}{conv_str}")
    except Exception as e:
        print(f"  ❌ funnel build failed: {type(e).__name__}: {e}")

    try:
        from services.decision_trail import build_module_scorecard
        sc = build_module_scorecard(db, days=30)
        print(f"\n[ Module Scorecard (30d) ] — endpoint output:")
        print(f"  modules count: {len(sc.get('modules') or [])}")
        vb = sc.get("vote_breakdown") or {}
        for src, v in vb.items():
            tot = v.get("total_votes", 0)
            print(f"  {src:<20} total_votes={tot}")
    except Exception as e:
        print(f"  ❌ scorecard build failed: {type(e).__name__}: {e}")

    print("\n[ DONE ]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
