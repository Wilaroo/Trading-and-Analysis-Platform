#!/usr/bin/env python3
"""
diag_style_integrity.py — READ-ONLY style/taxonomy alignment audit.

Answers: "are all systems on the same page about trade-style?" by cross-tabbing,
over recently scored alerts:
    setup_type -> canonical_setup -> STAMPED trade_style -> weights actually used

Checks:
  [A] distribution of stamped trade_style (are swing/position present at all?)
  [B] alerts with MISSING / unknown trade_style (these hit the lossy fallback)
  [C] DRIFT: stamped trade_style != SSOT style_of(setup_type) recomputed now
  [D] WEIGHT FIDELITY: for each stamped style, the fundamental-weight actually
      applied (from tqs_breakdown.weights_used) vs the expected STYLE_WEIGHTS
      profile — proves swing/position alerts really got swing/position weighting

Nothing is written. Run from the repo root (needs backend/ importable):
    python3 diag_style_integrity.py
    python3 diag_style_integrity.py --days 14
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
    """Import the SSOT style resolver + TQS weight table for recompute/fidelity."""
    for bd in ("backend", ".", os.path.join(os.path.dirname(__file__), "backend")):
        if os.path.isdir(bd) and os.path.exists(os.path.join(bd, "services", "setup_taxonomy.py")):
            sys.path.insert(0, os.path.abspath(bd))
            break
    style_of = canonicalize = weights = None
    try:
        from services.setup_taxonomy import style_of as _s, canonicalize as _c
        style_of, canonicalize = _s, _c
    except Exception as e:
        print(f"  (note: could not import setup_taxonomy SSOT — drift check skipped: {e})")
    try:
        from services.tqs.tqs_engine import TQSEngine
        weights = TQSEngine.STYLE_WEIGHTS
    except Exception as e:
        print(f"  (note: could not import TQS STYLE_WEIGHTS — expected-profile skipped: {e})")
    return style_of, canonicalize, weights


def pct(n, d):
    return f"{(100.0*n/d):.0f}%" if d else "—"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=None)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--limit", type=int, default=0)
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

    style_of, canonicalize, STYLE_WEIGHTS = try_import_ssot()
    db = MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=5000)[env.get("DB_NAME") or "tradecommand"]
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=args.days)).strftime("%Y-%m-%d")

    cur = db.live_alerts.find(
        {"created_at": {"$gte": since}, "tqs_score": {"$gt": 0}},
        {"setup_type": 1, "canonical_setup": 1, "trade_style": 1,
         "tqs_breakdown": 1}).sort("created_at", -1)
    if args.limit:
        cur = cur.limit(args.limit)

    stamped = Counter()
    missing = 0
    drift = []                                  # (setup_type, stamped, recomputed)
    setup_to_stamped = defaultdict(Counter)
    fund_w_by_style = defaultdict(list)         # stamped_style -> [fundamental weights seen]
    weights_seen = 0
    n = 0

    for d in cur:
        n += 1
        setup = d.get("setup_type") or "—"
        st = (d.get("trade_style") or "").strip().lower()
        if not st or st in ("unknown", "none"):
            missing += 1
            st_key = st or "(missing)"
        else:
            st_key = st
        stamped[st_key] += 1
        setup_to_stamped[setup][st_key] += 1

        # drift vs SSOT recompute
        if style_of is not None and setup != "—":
            try:
                recomputed = (style_of(setup) or "").lower()
                if recomputed and recomputed != "unknown" and st and st not in ("unknown", "none") \
                        and recomputed != st:
                    drift.append((setup, st, recomputed))
            except Exception:
                pass

        # weight fidelity
        bd = d.get("tqs_breakdown") or {}
        wu = bd.get("weights_used") or bd.get("weights")
        if isinstance(wu, dict) and "fundamental" in wu:
            weights_seen += 1
            fund_w_by_style[st_key].append(round(float(wu["fundamental"]), 3))

    print("=" * 78)
    print("  STYLE / TAXONOMY INTEGRITY AUDIT   (read-only)")
    print(f"  db={env.get('DB_NAME') or 'tradecommand'}  window=last {args.days}d (since {since})")
    print("=" * 78)
    print(f"  alerts scanned: {n}")

    # [A] distribution
    print("\n[A] stamped trade_style distribution")
    print("-" * 78)
    for k, c in stamped.most_common():
        exp = ""
        if STYLE_WEIGHTS and k in STYLE_WEIGHTS:
            exp = f"  (expected fund-weight {STYLE_WEIGHTS[k]['fundamental']})"
        print(f"  {k:<16}{c:>6}  {pct(c, n):>5}{exp}")

    # [B] missing / unknown
    print("\n[B] missing / unknown trade_style (these fall to the lossy fallback)")
    print("-" * 78)
    flag = "🔴" if missing else "OK"
    print(f"  {missing} / {n}  ({pct(missing, n)})  {flag}")

    # [C] drift
    print("\n[C] DRIFT — stamped != SSOT style_of() recomputed now")
    print("-" * 78)
    if style_of is None:
        print("  (SSOT not importable — skipped)")
    elif not drift:
        print("  none — every stamped style agrees with the SSOT. ✓")
    else:
        dc = Counter((s, a, b) for (s, a, b) in drift)
        print(f"  {len(drift)} alert(s) drift across {len(dc)} setup(s):")
        for (setup, a, b), c in dc.most_common(25):
            print(f"    {setup:<28} stamped={a:<10} ssot={b:<10} x{c}")

    # [D] weight fidelity
    print("\n[D] WEIGHT FIDELITY — fundamental-weight actually applied per stamped style")
    print("-" * 78)
    if weights_seen == 0:
        print("  weights_used NOT persisted in tqs_breakdown — cannot verify applied profile.")
        print("  (Relying on [A]/[C]: if style is stamped right, _get_weights_for_style maps it.)")
    else:
        print(f"  {'stamped style':<16}{'fund-w seen (uniq)':<28}{'expected':<10}{'match'}")
        for k in sorted(fund_w_by_style):
            seen = sorted(set(fund_w_by_style[k]))
            exp = STYLE_WEIGHTS.get(k, {}).get("fundamental") if STYLE_WEIGHTS else None
            match = "OK" if (exp is not None and seen == [round(float(exp), 3)]) else \
                    ("—" if exp is None else "🔴 MISMATCH")
            print(f"  {k:<16}{str(seen):<28}{str(exp):<10}{match}")

    # [E] top setups -> stamped style
    print("\n[E] top setups → stamped style (spot-check the mapping)")
    print("-" * 78)
    top = sorted(setup_to_stamped.items(), key=lambda kv: -sum(kv[1].values()))[:20]
    for setup, ctr in top:
        styles = ", ".join(f"{s}:{c}" for s, c in ctr.most_common())
        print(f"  {setup:<30} {styles}")

    print("\n" + "=" * 78)
    print("  Verdict cues: [B]>0 → fallback exposure; [C] non-empty → stamp/SSOT")
    print("  drift; [D] MISMATCH → wrong weight profile applied despite stamp.")
    print("=" * 78)


if __name__ == "__main__":
    main()
