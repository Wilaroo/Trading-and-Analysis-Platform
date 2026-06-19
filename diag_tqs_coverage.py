#!/usr/bin/env python3
"""
diag_tqs_coverage.py — READ-ONLY TQS data-coverage audit.

Measures, across recently scored alerts, how much of each TQS pillar/sub-score
is backed by REAL data vs falling back to a "No data" default. This is the
honest real-vs-default picture the v391/v393/v396/v398 audit has been driving
toward — and the data source for a future "TQS Data Coverage" V5 tile.

The authoritative tell is the descriptor layer's verdict: a sub-score whose
`display.<component>.verdict == "No data"` was scored from absent data (set via
`absent=True` in the pillar `_display()` methods). Everything else is real.

Nothing is written. Safe to run anytime, repeatedly (incl. during a backfill).

Usage (on the DGX, from the repo root):
    python3 diag_tqs_coverage.py
    python3 diag_tqs_coverage.py --days 7 --limit 0   # 0 = no cap
"""
import os
import sys
import argparse
from datetime import datetime, timezone, timedelta
from collections import defaultdict

try:
    from pymongo import MongoClient
except Exception:
    print("pymongo not importable — run inside the backend venv.")
    sys.exit(1)

NO_DATA = "No data"
PILLARS = ["setup", "technical", "fundamental", "context", "execution"]


def load_env(env_path):
    vals = {}
    if env_path and os.path.exists(env_path):
        for line in open(env_path):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("MONGO_URL", "DB_NAME"):
        vals.setdefault(k, os.environ.get(k, ""))
    return vals


def bar(pct, width=22):
    filled = int(round(pct / 100 * width))
    return "█" * filled + "░" * (width - filled)


def flag(pct):
    if pct >= 80:
        return "OK"
    if pct >= 50:
        return "🟡"
    return "🔴"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=None)
    ap.add_argument("--days", type=int, default=7,
                    help="look-back window over live_alerts.created_at")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap sampled alerts (0 = no cap)")
    args = ap.parse_args()

    env_path = args.env
    if env_path is None:
        for c in ("/app/backend/.env", "backend/.env", ".env",
                  os.path.join(os.path.dirname(__file__), "..", "backend", ".env")):
            if os.path.exists(c):
                env_path = c
                break
    env = load_env(env_path)
    if not env.get("MONGO_URL"):
        print("MONGO_URL not found. Pass --env /path/to/backend/.env")
        sys.exit(1)

    db = MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=5000)[env.get("DB_NAME") or "tradecommand"]
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=args.days)).strftime("%Y-%m-%d")

    q = {"created_at": {"$gte": since}, "tqs_score": {"$gt": 0}}
    cur = db.live_alerts.find(q, {"tqs_breakdown": 1, "symbol": 1, "created_at": 1}) \
                        .sort("created_at", -1)
    if args.limit:
        cur = cur.limit(args.limit)

    # per-component tallies: comp_key -> {label, total, no_data, score_sum, on_50}
    comp = defaultdict(lambda: defaultdict(lambda: {"label": "", "total": 0, "no_data": 0, "on_50": 0}))
    pillar_tot = defaultdict(lambda: {"sub_total": 0, "sub_no_data": 0})
    n_alerts = 0
    n_with_breakdown = 0
    n_with_display = 0
    sample = None

    for doc in cur:
        n_alerts += 1
        bd = doc.get("tqs_breakdown") or {}
        if not bd:
            continue
        n_with_breakdown += 1
        had_display = False
        for p in PILLARS:
            pdata = bd.get(p)
            if not isinstance(pdata, dict):
                continue
            disp = pdata.get("display")
            comps = pdata.get("components") or {}
            if not isinstance(disp, dict):
                continue
            had_display = True
            for ckey, block in disp.items():
                if not isinstance(block, dict):
                    continue
                rec = comp[p][ckey]
                rec["label"] = block.get("label", ckey)
                rec["total"] += 1
                verdict = block.get("verdict", "")
                is_nd = (verdict == NO_DATA)
                if is_nd:
                    rec["no_data"] += 1
                # cross-check: numeric score sitting exactly on the 50 default
                sc = comps.get(ckey)
                if isinstance(sc, (int, float)) and abs(float(sc) - 50.0) < 0.05:
                    rec["on_50"] += 1
                pillar_tot[p]["sub_total"] += 1
                pillar_tot[p]["sub_no_data"] += 1 if is_nd else 0
        if had_display:
            n_with_display += 1
            if sample is None:
                sample = doc

    print("=" * 80)
    print("  TQS DATA-COVERAGE AUDIT   (read-only)   real vs 'No data' default")
    print(f"  db={env.get('DB_NAME') or 'tradecommand'}   window=last {args.days}d "
          f"(since {since})   now={now.isoformat()[:19]}Z")
    print("=" * 80)
    print(f"  alerts scanned        : {n_alerts}")
    print(f"  with tqs_breakdown    : {n_with_breakdown}")
    print(f"  with display blocks   : {n_with_display}"
          f"   ({n_with_breakdown - n_with_display} legacy / no-display)")

    if n_with_display == 0:
        print("\n  No alerts carry descriptor `display` blocks in this window.")
        print("  (Either pre-v391 alerts, or none scored recently.) Try --days 30.")
        return

    grand_total = grand_nd = 0
    for p in PILLARS:
        recs = comp.get(p)
        if not recs:
            continue
        pt = pillar_tot[p]
        p_cov = 100.0 * (1 - pt["sub_no_data"] / pt["sub_total"]) if pt["sub_total"] else 0
        grand_total += pt["sub_total"]
        grand_nd += pt["sub_no_data"]
        print("\n" + "-" * 80)
        print(f"  {p.upper():<12} pillar coverage: {bar(p_cov)} {p_cov:5.1f}%  {flag(p_cov)}")
        print(f"  {'component':<18}{'samples':<9}{'real%':<8}{'no-data%':<10}{'on-50%':<8}{''}")
        for ckey, rec in sorted(recs.items()):
            tot = rec["total"]
            if not tot:
                continue
            real_pct = 100.0 * (tot - rec["no_data"]) / tot
            nd_pct = 100.0 * rec["no_data"] / tot
            on50_pct = 100.0 * rec["on_50"] / tot
            print(f"  {rec['label'][:17]:<18}{tot:<9}{real_pct:<8.0f}{nd_pct:<10.0f}"
                  f"{on50_pct:<8.0f}{flag(real_pct)}")

    overall = 100.0 * (1 - grand_nd / grand_total) if grand_total else 0
    print("\n" + "=" * 80)
    print(f"  OVERALL TQS DATA COVERAGE: {bar(overall)} {overall:5.1f}%  "
          f"({grand_total - grand_nd}/{grand_total} sub-scores real)")
    print("=" * 80)

    if sample is not None:
        print(f"\n  sample alert: {sample.get('symbol')} @ {str(sample.get('created_at'))[:19]}")
        bd = sample.get("tqs_breakdown") or {}
        for p in PILLARS:
            pdata = bd.get(p)
            if not isinstance(pdata, dict):
                continue
            disp = pdata.get("display") or {}
            verds = [f"{b.get('label')}={b.get('verdict')}" for b in disp.values()
                     if isinstance(b, dict)]
            if verds:
                print(f"    {p:<12}: {', '.join(verds)}")

    print("\n  Legend: real% = data-backed sub-scores; no-data% = scored from")
    print("  absent data (descriptor verdict 'No data'); on-50% = numeric score")
    print("  sitting exactly on the 50 neutral default (cross-check). 🔴<50 🟡<80 OK>=80")


if __name__ == "__main__":
    main()
