#!/usr/bin/env python3
"""
diag_p1_drift_delta.py — READ-ONLY before/after proof-of-impact for the P1
Style=Pattern flip. One screen the team can screenshot.

It measures three things over a window of live_alerts (tradeable only —
watch/diagnostic triggers are edge-excluded and reported separately):

  BEFORE  liquidity-lens drift  : stamped trade_style != style_of(setup)
          = how often the OLD lens (liquidity stamp) disagreed with the
            pattern's true style. This is the ~42% the patch removes.
  AFTER   pattern-lens drift    : tqs_breakdown.scoring_style != style_of(setup)
          (post-patch alerts only) — should be ~0%.
  IMPACT  realized flip rate     : scoring_style != stamp  (post-patch alerts)
          = the % of LIVE alerts whose scoring lens the patch actually changed,
            with the top style transitions (e.g. intraday -> multi_day).

Nothing is written. Run from repo root with the venv python (AGENTS.md §2):
    .venv/bin/python scripts/diag_p1_drift_delta.py --days 14
"""
import os
import sys
import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta

try:
    from pymongo import MongoClient
except Exception:
    print("pymongo not importable — run inside the backend venv.")
    sys.exit(1)


def load_env(p):
    v = {}
    if p and os.path.exists(p):
        for ln in open(p):
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, val = ln.split("=", 1)
                v[k.strip()] = val.strip().strip('"').strip("'")
    for k in ("MONGO_URL", "DB_NAME"):
        v.setdefault(k, os.environ.get(k, ""))
    return v


def ssot():
    for bd in ("backend", ".", os.path.join(os.path.dirname(__file__), "..", "backend")):
        if os.path.isdir(bd) and os.path.exists(os.path.join(bd, "services", "setup_taxonomy.py")):
            sys.path.insert(0, os.path.abspath(bd))
            break
    from services.setup_taxonomy import style_of, is_edge_excluded
    return style_of, is_edge_excluded


def norm(x):
    return (str(x or "").strip().lower()) or None


def pct(n, d):
    return f"{(100.0*n/d):.1f}%" if d else "—"


def bar(p, width=24):
    fill = int(round((p / 100.0) * width)) if p else 0
    return "\u2588" * fill + "\u2591" * (width - fill)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=None)
    ap.add_argument("--days", type=int, default=14)
    args = ap.parse_args()

    env_path = args.env
    if env_path is None:
        for c in ("/app/backend/.env", "backend/.env", ".env"):
            if os.path.exists(c):
                env_path = c
                break
    env = load_env(env_path)
    if not env.get("MONGO_URL"):
        print("MONGO_URL not found. Pass --env /path/to/backend/.env")
        sys.exit(1)

    style_of, is_edge_excluded = ssot()
    db = MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=5000)[env.get("DB_NAME") or "tradecommand"]
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%d")

    cur = db.live_alerts.find(
        {"created_at": {"$gte": since}, "tqs_score": {"$gt": 0}},
        {"setup_type": 1, "trade_style": 1, "tqs_breakdown": 1})

    n = watch = 0
    before_n = before_drift = 0
    post_n = after_drift = flipped = 0
    before_trans = Counter()   # stamp -> pattern (historical liquidity drift)
    flip_trans = Counter()     # stamp -> scoring_style (realized change)
    after_bad = Counter()

    for d in cur:
        setup = norm(d.get("setup_type"))
        if setup and is_edge_excluded(setup):
            watch += 1
            continue
        n += 1
        stamp = norm(d.get("trade_style"))
        bd = d.get("tqs_breakdown") or {}
        ss = norm(bd.get("scoring_style")) if isinstance(bd, dict) else None
        try:
            pat = norm(style_of(setup))
        except Exception:
            pat = None
        valid_pat = pat and pat != "unknown"

        # BEFORE — what the OLD liquidity lens (stamp) cost vs the pattern
        if stamp and valid_pat:
            before_n += 1
            if stamp != pat:
                before_drift += 1
                before_trans[f"{stamp} -> {pat}"] += 1

        # AFTER + IMPACT — only post-patch alerts carry scoring_style
        if ss:
            post_n += 1
            if valid_pat and ss != pat:
                after_drift += 1
                after_bad[f"{setup}: scoring={ss} pattern={pat}"] += 1
            if stamp and ss != stamp:
                flipped += 1
                flip_trans[f"{stamp} -> {ss}"] += 1

    bdr = (100.0 * before_drift / before_n) if before_n else 0.0
    adr = (100.0 * after_drift / post_n) if post_n else 0.0
    fr = (100.0 * flipped / post_n) if post_n else 0.0

    print("=" * 84)
    print("  P1 DRIFT DELTA — Liquidity lens  ->  Pattern lens  (read-only proof-of-impact)")
    print(f"  db={env.get('DB_NAME') or 'tradecommand'}  window=last {args.days}d (since {since})")
    print(f"  tradeable alerts={n}   watch/diagnostic skipped={watch}")
    print("=" * 84)

    print("\n  BEFORE  liquidity-lens drift  (stamp != pattern, over all tradeable)")
    print(f"          {bar(bdr)}  {before_drift}/{before_n}  = {pct(before_drift, before_n)}")
    print("          ^ how often the old liquidity stamp mis-scored vs the true pattern")

    print("\n  AFTER   pattern-lens drift    (scoring_style != pattern, post-patch only)")
    print(f"          {bar(adr)}  {after_drift}/{post_n}  = {pct(after_drift, post_n)}   target ~0%")

    print("\n  IMPACT  realized flip rate    (scoring_style != stamp, post-patch only)")
    print(f"          {bar(fr)}  {flipped}/{post_n}  = {pct(flipped, post_n)}")
    print("          ^ share of LIVE alerts whose scoring lens the patch actually changed")

    print("\n" + "-" * 84)
    print(f"  HEADLINE:  liquidity-lens drift {pct(before_drift, before_n)}  ->  "
          f"pattern-lens drift {pct(after_drift, post_n)}   "
          f"(lens flipped on {pct(flipped, post_n)} of live alerts)")
    print("-" * 84)

    if before_trans:
        print("\n  historical mis-score transitions (stamp -> pattern), top 12:")
        for k, c in before_trans.most_common(12):
            print(f"    x{c:<6} {k}")
    if flip_trans:
        print("\n  realized lens flips on live alerts (stamp -> scoring_style), top 12:")
        for k, c in flip_trans.most_common(12):
            print(f"    x{c:<6} {k}")
    if after_bad:
        print("\n  \u26a0 residual pattern-lens drift (investigate — should be empty):")
        for k, c in after_bad.most_common(12):
            print(f"    x{c:<6} {k}")

    if post_n == 0:
        print("\n  NOTE: 0 post-patch alerts in window — run after the scanner has scored")
        print("        fresh alerts (use a window that includes post-restart alerts).")
    print("\n" + "=" * 84)


if __name__ == "__main__":
    main()
