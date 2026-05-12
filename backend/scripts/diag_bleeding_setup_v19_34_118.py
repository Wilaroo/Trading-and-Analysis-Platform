"""
diag_bleeding_setup_v19_34_118.py
─────────────────────────────────────────────────────────────────────────────
Diagnostic for bleeding positions whose IB OCA STP leg didn't fire.

Run on the DGX where MongoDB has the live bot_trades:
    cd ~/Trading-and-Analysis-Platform/backend
    MONGO_URL=mongodb://localhost:27017 DB_NAME=tradecommand \
        python3 scripts/diag_bleeding_setup_v19_34_118.py ONON RJF MTB CCJ

For each symbol it prints:
  • most-recent OPEN bot_trades doc (setup_type, trade_style, direction,
    entry_price, stop_price, target_prices, status, order_pipeline,
    parent_oca_group, ib_order_ids)
  • whether `setup_type` resolves into SETUP_MULTIPLIERS (post-v118 patch)
  • last 3 bracket_lifecycle_events for this trade (so we can see WHY
    the STP leg dropped — never attached, cancelled, orphaned)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from pprint import pprint

HERE = Path(__file__).resolve()
BACKEND_DIR = HERE.parent.parent
sys.path.insert(0, str(BACKEND_DIR))


def _resolve_mult(setup_type: str) -> str:
    try:
        from services.opportunity_evaluator import OpportunityEvaluator
    except Exception as exc:  # pragma: no cover
        return f"<import failed: {exc}>"
    # Use a dummy bot-shape that exposes risk_params.base_atr_multiplier.
    class _DummyRisk:
        base_atr_multiplier = 1.5
        min_atr_multiplier = 1.0
        max_atr_multiplier = 3.0

    class _DummyBot:
        risk_params = _DummyRisk()

    mult, is_scalp, kind = OpportunityEvaluator._resolve_atr_multiplier(setup_type, _DummyBot())
    return f"multiplier={mult} scalp={is_scalp} resolution={kind}"


def main(symbols):
    from pymongo import MongoClient

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "tradecommand")
    if not mongo_url:
        print("ERROR: MONGO_URL not set. Run with MONGO_URL=mongodb://localhost:27017 ...")
        sys.exit(1)

    client = MongoClient(mongo_url)
    db = client[db_name]

    symbols = [s.upper() for s in symbols]
    print(f"\n=== Diagnosing bleeding positions for: {symbols} ===\n")

    for sym in symbols:
        print(f"\n─── {sym} " + "─" * 60)
        trade = db.bot_trades.find_one(
            {"symbol": sym, "status": {"$in": ["open", "OPEN", "partial", "filled"]}},
            {"_id": 0},
            sort=[("entered_at", -1)],
        )
        if not trade:
            trade = db.bot_trades.find_one(
                {"symbol": sym}, {"_id": 0}, sort=[("entered_at", -1)]
            )
            if not trade:
                print(f"  no bot_trades doc found for {sym}")
                continue
            print(f"  (no open trade; showing most-recent)")

        setup_type = trade.get("setup_type") or "<MISSING>"
        print(f"  setup_type       : {setup_type}")
        print(f"  trade_style      : {trade.get('trade_style')}")
        print(f"  direction        : {trade.get('direction')}")
        print(f"  status           : {trade.get('status')}")
        print(f"  entry_price      : {trade.get('entry_price')}")
        print(f"  stop_price       : {trade.get('stop_price')}")
        print(f"  target_prices    : {trade.get('target_prices')}")
        print(f"  shares           : {trade.get('shares')}")
        print(f"  entered_at       : {trade.get('entered_at')}")
        print(f"  entered_by       : {trade.get('entered_by')}")
        print(f"  parent_oca_group : {trade.get('parent_oca_group')}")
        print(f"  ib_order_ids     : {trade.get('ib_order_ids')}")
        print(f"  bracket_status   : {trade.get('bracket_status')}")
        op = trade.get("order_pipeline") or {}
        if isinstance(op, dict):
            print(f"  order_pipeline   :")
            for k, v in op.items():
                print(f"     {k}: {v}")

        print(f"  v118 multiplier  : {_resolve_mult(setup_type)}")

        # bracket lifecycle events
        tid = trade.get("id") or trade.get("trade_id")
        if tid:
            evts = list(
                db.bracket_lifecycle_events.find(
                    {"trade_id": tid}, {"_id": 0}, sort=[("ts", -1)]
                ).limit(5)
            )
            if evts:
                print(f"  bracket_lifecycle_events (latest 5):")
                for e in evts:
                    print(
                        f"    [{e.get('ts')}] {e.get('event')} "
                        f"leg={e.get('leg')} status={e.get('status')} "
                        f"reason={e.get('reason')}"
                    )
            else:
                print(f"  bracket_lifecycle_events : (none)")


if __name__ == "__main__":
    syms = sys.argv[1:] or ["ONON", "RJF", "MTB", "CCJ"]
    main(syms)
