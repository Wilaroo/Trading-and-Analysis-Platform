#!/usr/bin/env python3
"""
diag_p1_verify.py — READ-ONLY P1 verification (run AFTER patch + backend restart).

Confirms the Style=Pattern flip on freshly-scored alerts:
  [1] persistence : % alerts carrying tqs_breakdown.scoring_style + weights_used
  [2] pattern-correct : scoring_style == style_of(setup_type)   -> target ~100%
  [3] weight fidelity : applied fundamental-weight == STYLE_WEIGHTS[scoring_style]
  [4] (informational) stamp(execution horizon) vs pattern(scoring) divergence
      — EXPECTED to be non-zero by design; the stamp drives brackets/TIF, the
      scoring lens drives TQS. Not an error.

WATCH/DIAGNOSTIC TRIGGERS are SKIPPED: approaching_* and carry_forward_watch are
edge-excluded non-trades (pre-fire "checks in favor" / EOD carry-over), so they
carry no honest pattern style. They are reported separately, never counted as
pattern mismatches.

Run from repo root, after a few new alerts have scored post-restart:
    python3 scripts/diag_p1_verify.py --days 1
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
    from services.tqs.tqs_engine import TQSEngine
    return style_of, is_edge_excluded, getattr(TQSEngine, "STYLE_WEIGHTS", {})


def norm(x):
    return (str(x or "").strip().lower()) or None


def pct(n, d):
    return f"{(100.0*n/d):.1f}%" if d else "—"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=None)
    ap.add_argument("--days", type=int, default=1)
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

    style_of, is_edge_excluded, STYLE_WEIGHTS = ssot()
    db = MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=5000)[env.get("DB_NAME") or "tradecommand"]
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%d")

    cur = db.live_alerts.find(
        {"created_at": {"$gte": since}, "tqs_score": {"$gt": 0}},
        {"setup_type": 1, "trade_style": 1, "tqs_breakdown": 1})

    n = persisted = pattern_ok = weight_ok = weight_checked = stamp_div = watch_skipped = 0
    bad_pattern = Counter()
    watch_kinds = Counter()
    for d in cur:
        setup = norm(d.get("setup_type"))
        # P1: skip edge-excluded watch/diagnostic triggers (approaching_*,
        # carry_forward_watch, reconciled_*, imported_from_ib). Not trades ->
        # no honest pattern style, so they must not count as mismatches.
        try:
            if setup and is_edge_excluded(setup):
                watch_skipped += 1
                watch_kinds[setup] += 1
                continue
        except Exception:
            pass
        n += 1
        stamp = norm(d.get("trade_style"))
        bd = d.get("tqs_breakdown") or {}
        ss = norm(bd.get("scoring_style")) if isinstance(bd, dict) else None
        wu = bd.get("weights_used") if isinstance(bd, dict) else None
        if ss and isinstance(wu, dict) and wu:
            persisted += 1
        else:
            continue
        try:
            expect = norm(style_of(setup))
        except Exception:
            expect = None
        if expect and ss == expect:
            pattern_ok += 1
        else:
            bad_pattern[f"{setup}: scoring={ss} expect={expect}"] += 1
        if ss in STYLE_WEIGHTS and "fundamental" in wu:
            weight_checked += 1
            try:
                if abs(float(wu["fundamental"]) - float(STYLE_WEIGHTS[ss]["fundamental"])) < 1e-6:
                    weight_ok += 1
            except Exception:
                pass
        if stamp and ss and stamp != ss:
            stamp_div += 1

    print("=" * 80)
    print("  P1 VERIFY — Style = Pattern (read-only)")
    print(f"  db={env.get('DB_NAME') or 'tradecommand'}  window=last {args.days}d (since {since})")
    print("=" * 80)
    print(f"  tradeable alerts scanned  : {n}   (watch/diag skipped: {watch_skipped})")
    print(f"  [1] persisted scoring_style+weights : {persisted}  ({pct(persisted, n)})")
    print(f"      (older pre-patch alerts won't carry these; use a tight --days window)")
    print(f"  [2] pattern-correct (ss==style_of)  : {pattern_ok}/{persisted}  ({pct(pattern_ok, persisted)})  target ~100%")
    print(f"  [3] weight fidelity (fund weight)   : {weight_ok}/{weight_checked}  ({pct(weight_ok, weight_checked)})")
    print(f"  [4] stamp!=pattern (INFORMATIONAL)  : {stamp_div}/{persisted}  ({pct(stamp_div, persisted)})  <- expected by design")

    if watch_kinds:
        print("\n  watch/diagnostic triggers skipped (edge-excluded, NOT scored as trades):")
        for k, c in watch_kinds.most_common(20):
            print(f"    x{c:<5} {k}")

    if bad_pattern:
        print("\n  \u26a0 pattern mismatches (investigate if non-trivial):")
        for k, c in bad_pattern.most_common(20):
            print(f"    x{c:<5} {k}")
    else:
        print("\n  \u2705 every persisted tradeable alert scored by its pattern-intrinsic style.")

    print("\n" + "=" * 80)
    print("  PASS when [1] high on fresh alerts, [2] ~100%, [3] ~100%.")
    print("  [4] non-zero is correct: execution horizon (stamp) != scoring lens (pattern).")
    print("=" * 80)


if __name__ == "__main__":
    main()
