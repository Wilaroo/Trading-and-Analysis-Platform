#!/usr/bin/env python3
"""
diag_tqs_today.py  (READ-ONLY)

Same pillar/grade distribution report as diag_tqs_pillar_distribution.py, but
filtered to TODAY'S session only (America/New_York calendar date) so you see a
CLEAN read of alerts scored under the new v19.34.230 code — no yesterday blur.

GRADE distribution is printed first (that's the headline for the v230 live-verify:
are B's appearing now that the floors are reachable?).

USAGE on the DGX:
    curl -s https://paste.rs/XXXX -o /tmp/diag_tqs_today.py
    python3 /tmp/diag_tqs_today.py
    # optional: pass an explicit ISO since-timestamp to start later, e.g.
    python3 /tmp/diag_tqs_today.py 2026-06-03T09:30
"""
import os
import sys
import statistics as st
from datetime import datetime
from zoneinfo import ZoneInfo


def _pct(s, p):
    if not s:
        return None
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (p / 100.0)
    lo = int(k); hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _row(label, vals):
    vals = [v for v in vals if isinstance(v, (int, float))]
    if not vals:
        return f"  {label:<22} n=0   (no data)"
    s = sorted(vals)
    return (f"  {label:<22} n={len(s):<5} min={s[0]:6.1f}  p10={_pct(s,10):6.1f}  "
            f"med={_pct(s,50):6.1f}  mean={st.mean(s):6.1f}  p90={_pct(s,90):6.1f}  "
            f"max={s[-1]:6.1f}  stdev={(st.pstdev(s) if len(s)>1 else 0):5.2f}")


def _get_db():
    from pymongo import MongoClient
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME") or "tradecommand"
    if not url:
        here = os.path.dirname(os.path.abspath(__file__))
        for cand in (os.getcwd(), here, os.path.expanduser("~/Trading-and-Analysis-Platform")):
            envp = os.path.join(cand, "backend", ".env")
            if os.path.isfile(envp):
                for line in open(envp):
                    line = line.strip()
                    if line.startswith("MONGO_URL=") and not url:
                        url = line.split("=", 1)[1]
                    if line.startswith("DB_NAME="):
                        name = line.split("=", 1)[1]
                break
    if not url:
        raise SystemExit("ERROR: MONGO_URL not set and backend/.env not found.")
    return MongoClient(url, serverSelectionTimeoutMS=2500)[name]


def main():
    # cutoff = explicit arg, else today's ET calendar date at 00:00
    if len(sys.argv) > 1:
        cutoff = sys.argv[1]
    else:
        cutoff = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    db = _get_db()
    rows = list(db["live_alerts"].find(
        {"created_at": {"$gte": cutoff}, "tqs_score": {"$gt": 0}},
        {"tqs_score": 1, "tqs_grade": 1, "tqs_pillar_scores": 1,
         "tqs_breakdown": 1, "setup_type": 1, "_id": 0},
    ))
    print("=" * 78)
    print(f"TQS TODAY  —  live_alerts with tqs_score>0 since {cutoff}")
    print(f"count: {len(rows)}")
    print("=" * 78)
    if not rows:
        print("No TQS-scored alerts yet today. (Pre-9:30 ET the scanner builds the")
        print("premarket watchlist but does NOT run the TQS engine — scored alerts")
        print("start flowing a scan cycle or two after the 9:30 RTH open.)")
        return

    # --- GRADE distribution FIRST (the headline) ---
    grades = {}
    for r in rows:
        g = r.get("tqs_grade") or "?"
        grades[g] = grades.get(g, 0) + 1
    print("\n[GRADE distribution]  (v230 live-verify: are B's appearing?)")
    order = {"A+": 0, "A": 1, "A-": 2, "B+": 3, "B": 4, "B-": 5, "C+": 6, "C": 7, "C-": 8, "D": 9, "F": 10}
    for g in sorted(grades, key=lambda x: order.get(x, 99)):
        bar = "#" * int(grades[g] / max(grades.values()) * 30)
        print(f"  {g:<3} {grades[g]:5d}  ({grades[g]/len(rows)*100:4.1f}%)  {bar}")

    # --- composite + pillars ---
    composite = [r.get("tqs_score") for r in rows]
    pillars = {p: [] for p in ("setup", "technical", "fundamental", "context", "execution")}
    for r in rows:
        ps = r.get("tqs_pillar_scores") or {}
        for p in pillars:
            v = ps.get(p)
            if isinstance(v, (int, float)):
                pillars[p].append(v)
    print("\n[COMPOSITE]")
    print(_row("tqs_score", composite))
    print("\n[PILLARS]")
    for p in ("setup", "technical", "fundamental", "context", "execution"):
        print(_row(p, pillars[p]))

    # --- setup sub-components (confirm A1/A2 un-pinned) ---
    setup_sub = {k: [] for k in ("pattern", "win_rate", "expected_value", "tape", "smb")}
    exec_sub = {k: [] for k in ("history", "tilt", "entry_tendency", "exit_tendency", "streak")}
    for r in rows:
        bd = r.get("tqs_breakdown") or {}
        sc = (bd.get("setup") or {}).get("components") or {}
        for k in setup_sub:
            v = sc.get(k)
            if isinstance(v, (int, float)):
                setup_sub[k].append(v)
        ec = (bd.get("execution") or {}).get("components") or {}
        for k in exec_sub:
            v = ec.get(k)
            if isinstance(v, (int, float)):
                exec_sub[k].append(v)
    if any(setup_sub.values()):
        print("\n[SETUP sub-components]  (A1: expected_value should no longer be pinned at 30; A2: smb 35→50)")
        for k in ("pattern", "win_rate", "expected_value", "tape", "smb"):
            print(_row(k, setup_sub[k]))
    if any(exec_sub.values()):
        print("\n[EXECUTION sub-components]  (B3: history should start varying as outcomes accrue)")
        for k in ("history", "tilt", "entry_tendency", "exit_tendency", "streak"):
            print(_row(k, exec_sub[k]))

    print("\nDONE (read-only).")


if __name__ == "__main__":
    main()
