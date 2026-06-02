#!/usr/bin/env python3
"""
diag_tqs_pillar_breakdown.py  (READ-ONLY)

Reads the per-pillar TQS breakdown the scanner now persists on each alert
(`tqs_breakdown` -> {pillar: {score, grade, components, raw_values}}) and
proves, EMPIRICALLY, which pillars/sub-components are running on REAL data
vs the neutral DEFAULT sentinels.

This settles the question: "did yesterday's fixes make TQS compute real data?"

Usage on the DGX:
    python3 /tmp/diag_tqs_pillar_breakdown.py            # today (UTC)
    python3 /tmp/diag_tqs_pillar_breakdown.py --days 3

Read-only. Nothing is written.
"""

import os
import sys
import argparse
import statistics
from collections import Counter
from datetime import datetime, timezone, timedelta


def _load_env():
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    for c in ("/app/backend/.env", "./backend/.env", "backend/.env", ".env"):
        if (mongo_url and db_name) or not os.path.exists(c):
            continue
        with open(c) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k == "MONGO_URL" and not mongo_url:
                    mongo_url = v
                elif k == "DB_NAME" and not db_name:
                    db_name = v
    return mongo_url or "mongodb://localhost:27017", db_name or "tradecommand"


def _pct(n, total):
    return f"{(100.0*n/total):5.1f}%" if total else "  n/a"


def _stats(vals):
    vals = [v for v in vals if isinstance(v, (int, float))]
    if not vals:
        return "no numeric values"
    return (f"min={min(vals):.2f} max={max(vals):.2f} "
            f"mean={statistics.mean(vals):.2f} median={statistics.median(vals):.2f}")


def _default_rate(rows, pillar, field, sentinel, approx=True):
    """% of alerts where this raw_value equals the known DEFAULT sentinel."""
    present = 0
    hits = 0
    for r in rows:
        bd = (r.get("tqs_breakdown") or {}).get(pillar) or {}
        rv = bd.get("raw_values") or {}
        if field not in rv:
            continue
        present += 1
        val = rv[field]
        if isinstance(sentinel, str):
            if str(val) == sentinel:
                hits += 1
        elif isinstance(val, (int, float)) and isinstance(sentinel, (int, float)):
            if (abs(val - sentinel) < 1e-6) if approx else (val == sentinel):
                hits += 1
        elif val == sentinel:
            hits += 1
    return hits, present


def _pillar_scores(rows, pillar):
    out = []
    for r in rows:
        bd = (r.get("tqs_breakdown") or {}).get(pillar) or {}
        s = bd.get("score")
        if isinstance(s, (int, float)):
            out.append(s)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0)
    args = ap.parse_args()

    from pymongo import MongoClient
    mongo_url, db_name = _load_env()
    db = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)[db_name]

    now = datetime.now(timezone.utc)
    cutoff = ((now - timedelta(days=args.days)) if args.days else now).strftime("%Y-%m-%d")
    rows = list(db["live_alerts"].find(
        {"created_at": {"$gte": cutoff}, "tqs_breakdown": {"$exists": True, "$ne": {}}}
    ))
    if not rows:
        rows = list(db["live_alerts"].find(
            {"tqs_breakdown": {"$exists": True, "$ne": {}}}
        ).sort("created_at", -1).limit(300))
        print(f"(window empty — fell back to most-recent {len(rows)} alerts with a breakdown)")

    total = len(rows)
    print(f"\nDB: {db_name}   window>= {cutoff}   alerts WITH tqs_breakdown: {total}")
    # how many alerts even HAVE a breakdown vs total today
    all_today = db["live_alerts"].count_documents({"created_at": {"$gte": cutoff}})
    print(f"alerts in window total: {all_today}   "
          f"with breakdown: {total}  {_pct(total, all_today) if all_today else ''}")
    if not total:
        print("No alerts carry a persisted TQS breakdown. "
              "Either TQS isn't running, or the scanner build that persists "
              "tqs_breakdown isn't deployed. THIS ITSELF is the finding.")
        return

    # ---- overall TQS ----
    tqs = [float(r.get("tqs_score", 0) or 0) for r in rows if r.get("tqs_score")]
    print(f"\nOverall TQS: {_stats(tqs)}")
    print("grade counts:", dict(Counter(str(r.get('tqs_grade') or '—') for r in rows)))

    # ---- per-pillar score spread ----
    print("\n" + "=" * 72)
    print("PER-PILLAR SCORE SPREAD  (a healthy pillar should span widely, not pin)")
    print("=" * 72)
    for p in ("setup", "technical", "fundamental", "context", "execution"):
        ps = _pillar_scores(rows, p)
        print(f"  {p:12s} {_stats(ps)}   n={len(ps)}")

    # ---- DEFAULT-SENTINEL detection ----
    print("\n" + "=" * 72)
    print("DEFAULT-SENTINEL HIT RATE  (high % = pillar is scoring a CONSTANT, not real data)")
    print("=" * 72)

    checks = [
        # pillar, field, sentinel, human note
        ("technical", "rsi", 50.0, "RSI default"),
        ("technical", "rvol", 1.0, "RVOL default"),
        ("technical", "atr_percent", 2.0, "ATR% default"),
        ("technical", "ma_stack", "neutral", "MA-stack default"),
        ("technical", "vwap_distance_pct", 0.0, "VWAP-dist default"),
        ("setup", "win_rate", 0.5, "win-rate default (no learning sample)"),
        ("setup", "expected_value_r", 0.0, "EV default"),
        ("setup", "tape_confirmation", False, "tape NOT confirmed"),
        ("fundamental", "has_catalyst", False, "no catalyst"),
        ("fundamental", "short_interest_pct", 5.0, "SI default"),
        ("fundamental", "float_shares_millions", 100.0, "float default"),
        ("fundamental", "institutional_pct", 50.0, "institutional default"),
        ("execution", "recent_win_rate", 0.5, "exec win-rate default (no profile)"),
        ("execution", "avg_r_capture_pct", 75.0, "R-capture default (no profile)"),
        ("execution", "consecutive_losses", 0, "no-loss default"),
    ]
    cur_pillar = None
    for pillar, field, sentinel, note in checks:
        if pillar != cur_pillar:
            print(f"\n[{pillar.upper()}]")
            cur_pillar = pillar
        hits, present = _default_rate(rows, pillar, field, sentinel)
        flag = ""
        if present:
            r = hits / present
            flag = " ⬅ ALWAYS DEFAULT" if r > 0.95 else (" ⬅ mostly default" if r > 0.7 else "")
        print(f"  {field:22s} = {str(sentinel):8s} : {hits}/{present} {_pct(hits, present)}  {note}{flag}")

    # ---- tape sub-component (the scale-bug victim) ----
    print("\n" + "=" * 72)
    print("SETUP-PILLAR 'tape' COMPONENT (0-100)  — the scale-bug victim")
    print("=" * 72)
    tape_comp = []
    for r in rows:
        c = ((r.get("tqs_breakdown") or {}).get("setup") or {}).get("components") or {}
        if "tape" in c and isinstance(c["tape"], (int, float)):
            tape_comp.append(c["tape"])
    print(f"  {_stats(tape_comp)}   n={len(tape_comp)}")
    if tape_comp:
        pinned = sum(1 for t in tape_comp if t <= 30.0)
        print(f"  <=30 (pinned by the -1..1 bug): {pinned}/{len(tape_comp)} {_pct(pinned, len(tape_comp))}")

    print("\n" + "=" * 72)
    print("Done. Read-only.")
    print("=" * 72)


if __name__ == "__main__":
    main()
