#!/usr/bin/env python3
"""
diag_style_reconcile.py — READ-ONLY style-SSOT reconciliation audit.

The style-integrity audit proved ~49% of stamped trade_style disagrees with
style_of(). But style_of() is NOT automatically right: canonicalize() strips
horizon-bearing suffixes (e.g. '_confirmed'), so a setup with a DISTINCT raw
SETUP_TO_STYLE entry can be silently collapsed to a different horizon.

This diag decides, per setup, WHO is authoritative — so a future "TQS scores by
pattern" flip makes scores MORE correct, never less. For every setup seen in
live_alerts it prints:
    raw_tbl   = SETUP_TO_STYLE[setup_raw]           (explicit author intent)
    canon     = canonicalize(setup_raw)
    canon_tbl = SETUP_TO_STYLE[canon]               (what style_of sees)
    ssot      = style_of(setup_raw)                 (current SSOT output)
    stamp     = dominant stamped trade_style on alerts
    smb       = get_default_trade_style(setup)      (best-effort)

Verdict buckets (by ALERT count):
  ALIGNED        stamp == ssot (no action)
  FLIP_HELPS     drift, no over-collapse → ssot authoritative → flip improves
  SSOT_BUG       OVER-COLLAPSE: raw_tbl exists, != canon_tbl, and ssot != raw_tbl
                 → style_of is wrong here; fix SSOT (raw-first lookup) BEFORE flip
  REVIEW         drift but ambiguous (no raw_tbl, or three-way disagreement)

Nothing is written. Run from repo root (needs backend/ importable):
    python3 scripts/diag_style_reconcile.py --days 14
"""
import os
import sys
import argparse
from collections import defaultdict, Counter
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


def try_import_ssot():
    for bd in ("backend", ".", os.path.join(os.path.dirname(__file__), "..", "backend")):
        if os.path.isdir(bd) and os.path.exists(os.path.join(bd, "services", "setup_taxonomy.py")):
            sys.path.insert(0, os.path.abspath(bd))
            break
    style_of = canonicalize = setup_to_style = smb_default = None
    try:
        from services.setup_taxonomy import style_of as _s, canonicalize as _c
        style_of, canonicalize = _s, _c
    except Exception as e:
        print(f"  (FATAL: setup_taxonomy not importable: {e})")
        sys.exit(1)
    try:
        from services.trade_style_classifier import SETUP_TO_STYLE as _m
        setup_to_style = _m
    except Exception as e:
        print(f"  (note: SETUP_TO_STYLE not importable: {e})")
        setup_to_style = {}
    try:
        from services.smb_integration import get_default_trade_style as _g
        def smb_default(s):
            try:
                r = _g(s)
                return getattr(r, "value", str(r))
            except Exception:
                return None
    except Exception:
        smb_default = lambda s: None
    return style_of, canonicalize, setup_to_style, smb_default


def norm(x):
    return (str(x or "").strip().lower()) or None


def pct(n, d):
    return f"{(100.0*n/d):.0f}%" if d else "—"


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

    style_of, canonicalize, SETUP_TO_STYLE, smb_default = try_import_ssot()
    db = MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=5000)[env.get("DB_NAME") or "tradecommand"]
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%d")

    cur = db.live_alerts.find(
        {"created_at": {"$gte": since}, "tqs_score": {"$gt": 0}},
        {"setup_type": 1, "trade_style": 1})

    # setup -> Counter(stamped_style), and setup -> total
    stamp_by_setup = defaultdict(Counter)
    total_by_setup = Counter()
    n = 0
    for d in cur:
        s = norm(d.get("setup_type"))
        if not s:
            continue
        n += 1
        total_by_setup[s] += 1
        stamp_by_setup[s][norm(d.get("trade_style")) or "(missing)"] += 1

    rows = []
    buckets = Counter()          # verdict -> alert count
    bucket_setups = defaultdict(list)
    for setup, cnt in total_by_setup.most_common():
        raw_tbl = norm(SETUP_TO_STYLE.get(setup))
        canon = norm(canonicalize(setup))
        canon_tbl = norm(SETUP_TO_STYLE.get(canon))
        try:
            ssot = norm(style_of(setup))
        except Exception:
            ssot = None
        smb = norm(smb_default(setup))
        stamp = stamp_by_setup[setup].most_common(1)[0][0]

        over_collapse = (raw_tbl is not None and canon != setup and
                         raw_tbl != canon_tbl and ssot != raw_tbl)
        if stamp == ssot:
            verdict = "ALIGNED"
        elif over_collapse:
            verdict = "SSOT_BUG"
        elif ssot is not None and raw_tbl == ssot:
            verdict = "FLIP_HELPS"
        elif ssot is not None and raw_tbl is None and canon_tbl == ssot:
            verdict = "FLIP_HELPS"
        else:
            verdict = "REVIEW"

        buckets[verdict] += cnt
        bucket_setups[verdict].append((setup, cnt, stamp, raw_tbl, canon, canon_tbl, ssot, smb))
        rows.append((cnt, setup, stamp, raw_tbl, canon, canon_tbl, ssot, smb, verdict))

    print("=" * 100)
    print("  STYLE-SSOT RECONCILIATION  (read-only)")
    print(f"  db={env.get('DB_NAME') or 'tradecommand'}  window=last {args.days}d (since {since})  alerts={n}")
    print("=" * 100)

    print("\n  VERDICT ROLLUP (by alert count)")
    print("-" * 100)
    order = ["ALIGNED", "FLIP_HELPS", "SSOT_BUG", "REVIEW"]
    note = {
        "ALIGNED": "stamp already == ssot",
        "FLIP_HELPS": "ssot authoritative → flipping TQS to style_of IMPROVES these",
        "SSOT_BUG": "canonicalize over-collapse → style_of WRONG → fix SSOT first",
        "REVIEW": "ambiguous → operator ratify canonical style",
    }
    for k in order:
        print(f"  {k:<12}{buckets[k]:>8}  {pct(buckets[k], n):>5}   {note[k]}")
    drift = n - buckets["ALIGNED"]
    print(f"  {'(drift)':<12}{drift:>8}  {pct(drift, n):>5}")

    print("\n  PER-SETUP (sorted by alert volume)")
    print("-" * 100)
    print(f"  {'setup':<28}{'cnt':>6}  {'stamp':<10}{'raw_tbl':<10}{'canon':<22}{'ssot':<10}{'verdict'}")
    for cnt, setup, stamp, raw_tbl, canon, canon_tbl, ssot, smb, verdict in rows[:60]:
        flag = {"ALIGNED": "  ", "FLIP_HELPS": "✓ ", "SSOT_BUG": "🔴", "REVIEW": "🟡"}.get(verdict, "  ")
        print(f"  {setup:<28}{cnt:>6}  {str(stamp):<10}{str(raw_tbl):<10}{str(canon):<22}{str(ssot):<10}{flag}{verdict}")

    print("\n  🔴 SSOT_BUG setups (style_of mis-resolves — fix raw-first lookup):")
    print("-" * 100)
    for setup, cnt, stamp, raw_tbl, canon, canon_tbl, ssot, smb in sorted(
            bucket_setups["SSOT_BUG"], key=lambda r: -r[1])[:30]:
        print(f"  {setup:<28} x{cnt:<6} raw_tbl={raw_tbl} -> canon='{canon}' -> ssot={ssot}  (should be {raw_tbl})")

    print("\n  🟡 REVIEW setups (need operator ratification):")
    print("-" * 100)
    for setup, cnt, stamp, raw_tbl, canon, canon_tbl, ssot, smb in sorted(
            bucket_setups["REVIEW"], key=lambda r: -r[1])[:30]:
        print(f"  {setup:<28} x{cnt:<6} stamp={stamp} raw_tbl={raw_tbl} canon_tbl={canon_tbl} ssot={ssot} smb={smb}")

    print("\n" + "=" * 100)
    print("  DECISION: FLIP_HELPS% = how much of the drift the style_of flip fixes cleanly.")
    print("  SSOT_BUG% must be repaired in the SSOT (raw-first lookup) BEFORE flipping TQS.")
    print("=" * 100)


if __name__ == "__main__":
    main()
