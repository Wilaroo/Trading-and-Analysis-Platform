#!/usr/bin/env python3
"""
v369 VERIFY — confirm the missed-movers fix landed (READ-ONLY, nothing written).

Two checks:
 1) SOURCE MARKERS — the live enhanced_scanner.py + ib_historical_collector.py
    carry the v369 edits (rvol-unmeasured defer + ATR ceiling waive).
 2) trade_drops DISTRIBUTION — over the last --days window:
      - all drops by gate
      - universal_liquidity_gate drops by context.check
      - scalp_rvol drops split by fail_closed True/False, with per-drop timestamps
        so you can see whether NEW fail_closed=True drops are still being created
        AFTER the deploy time (post-deploy they should stop accruing)
      - watch-symbol (SNDK/MRVL/SPCX/TSLA/SMCI ...) recent drops: gate + reason + ts

Usage (repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v369_verify.py --days 2
  # optional: pass the deploy time to split pre/post drops
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v369_verify.py --days 2 --deploy-iso 2026-06-18T16:41:00Z
"""
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

WATCH = ["SNDK", "MRVL", "SPCX", "TSLA", "SMCI", "HON", "SPY", "QQQ"]


def _arg(flag, default, cast=str):
    if flag in sys.argv:
        try:
            return cast(sys.argv[sys.argv.index(flag) + 1])
        except Exception:
            return default
    return default


def _load_db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    from pymongo import MongoClient
    return MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=20000)[env["DB_NAME"]]


def _ts_of(doc):
    """Best-effort epoch seconds from any plausible timestamp field."""
    for k in ("ts", "created_at", "timestamp", "dropped_at", "at", "time"):
        v = doc.get(k)
        if v in (None, ""):
            continue
        if isinstance(v, (int, float)):
            return float(v) if v < 1e12 else float(v) / 1000.0
        if isinstance(v, datetime):
            return v.replace(tzinfo=v.tzinfo or timezone.utc).timestamp()
        try:
            s = str(v).replace("Z", "+00:00")
            return datetime.fromisoformat(s).timestamp()
        except Exception:
            continue
    return None


def _iso(ep):
    if ep is None:
        return "?"
    return datetime.fromtimestamp(ep, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def _ctx(doc):
    c = doc.get("context")
    return c if isinstance(c, dict) else {}


def section(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


def check_markers():
    section("1) SOURCE MARKERS (is v369 live in the code?)")
    checks = {
        "backend/services/enhanced_scanner.py": [
            ("rvol defer guard", "_rvol_fail_closed"),
            ("measured-rvol-only block", "elif rvol > 0 and rvol < self._scalp_min_rvol:"),
            ("env knob", "SCALP_RVOL_FAIL_CLOSED"),
        ],
        "backend/services/ib_historical_collector.py": [
            ("ceiling-waive flag", "_waive_ceiling_liquid"),
            ("liquidity gate", "_highly_liquid"),
            ("env knob", "ATR_CEILING_WAIVE_LIQUID"),
        ],
    }
    all_ok = True
    for fp, markers in checks.items():
        try:
            src = open(fp).read()
        except Exception as e:
            print(f"  ✗ cannot read {fp}: {e}")
            all_ok = False
            continue
        for label, needle in markers:
            ok = needle in src
            all_ok = all_ok and ok
            print(f"  {'✓' if ok else '✗'} {fp.split('/')[-1]:<28} {label}")
    print(f"\n  => v369 markers {'ALL PRESENT ✅' if all_ok else 'MISSING ❌ (patch not applied?)'}")
    return all_ok


def analyze_drops(db, days, deploy_ep):
    section(f"2) trade_drops DISTRIBUTION (last {days}d)")
    since = datetime.now(timezone.utc).timestamp() - days * 86400
    try:
        rows = list(db.trade_drops.find({}, {"_id": 0}))
    except Exception as e:
        print(f"  cannot read trade_drops: {e}")
        return
    rows = [r for r in rows if (_ts_of(r) or since) >= since]
    print(f"  total drops in window: {len(rows)}")
    if not rows:
        print("  (no drops yet — pusher just booted? re-run during RTH with quote flow)")
        return

    by_gate = Counter(str(r.get("gate", "?")) for r in rows)
    print("\n  -- by gate --")
    for g, n in by_gate.most_common():
        print(f"     {n:>6}  {g}")

    ulg = [r for r in rows if str(r.get("gate")) == "universal_liquidity_gate"]
    by_check = Counter(str(_ctx(r).get("check", "?")) for r in ulg)
    print(f"\n  -- universal_liquidity_gate ({len(ulg)}) by context.check --")
    for c, n in by_check.most_common():
        print(f"     {n:>6}  {c}")

    # scalp_rvol split by fail_closed; show timestamps (post-deploy = should stop)
    rvol_drops = [r for r in ulg if _ctx(r).get("check") == "scalp_rvol"]
    fc_true = [r for r in rvol_drops if _ctx(r).get("fail_closed") is True]
    fc_false = [r for r in rvol_drops if _ctx(r).get("fail_closed") is not True]
    print(f"\n  -- scalp_rvol drops: {len(rvol_drops)} "
          f"(fail_closed=True {len(fc_true)} | measured-low {len(fc_false)}) --")
    if deploy_ep:
        post = [r for r in fc_true if (_ts_of(r) or 0) >= deploy_ep]
        print(f"     fail_closed=True AFTER deploy ({_iso(deploy_ep)}): {len(post)}"
              f"   <-- v369 SUCCESS = 0 (no new unmeasured-rvol fail-closes)")
    print("     most-recent fail_closed=True (unmeasured-rvol drops):")
    for r in sorted(fc_true, key=lambda x: _ts_of(x) or 0, reverse=True)[:8]:
        print(f"       {_iso(_ts_of(r)):<22} {str(r.get('symbol','?')):<6} "
              f"{str(r.get('setup_type','?'))}")


def watch_symbols(db, days):
    section(f"3) WATCH-SYMBOL recent drops (last {days}d)")
    since = datetime.now(timezone.utc).timestamp() - days * 86400
    rows = list(db.trade_drops.find(
        {"symbol": {"$in": WATCH}}, {"_id": 0}))
    rows = [r for r in rows if (_ts_of(r) or since) >= since]
    bysym = defaultdict(list)
    for r in rows:
        bysym[str(r.get("symbol"))].append(r)
    for sym in WATCH:
        rs = sorted(bysym.get(sym, []), key=lambda x: _ts_of(x) or 0, reverse=True)
        if not rs:
            print(f"  {sym:<6} no drops (passed gate or no alerts) ✅")
            continue
        latest = rs[0]
        print(f"  {sym:<6} {len(rs)} drop(s); latest {_iso(_ts_of(latest))} "
              f"gate={latest.get('gate')} :: {str(latest.get('reason'))[:90]}")


def main():
    days = _arg("--days", 2, float)
    deploy_iso = _arg("--deploy-iso", None)
    deploy_ep = None
    if deploy_iso:
        try:
            deploy_ep = datetime.fromisoformat(
                deploy_iso.replace("Z", "+00:00")).timestamp()
        except Exception:
            print(f"(could not parse --deploy-iso {deploy_iso})")
    ok = check_markers()
    db = _load_db()
    analyze_drops(db, days, deploy_ep)
    watch_symbols(db, days)
    section("DONE (read-only)")
    print("  v369 verified when: markers present + new scalp_rvol fail_closed=True")
    print("  drops stop accruing post-deploy + watch symbols clear the gate.")


if __name__ == "__main__":
    main()
