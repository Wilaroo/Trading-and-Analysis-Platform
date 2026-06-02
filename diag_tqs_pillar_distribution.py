#!/usr/bin/env python3
"""
diag_tqs_pillar_distribution.py  (READ-ONLY)

v19.34.230-diag — Measure the live TQS pillar + sub-component distributions on the
DGX so the upcoming pillar de-compression patch is grounded in real numbers
(not stale handoff figures).

Reads recent `live_alerts` and reports, for the composite score and each of the
5 pillars (setup / technical / fundamental / context / execution):
    n, min, p10, median, mean, p90, max, stdev
Plus the setup sub-components (pattern/win_rate/EV/tape/smb) and execution
sub-components (history/tilt/entry/exit/streak) so we can SEE exactly which
inputs are pinned at their defaults and crushing the variance.

NOTHING is written. Safe to run anytime.

USAGE on the DGX:
    curl -s https://paste.rs/XXXX -o /tmp/diag_tqs_dist.py
    python3 /tmp/diag_tqs_dist.py            # default: last 5 days
    python3 /tmp/diag_tqs_dist.py 7          # last 7 days
"""
import os
import sys
import statistics as st
from datetime import datetime, timedelta, timezone


def _pct(sorted_vals, p):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def _row(label, vals):
    vals = [v for v in vals if isinstance(v, (int, float))]
    if not vals:
        return f"  {label:<22} n=0   (no data)"
    s = sorted(vals)
    return (
        f"  {label:<22} n={len(s):<5} "
        f"min={s[0]:6.1f}  p10={_pct(s,10):6.1f}  med={_pct(s,50):6.1f}  "
        f"mean={st.mean(s):6.1f}  p90={_pct(s,90):6.1f}  max={s[-1]:6.1f}  "
        f"stdev={(st.pstdev(s) if len(s)>1 else 0):5.2f}"
    )


def _get_db():
    from pymongo import MongoClient
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME") or "tradecommand"
    if not url:
        # try loading backend/.env if env not exported
        here = os.path.dirname(os.path.abspath(__file__))
        for cand in (os.getcwd(), here):
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
    return MongoClient(url, serverSelectionTimeoutMS=2000)[name]


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    db = _get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    rows = list(db["live_alerts"].find(
        {"created_at": {"$gte": cutoff}, "tqs_score": {"$gt": 0}},
        {"tqs_score": 1, "tqs_grade": 1, "tqs_pillar_scores": 1,
         "tqs_breakdown": 1, "setup_type": 1, "_id": 0},
    ))
    print("=" * 78)
    print(f"TQS PILLAR DISTRIBUTION  —  live_alerts since {cutoff} ({days}d)")
    print(f"alerts with tqs_score>0: {len(rows)}")
    print("=" * 78)
    if not rows:
        print("No alerts found in window. Try a larger day count.")
        return

    # --- composite + pillar distributions ---
    composite = [r.get("tqs_score") for r in rows]
    pillars = {p: [] for p in ("setup", "technical", "fundamental", "context", "execution")}
    have_pillars = 0
    for r in rows:
        ps = r.get("tqs_pillar_scores") or {}
        if ps:
            have_pillars += 1
        for p in pillars:
            v = ps.get(p)
            if isinstance(v, (int, float)):
                pillars[p].append(v)

    print(f"\n[COMPOSITE]")
    print(_row("tqs_score", composite))
    print(f"\n[PILLARS]  (alerts with stored pillar breakdown: {have_pillars}/{len(rows)})")
    for p in ("setup", "technical", "fundamental", "context", "execution"):
        print(_row(p, pillars[p]))

    # --- setup sub-components ---
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
        print(f"\n[SETUP sub-components]  (weights: pattern .20 / win_rate .25 / EV .20 / tape .20 / smb .15)")
        for k in ("pattern", "win_rate", "expected_value", "tape", "smb"):
            print(_row(k, setup_sub[k]))
    else:
        print("\n[SETUP sub-components]  no tqs_breakdown stored on these alerts")

    if any(exec_sub.values()):
        print(f"\n[EXECUTION sub-components]  (weights: history .25 / tilt .30 / entry .15 / exit .15 / streak .15)")
        for k in ("history", "tilt", "entry_tendency", "exit_tendency", "streak"):
            print(_row(k, exec_sub[k]))
    else:
        print("\n[EXECUTION sub-components]  no tqs_breakdown stored on these alerts")

    # --- grade distribution ---
    grades = {}
    for r in rows:
        g = r.get("tqs_grade") or "?"
        grades[g] = grades.get(g, 0) + 1
    print("\n[GRADE distribution]")
    for g in sorted(grades, key=lambda x: (-grades[x], x)):
        print(f"  {g:<3} {grades[g]:5d}  ({grades[g]/len(rows)*100:4.1f}%)")

    # --- per-setup_type setup-pillar spread (top 12 by count) ---
    by_setup = {}
    for r in rows:
        stp = r.get("setup_type") or "?"
        ps = (r.get("tqs_pillar_scores") or {}).get("setup")
        if isinstance(ps, (int, float)):
            by_setup.setdefault(stp, []).append(ps)
    if by_setup:
        print("\n[SETUP pillar by setup_type]  (shows whether pattern-tier variance survives)")
        ordered = sorted(by_setup.items(), key=lambda kv: -len(kv[1]))[:12]
        for stp, vals in ordered:
            s = sorted(vals)
            print(f"  {stp:<26} n={len(s):<4} med={_pct(s,50):5.1f}  min={s[0]:5.1f}  max={s[-1]:5.1f}")

    print("\nDONE (read-only). Share this output back to design the de-compression patch.")


if __name__ == "__main__":
    main()
