"""
audit_scalp_timeframe_tagging_v19_34_179.py
===========================================

READ-ONLY audit. Validates the assumption that `check_scalp_decay`
(v19.34.171) relies on: every scalp-style setup must stamp
`bot_trades.timeframe == "scalp"` at entry.

Why this matters
----------------
`position_manager.check_scalp_decay` only flattens trades whose
`timeframe == "scalp"`. That timeframe is set at entry from
`STRATEGY_CONFIG[setup_type]["timeframe"]`, defaulting to INTRADAY.
So ANY scalp-style detector that is missing from STRATEGY_CONFIG, or
mis-tagged, silently falls through to INTRADAY -> the 60-min scalp
time-decay NEVER fires for it (it only closes at EOD 15:45). This
script surfaces exactly those mismatches from the live DB.

Run on the DGX (read-only, no writes):
    DB_NAME=tradecommand python -m backend.scripts.audit_scalp_timeframe_tagging_v19_34_179
    # or
    python backend/scripts/audit_scalp_timeframe_tagging_v19_34_179.py --days 30
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient


def _load_expected_scalp_setups():
    """Pull the SCALP-tagged setup_types from the live STRATEGY_CONFIG.

    Falls back to an empty set (with a warning) if the heavy import
    chain can't load in this environment — the DB-side report is still
    useful on its own."""
    try:
        # Ensure backend/ is importable when run as a bare script.
        here = os.path.dirname(os.path.abspath(__file__))
        backend_dir = os.path.dirname(here)
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)
        from services.trading_bot_service import STRATEGY_CONFIG, TradeTimeframe
        expected = set()
        for setup, cfg in STRATEGY_CONFIG.items():
            tf = cfg.get("timeframe")
            tf_val = tf.value if isinstance(tf, TradeTimeframe) else str(tf)
            if str(tf_val).lower() == "scalp":
                expected.add(setup)
        return expected, None
    except Exception as exc:  # pragma: no cover - env dependent
        return set(), f"{type(exc).__name__}: {exc}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30,
                    help="lookback window over bot_trades (default 30)")
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "tradecommand")
    db = MongoClient(mongo_url)[db_name]

    expected_scalp, import_err = _load_expected_scalp_setups()

    print("=" * 72)
    print("SCALP TIMEFRAME TAGGING AUDIT — v19.34.179")
    print(f"  DB={db_name}  lookback={args.days}d")
    if import_err:
        print(f"  ⚠️  STRATEGY_CONFIG import failed ({import_err}).")
        print("      Expected-scalp set unavailable; showing DB tagging only.")
    else:
        print(f"  STRATEGY_CONFIG SCALP-tagged setups: {len(expected_scalp)}")
    print("=" * 72)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()

    # Aggregate: per setup_type -> Counter of timeframe values seen.
    seen = defaultdict(lambda: defaultdict(int))
    total = 0
    cursor = db["bot_trades"].find(
        {"$or": [{"created_at": {"$gte": cutoff}},
                 {"entry_time": {"$gte": cutoff}}]},
        {"_id": 0, "setup_type": 1, "timeframe": 1},
    )
    for row in cursor:
        st = row.get("setup_type") or "?"
        tf = row.get("timeframe")
        tf = tf.value if hasattr(tf, "value") else str(tf or "?")
        seen[st][str(tf).lower()] += 1
        total += 1

    print(f"\nScanned {total} bot_trades rows across {len(seen)} setup_types.\n")

    # 1) Mismatches — setups STRATEGY_CONFIG calls scalp but DB tagged otherwise.
    mismatches = []
    for st in sorted(expected_scalp):
        tfs = seen.get(st)
        if not tfs:
            continue  # no trades in window — nothing to validate
        non_scalp = {k: v for k, v in tfs.items() if k != "scalp"}
        if non_scalp:
            mismatches.append((st, dict(tfs)))

    print("-" * 72)
    print("1) MISMATCHES — setup is SCALP in config but trades tagged otherwise")
    print("   (these will NOT time-decay; they only close at EOD)")
    print("-" * 72)
    if mismatches:
        for st, tfs in mismatches:
            print(f"   ❌ {st:32s} -> {tfs}")
    else:
        print("   ✅ none — every config-scalp setup with trades is tagged 'scalp'.")

    # 2) Orphans — DB has scalp-tagged trades for setups NOT in the config set.
    print("\n" + "-" * 72)
    print("2) Setups tagged 'scalp' in DB but NOT in STRATEGY_CONFIG scalp set")
    print("   (verify these are intentional scalp detectors)")
    print("-" * 72)
    orphans = [st for st, tfs in seen.items()
               if tfs.get("scalp") and st not in expected_scalp]
    if orphans and not import_err:
        for st in sorted(orphans):
            print(f"   ⚠️  {st:32s} scalp_count={seen[st]['scalp']}")
    elif import_err:
        print("   (skipped — config unavailable)")
    else:
        print("   ✅ none.")

    # 3) Full tagging table for eyeballing.
    print("\n" + "-" * 72)
    print("3) FULL per-setup timeframe distribution")
    print("-" * 72)
    for st in sorted(seen.keys()):
        flag = " [config:scalp]" if st in expected_scalp else ""
        print(f"   {st:32s} {dict(seen[st])}{flag}")

    print("\n" + "=" * 72)
    print("VERDICT:",
          "⚠️  FIX NEEDED — add/correct STRATEGY_CONFIG timeframe for the "
          "mismatched setups above." if mismatches
          else "✅ scalp time-decay tagging is consistent.")
    print("=" * 72)


if __name__ == "__main__":
    main()
