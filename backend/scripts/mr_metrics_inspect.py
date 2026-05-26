#!/usr/bin/env python3
"""mr_metrics_inspect.py — v19.34.157 (P3-C)

Operator-side inspection of the mean-reversion metrics service.
Prints the current MR metrics for a symbol (or for a comma-separated
list of symbols) at one or more bar sizes. READ-ONLY.

Usage (on DGX):
    PYTHONPATH=backend python3 backend/scripts/mr_metrics_inspect.py AAPL
    PYTHONPATH=backend python3 backend/scripts/mr_metrics_inspect.py AAPL,MSFT,TSLA
    PYTHONPATH=backend python3 backend/scripts/mr_metrics_inspect.py AAPL --bar-size "1 min"
    PYTHONPATH=backend python3 backend/scripts/mr_metrics_inspect.py AAPL --fresh   # bypass cache
    PYTHONPATH=backend python3 backend/scripts/mr_metrics_inspect.py AAPL --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BACKEND_ROOT, ".env"))
except Exception:
    pass


def _connect_db():
    from pymongo import MongoClient
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not (mongo_url and db_name):
        print("[FATAL] MONGO_URL / DB_NAME not set", file=sys.stderr)
        sys.exit(2)
    return MongoClient(mongo_url).get_database(db_name)


def _emoji(regime: str) -> str:
    return {"MR_STRONG": "🌀", "MR_WEAK": "🌊", "NEUTRAL": "·",
            "TRENDING": "🚀"}.get(regime, "?")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("symbols", help="Comma-separated symbol(s)")
    ap.add_argument("--bar-size", default="5 mins",
                    choices=["1 min", "5 mins", "15 mins", "1 hour", "1 day"],
                    help="Bar size to compute on (default: 5 mins)")
    ap.add_argument("--lookback-bars", type=int, default=500,
                    help="Bars of history to use (default 500)")
    ap.add_argument("--fresh", action="store_true",
                    help="Bypass the cache, recompute from scratch")
    ap.add_argument("--json", action="store_true",
                    help="Raw JSON instead of pretty table")
    args = ap.parse_args()

    db = _connect_db()
    from services.mean_reversion_metrics import (
        compute_mr_metrics, classify_setup_family, get_mr_multiplier,
    )

    syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    results = []
    for sym in syms:
        m = compute_mr_metrics(
            db, sym, bar_size=args.bar_size,
            lookback_bars=args.lookback_bars,
            use_cache=(not args.fresh),
        )
        results.append(m)

    if args.json:
        print(json.dumps(results, indent=2, default=str))
        return 0

    print("─" * 90)
    print(f"  MEAN-REVERSION METRICS  (bar_size: {args.bar_size}, "
          f"lookback: {args.lookback_bars} bars, "
          f"{'fresh' if args.fresh else 'cached'})")
    print("─" * 90)
    print(f"  {'symbol':<8} {'regime':<11} {'hurst':>6} {'t½ (bars)':>10} "
          f"{'z':>6} {'vwap_z':>7} {'score':>6}  reason")
    print("─" * 90)
    for m in results:
        h = m.get("hurst")
        hl = m.get("half_life_bars")
        z = m.get("current_z")
        vz = m.get("vwap_z")
        regime = m.get("regime_tag", "?")
        print(f"  {_emoji(regime)} {m['symbol']:<6} {regime:<11} "
              f"{f'{h:.2f}' if isinstance(h, (int, float)) else '   - ':>6} "
              f"{f'{hl:.1f}' if isinstance(hl, (int, float)) else '   -  ':>10} "
              f"{f'{z:+.2f}' if isinstance(z, (int, float)) else '   - ':>6} "
              f"{f'{vz:+.2f}' if isinstance(vz, (int, float)) else '    - ':>7} "
              f"{m.get('reversion_score', '-'): >6}  {m.get('reason', '')}")
    print("─" * 90)
    print()
    # Show how each setup family would be sized in the dominant regime.
    print("  MULTIPLIERS BY SETUP FAMILY (first symbol's regime):")
    if results:
        for fam_demo_setup in ("mean_reversion", "momentum_continuation",
                                "breakout_scalp", "unknown_thing"):
            mult, reason = get_mr_multiplier(results[0], fam_demo_setup)
            print(f"    {fam_demo_setup:<25} → {mult:.2f}×  ({reason})")
    print("─" * 90)
    return 0


if __name__ == "__main__":
    sys.exit(main())
