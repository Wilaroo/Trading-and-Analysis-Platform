#!/usr/bin/env python3
"""
v19.34.163 Step 2 — Bracket Churn Audit (read-only)
====================================================

Scans `bracket_lifecycle_events` to identify trades suffering from repeated
`naked_sweep_reissue` cycles — the suspected root cause of >75% of trades
never having a Take Profit target placed (v90 P0 bug).

For each offending trade, classifies the *trigger* of each reissue by
looking at the lifecycle phase immediately preceding it. The global
trigger distribution tells us what to actually fix in v19.34.163 Step 1:

    oca_conflict        → tighten OCA-group dedup
    reconciler_collision → position_reconciler is yanking live brackets
    self_cascade        → sweep itself is re-triggering on its own output
    cancel_failed       → IB cancel ack timeout cascade
    throttle_then_retry → throttle window not preventing rapid-fire
    unknown             → need to widen classifier

Read-only. Never writes. Safe to run during market hours.

Usage
-----
    cd ~/Trading-and-Analysis-Platform
    source .venv/bin/activate
    PYTHONPATH=backend python backend/scripts/bracket_churn_audit_v19_34_163.py --days 7
    PYTHONPATH=backend python backend/scripts/bracket_churn_audit_v19_34_163.py --days 1 --verbose
    PYTHONPATH=backend python backend/scripts/bracket_churn_audit_v19_34_163.py --sample-schema
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from pymongo import MongoClient

# ─── Load backend/.env ──────────────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
load_dotenv(os.path.join(_BACKEND_DIR, ".env"))

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")

# Confirmed phase taxonomy from grep of backend/services/ (v19.34.x):
SWEEP_REISSUE_PHASE = "naked_sweep_reissue"

# Map preceding phase → suspected trigger category. Order matters: first
# match wins. Phases not listed fall through to "unknown".
TRIGGER_RULES = [
    # (phase_substr, reason_substr_or_None, category)
    ("naked_sweep_reissue", None,                "self_cascade"),
    ("spawn_excess_slice",  None,                "reconciler_collision"),
    ("cancel",              None,                "cancel_path"),
    ("throttle",            None,                "throttle_then_retry"),
    ("compute",             None,                "compute_recompute"),
    ("submit",              None,                "submit_failed"),
    ("scale_out",           None,                "scale_out_followup"),
    ("eod_flatten",         None,                "eod_window"),
    ("close",               None,                "close_path"),
    ("done",                None,                "post_completion"),
]


def classify_trigger(prev_phase: str | None, prev_reason: str | None) -> str:
    if not prev_phase:
        return "no_prior_event"
    p = prev_phase.lower()
    r = (prev_reason or "").lower()
    for phase_sub, reason_sub, cat in TRIGGER_RULES:
        if phase_sub in p and (reason_sub is None or reason_sub in r):
            return cat
    return "unknown"


def fmt_dt(d) -> str:
    if not d:
        return "?"
    if isinstance(d, str):
        return d[:16]
    return d.strftime("%m-%d %H:%M")


def main() -> int:
    ap = argparse.ArgumentParser(description="Bracket Churn Audit (read-only)")
    ap.add_argument("--days", type=int, default=7, help="Lookback window in days (default 7)")
    ap.add_argument("--min-reissues", type=int, default=2,
                    help="Only report trades with ≥N naked_sweep_reissue events (default 2)")
    ap.add_argument("--top", type=int, default=25, help="Top N offenders to show (default 25)")
    ap.add_argument("--verbose", action="store_true",
                    help="Print full per-trade timeline for top 5 offenders")
    ap.add_argument("--sample-schema", action="store_true",
                    help="Print one sample document + distinct phases, then exit")
    args = ap.parse_args()

    if not MONGO_URL or not DB_NAME:
        print("[FATAL] MONGO_URL / DB_NAME missing from backend/.env", file=sys.stderr)
        return 2

    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    coll = db["bracket_lifecycle_events"]

    total_docs = coll.estimated_document_count()
    if total_docs == 0:
        print("[INFO] bracket_lifecycle_events is empty — nothing to audit.")
        return 0

    # ─── Schema inspection mode ─────────────────────────────────────────────
    if args.sample_schema:
        sample = coll.find_one(sort=[("created_at", -1)])
        if sample:
            sample.pop("_id", None)
            for k, v in list(sample.items()):
                if isinstance(v, datetime):
                    sample[k] = v.isoformat()
            print("[SCHEMA SAMPLE — most recent event]")
            print(json.dumps(sample, indent=2, default=str))
        phases = sorted(p for p in coll.distinct("phase") if p)
        print(f"\n[DISTINCT phase values] ({len(phases)} total)")
        for p in phases:
            n = coll.count_documents({"phase": p})
            print(f"  {p:<32} n={n}")
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)

    # ─── Pass 1: identify churning trade_ids ────────────────────────────────
    pipeline = [
        {"$match": {
            "phase": SWEEP_REISSUE_PHASE,
            "created_at": {"$gte": cutoff},
        }},
        {"$group": {
            "_id": "$trade_id",
            "reissue_count": {"$sum": 1},
            "symbols":   {"$addToSet": "$symbol"},
            "first_seen": {"$min": "$created_at"},
            "last_seen":  {"$max": "$created_at"},
            "fail_count": {"$sum": {"$cond": [{"$eq": ["$success", False]}, 1, 0]}},
        }},
        {"$match": {"reissue_count": {"$gte": args.min_reissues}}},
        {"$sort": {"reissue_count": -1}},
        {"$limit": args.top},
    ]
    offenders = list(coll.aggregate(pipeline))

    total_reissues_window = coll.count_documents({
        "phase": SWEEP_REISSUE_PHASE,
        "created_at": {"$gte": cutoff},
    })

    print(f"\n{'=' * 78}")
    print(f"  BRACKET CHURN AUDIT  —  v19.34.163 Step 2")
    print(f"  Window:           last {args.days}d  (cutoff {cutoff.isoformat()})")
    print(f"  Collection size:  {total_docs:,} total events")
    print(f"  Sweep reissues:   {total_reissues_window:,} in window")
    print(f"  Threshold:        ≥{args.min_reissues} reissues per trade")
    print(f"  Offending trades: {len(offenders)}")
    print(f"{'=' * 78}\n")

    if not offenders:
        print(f"[OK] No trades with ≥{args.min_reissues} naked_sweep_reissue events.")
        return 0

    # ─── Pass 2: fetch full timeline per offender, classify triggers ────────
    trade_ids = [o["_id"] for o in offenders if o["_id"]]
    timelines: dict[str, list[dict]] = defaultdict(list)
    cursor = coll.find(
        {"trade_id": {"$in": trade_ids}, "created_at": {"$gte": cutoff}},
        {"_id": 0, "trade_id": 1, "symbol": 1, "phase": 1,
         "reason": 1, "success": 1, "error": 1, "created_at": 1,
         "remaining_shares": 1, "oca_group": 1},
    ).sort("created_at", 1)
    for ev in cursor:
        timelines[ev["trade_id"]].append(ev)

    global_trigger = Counter()
    per_trade_trigger: dict[str, Counter] = {}
    for tid, events in timelines.items():
        tc = Counter()
        for i, ev in enumerate(events):
            if ev.get("phase") == SWEEP_REISSUE_PHASE:
                prev = events[i - 1] if i > 0 else None
                cat = classify_trigger(
                    prev.get("phase") if prev else None,
                    prev.get("reason") if prev else None,
                )
                tc[cat] += 1
                global_trigger[cat] += 1
        per_trade_trigger[tid] = tc

    # ─── Top offenders table ────────────────────────────────────────────────
    print("[TOP CHURN OFFENDERS]")
    print(f"  {'#':>3} {'reissues':>8} {'fails':>5} {'symbol':<10} "
          f"{'trade_id':<40} {'window':<26} top_trigger")
    print(f"  {'-' * 3} {'-' * 8} {'-' * 5} {'-' * 10} {'-' * 40} "
          f"{'-' * 26} {'-' * 24}")
    for i, o in enumerate(offenders, 1):
        syms = ",".join(s for s in (o.get("symbols") or []) if s)[:10] or "?"
        tid = str(o["_id"]) if o["_id"] else "<null>"
        tid_disp = tid[:38] + ".." if len(tid) > 40 else tid
        window = f"{fmt_dt(o.get('first_seen'))} → {fmt_dt(o.get('last_seen'))}"
        tt = per_trade_trigger.get(o["_id"], Counter())
        top_trigger = f"{tt.most_common(1)[0][0]} ({tt.most_common(1)[0][1]})" if tt else "-"
        print(f"  {i:>3} {o['reissue_count']:>8} {o.get('fail_count', 0):>5} "
              f"{syms:<10} {tid_disp:<40} {window:<26} {top_trigger}")

    # ─── Global trigger distribution ────────────────────────────────────────
    print(f"\n[GLOBAL TRIGGER DISTRIBUTION]  "
          f"(phase immediately preceding each naked_sweep_reissue)")
    total = sum(global_trigger.values()) or 1
    width = max((len(c) for c in global_trigger), default=0) + 2
    for cat, n in global_trigger.most_common():
        pct = 100.0 * n / total
        bar = "█" * int(pct / 2)
        print(f"  {cat:<{width}} {n:>5}  ({pct:5.1f}%)  {bar}")

    # ─── Verbose per-trade timeline ─────────────────────────────────────────
    if args.verbose:
        print(f"\n[VERBOSE TIMELINES — top 5 offenders]")
        for o in offenders[:5]:
            tid = o["_id"]
            print(f"\n  ━━ trade_id={tid}  symbol={','.join(o.get('symbols') or [])} "
                  f" reissues={o['reissue_count']} fails={o.get('fail_count', 0)}")
            print(f"     triggers={dict(per_trade_trigger.get(tid, {}))}")
            for ev in timelines.get(tid, []):
                ts = ev["created_at"].strftime("%m-%d %H:%M:%S") if ev.get("created_at") else "?"
                ok = "✓" if ev.get("success") else ("✗" if ev.get("success") is False else "·")
                marker = "  ★" if ev.get("phase") == SWEEP_REISSUE_PHASE else "   "
                err = f"  err={ev.get('error')!s:.50}" if ev.get("error") else ""
                rs = f"  rs={ev.get('remaining_shares')}" if ev.get("remaining_shares") is not None else ""
                print(f"    {marker} {ts}  {ok}  {ev.get('phase', '?'):<22} "
                      f"reason={ev.get('reason') or '-'}{rs}{err}")

    # ─── Headline summary ───────────────────────────────────────────────────
    top_cat, top_n = global_trigger.most_common(1)[0] if global_trigger else (None, 0)
    if top_cat:
        print(f"\n[HEADLINE]  Top trigger = '{top_cat}'  "
              f"({top_n}/{total} = {100.0 * top_n / total:.1f}% of reissues)")
        print(f"            → v19.34.163 Step 1 should focus the cumulative-fields")
        print(f"              + protection logic on this category first.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
