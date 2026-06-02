#!/usr/bin/env python3
"""
diag_signal_distributions.py  (READ-ONLY)

Empirically dumps the live distributions of the four core bot signals across
recent `live_alerts` so we can confirm the audit findings BEFORE changing code:

  1. tape_score          - suspected scale bug (-1..+1 emitted into 0-10/0-100 consumers)
  2. trigger_probability - suspected static-per-setup constant in the live engine
  3. priority            - suspected saturated to HIGH/CRITICAL (auto-exec gate)
  4. tqs_score / grade    - downstream effect of the tape pillar distortion

Usage on the DGX:
    python3 /tmp/diag_signal_distributions.py            # today (UTC)
    python3 /tmp/diag_signal_distributions.py --days 3   # last 3 calendar days
    python3 /tmp/diag_signal_distributions.py --days 7

Nothing is written. Pure aggregation + print.
"""

import os
import sys
import argparse
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta


def _load_env():
    """Read MONGO_URL / DB_NAME the same way the app does, without importing it."""
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    for candidate in ("/app/backend/.env", "./backend/.env", "backend/.env", ".env"):
        if (mongo_url and db_name) or not os.path.exists(candidate):
            continue
        with open(candidate) as fh:
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
    return f"{(100.0 * n / total):5.1f}%" if total else "  n/a"


def _bar(n, total, width=30):
    filled = int(round(width * n / total)) if total else 0
    return "█" * filled + "·" * (width - filled)


def _section(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0,
                    help="lookback in calendar days (0 = today UTC only)")
    args = ap.parse_args()

    try:
        from pymongo import MongoClient
    except ImportError:
        print("pymongo not installed in this environment.", file=sys.stderr)
        sys.exit(1)

    mongo_url, db_name = _load_env()
    client = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
    db = client[db_name]

    now = datetime.now(timezone.utc)
    if args.days and args.days > 0:
        cutoff = (now - timedelta(days=args.days)).strftime("%Y-%m-%d")
        label = f"last {args.days} day(s) (created_at >= {cutoff} UTC)"
    else:
        cutoff = now.strftime("%Y-%m-%d")
        label = f"today {cutoff} (UTC)"

    query = {"created_at": {"$gte": cutoff}}
    rows = list(db["live_alerts"].find(query))

    print(f"\nDB: {db_name}   collection: live_alerts")
    print(f"Window: {label}")
    print(f"Matched alerts: {len(rows)}")

    if not rows:
        # fall back: show the most recent 200 regardless of date so the operator
        # still sees *something* if today's session hasn't produced alerts yet.
        rows = list(db["live_alerts"].find().sort("created_at", -1).limit(200))
        print(f"(no rows in window — falling back to most-recent {len(rows)} alerts)")
        if not rows:
            print("No live_alerts at all. Nothing to analyze.")
            return

    total = len(rows)

    # ---------- 1. tape_score ----------
    _section("1) tape_score  (producer says -1.0..+1.0; consumers assume 0-10/0-100)")
    tapes = [float(r.get("tape_score", 0.0) or 0.0) for r in rows]
    have_tape = [t for t in tapes if t != 0.0]
    print(f"present (non-zero): {len(have_tape)}/{total}   zero/missing: {total - len(have_tape)}")
    if tapes:
        print(f"min={min(tapes):+.3f}  max={max(tapes):+.3f}  "
              f"mean={statistics.mean(tapes):+.3f}  median={statistics.median(tapes):+.3f}")
    in_unit = sum(1 for t in tapes if -1.0001 <= t <= 1.0001)
    print(f"within -1..+1 range: {in_unit}/{total}  {_pct(in_unit, total)}  "
          f"(if ~100%, scanner is emitting the raw unit-scale float)")
    print(f"exactly +0.2 (tight-spread-only, L2 missing): "
          f"{sum(1 for t in tapes if abs(t - 0.2) < 1e-9)}/{total}")
    print(f"<= 0 (collapses to hard-coded 30 in setup_quality): "
          f"{sum(1 for t in tapes if t <= 0)}/{total}")
    print(f"< 4  (triggers 'Weak tape' factor in setup_quality): "
          f"{sum(1 for t in tapes if t < 4)}/{total}  <- if 100%, every alert is mislabeled weak")
    print("\nhistogram:")
    buckets = [(-1.01, -0.3), (-0.3, -0.1), (-0.1, 0.1), (0.1, 0.3), (0.3, 1.01)]
    for lo, hi in buckets:
        c = sum(1 for t in tapes if lo <= t < hi)
        print(f"  [{lo:+.2f},{hi:+.2f}) {_bar(c, total)} {c:4d}  {_pct(c, total)}")
    # what the TQS tape pillar actually resolves to today
    def _tape_pillar(t):
        return min(t / 10.0, 1.0) * 100 if t > 0 else 30.0
    pillar_vals = [_tape_pillar(t) for t in tapes]
    print(f"\n=> setup_quality tape-pillar (0-100) ACTUAL: "
          f"min={min(pillar_vals):.1f} max={max(pillar_vals):.1f} mean={statistics.mean(pillar_vals):.1f}")
    print("   (a healthy 20%-weight pillar should span ~0-100; if pinned low, it's broken)")

    # ---------- 2. trigger_probability ----------
    _section("2) trigger_probability  (0..1; suspected static per setup_type)")
    tp_by_setup = defaultdict(set)
    tps = []
    for r in rows:
        tp = r.get("trigger_probability")
        if tp is None:
            continue
        tp = float(tp)
        tps.append(tp)
        tp_by_setup[str(r.get("setup_type", "?"))].add(round(tp, 4))
    if tps:
        print(f"present: {len(tps)}/{total}  min={min(tps):.2f} max={max(tps):.2f} "
              f"mean={statistics.mean(tps):.3f}  distinct values={len(set(round(t,4) for t in tps))}")
        vc = Counter(round(t, 2) for t in tps)
        print("value counts:")
        for val, c in sorted(vc.items()):
            print(f"  {val:.2f} {_bar(c, total)} {c:4d}  {_pct(c, total)}")
        # the smoking gun: does each setup_type map to exactly ONE constant?
        multi = {s: vs for s, vs in tp_by_setup.items() if len(vs) > 1}
        print(f"\nsetup_types observed: {len(tp_by_setup)}   "
              f"of which vary trigger_prob across alerts: {len(multi)}")
        if not multi:
            print("  => EVERY setup_type emits a SINGLE constant trigger_prob "
                  "(confirms it's static, not live-computed).")
        else:
            for s, vs in list(multi.items())[:10]:
                print(f"    {s}: {sorted(vs)}")
    else:
        print("no trigger_probability values present.")

    # ---------- 3. priority ----------
    _section("3) priority  (gate: auto-exec requires HIGH/CRITICAL)")
    pc = Counter(str(r.get("priority", "?")).lower() for r in rows)
    for p in ("critical", "high", "medium", "low", "?"):
        if pc.get(p):
            print(f"  {p:8s} {_bar(pc[p], total)} {pc[p]:4d}  {_pct(pc[p], total)}")
    autoexec = pc.get("critical", 0) + pc.get("high", 0)
    print(f"\n=> auto-exec-eligible (HIGH+CRITICAL): {autoexec}/{total}  {_pct(autoexec, total)}")
    tc = sum(1 for r in rows if r.get("tape_confirmation"))
    print(f"=> tape_confirmation == True: {tc}/{total}  {_pct(tc, total)}  "
          f"(saturation here inflates priority)")

    # ---------- 4. tqs ----------
    _section("4) tqs_score / tqs_grade  (downstream of the tape pillar)")
    tqs = [float(r.get("tqs_score", 0) or 0) for r in rows if r.get("tqs_score")]
    if tqs:
        print(f"present: {len(tqs)}/{total}  min={min(tqs):.1f} max={max(tqs):.1f} "
              f"mean={statistics.mean(tqs):.1f} median={statistics.median(tqs):.1f}")
    else:
        print("no tqs_score populated on these alerts.")
    gc = Counter(str(r.get("tqs_grade", "") or "—") for r in rows)
    print("grade counts:")
    for g, c in sorted(gc.items(), key=lambda kv: (-kv[1])):
        print(f"  {g:3s} {_bar(c, total)} {c:4d}  {_pct(c, total)}")

    print("\n" + "=" * 72)
    print("Done. Read-only — nothing was modified.")
    print("=" * 72)


if __name__ == "__main__":
    main()
