#!/usr/bin/env python3
"""
v378b — RAW smart_filter_skip drop inspector (READ-ONLY).

Disambiguates WHY a symbol was skipped: dumps the full trade_drops docs
(exact setup_type, full reason, context incl. win_rate/sample), resolves the
base_setup the filter would key on, and prints BOTH the Mongo strategy_stats
row AND the scanner's LIVE in-memory stats (via the running API) for that base
so we can see if Mongo and in-memory diverge.

Usage (repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v378b_sndk_skip_raw.py --symbol SNDK
"""
import json
import sys
import urllib.request
from datetime import datetime, timezone


def _arg(flag, default):
    if flag in sys.argv:
        try:
            return sys.argv[sys.argv.index(flag) + 1]
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


def _base(st):
    return str(st or "").split("_long")[0].split("_short")[0]


def _ts(d):
    for k in ("ts", "created_at", "timestamp", "dropped_at", "at"):
        v = d.get(k)
        if v in (None, ""):
            continue
        try:
            if isinstance(v, (int, float)):
                v = v if v < 1e12 else v / 1000.0
                return datetime.fromtimestamp(v, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
            return str(v)
        except Exception:
            return str(v)
    return "?"


def main():
    sym = _arg("--symbol", "SNDK").upper()
    db = _load_db()
    rows = list(db.trade_drops.find(
        {"symbol": sym, "gate": "smart_filter_skip"}, {"_id": 0}))
    rows.sort(key=lambda d: str(d.get("ts") or d.get("created_at") or ""), reverse=True)
    print(f"=== {sym} smart_filter_skip drops: {len(rows)} ===")
    bases = set()
    for r in rows[:8]:
        st = r.get("setup_type")
        bases.add(_base(st))
        print(f"\n  {_ts(r)}  setup_type={st!r}  base={_base(st)!r}")
        print(f"    reason: {r.get('reason')}")
        ctx = r.get("context")
        if isinstance(ctx, dict):
            keep = {k: ctx[k] for k in (
                "win_rate", "sample_size", "wins", "losses", "expected_value",
                "quality_score", "tqs", "action", "tqs_required") if k in ctx}
            print(f"    context: {keep if keep else ctx}")

    print("\n=== Mongo strategy_stats for involved base(s) ===")
    for b in sorted(bases):
        d = db.strategy_stats.find_one({"setup_type": b}, {"_id": 0})
        if d:
            print(f"  {b:<24} win_rate={d.get('win_rate')} "
                  f"n={d.get('alerts_triggered') or d.get('total_alerts')} "
                  f"won={d.get('alerts_won')} lost={d.get('alerts_lost')} "
                  f"ev={d.get('expected_value_r', d.get('avg_r'))}")
        else:
            print(f"  {b:<24} (no strategy_stats row)")

    print("\n=== LIVE in-memory scanner stats (the EXACT view smart_filter reads) ===")
    for b in sorted(bases):
        try:
            url = f"http://localhost:8001/api/trading-bot/smart-filter/strategy-stats/{b}"
            with urllib.request.urlopen(url, timeout=8) as resp:
                data = json.loads(resp.read().decode())
            print(f"  {b}: win_rate={data.get('win_rate')} sample={data.get('sample_size')} "
                  f"wins={data.get('wins')} losses={data.get('losses')} "
                  f"ev={data.get('expected_value')} avail={data.get('available')}")
        except Exception as e:
            print(f"  {b}: (API miss: {e})")
    print("\nDONE (read-only). If Mongo win_rate is healthy but the drop context win_rate")
    print("is low, the scanner's IN-MEMORY _strategy_stats is stale (refresh path bug).")


if __name__ == "__main__":
    main()
