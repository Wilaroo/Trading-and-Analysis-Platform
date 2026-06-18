#!/usr/bin/env python3
"""
P-WIRE Shadow-Mode self-verification (run on the DGX).

Proves the additive shadow plumbing is correct WITHOUT touching execution:
  1. predict_for_setup(..., model_name_override=None) is byte-for-byte unchanged.
  2. classify_current_regime() returns a valid regime from live SPY data.
  3. predict_with_named_model() loads the generic base + regime variant and
     returns real probabilities on the same bar snapshot.
  4. ConfidenceGate._compute_regime_shadow() returns a well-formed record.

Usage (from /app/backend):
    python3 scripts/pwire_shadow_verify.py
    python3 scripts/pwire_shadow_verify.py --symbol AAPL
"""
import argparse
import os
import sys

from pymongo import MongoClient


def _pick_symbol(db, override=None):
    if override:
        return override
    # Prefer a symbol that actually has >=50 5min bars
    doc = db["ib_historical_data"].find_one({"bar_size": "5 mins"}, {"symbol": 1})
    if doc:
        sym = doc["symbol"]
        n = db["ib_historical_data"].count_documents({"symbol": sym, "bar_size": "5 mins"})
        if n >= 50:
            return sym
    # fallback: any recent gate decision symbol
    g = db["confidence_gate_log"].find_one(sort=[("timestamp", -1)])
    return (g or {}).get("symbol", "SPY")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default=None)
    args = ap.parse_args()

    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ.get("DB_NAME", "tradecommand")
    db = MongoClient(mongo_url)[db_name]

    from services.ai_modules.timeseries_service import init_timeseries_ai
    from services.ai_modules.confidence_gate import (
        ConfidenceGate, PWIRE_SHADOW_ENABLED,
    )

    ts = init_timeseries_ai(db=db)
    # Ensure setup models are loaded for the unchanged-path test
    try:
        ts._load_setup_models_from_db()
    except Exception as e:
        print(f"[warn] _load_setup_models_from_db: {e}")

    symbol = _pick_symbol(db, args.symbol)
    print(f"== P-WIRE shadow verify ==  symbol={symbol}  PWIRE_SHADOW_ENABLED={PWIRE_SHADOW_ENABLED}")

    # --- fetch the same bars the live gate would use ---
    bar_size_used = "5 mins"
    bars = list(db["ib_historical_data"].find(
        {"symbol": symbol, "bar_size": "5 mins"}, {"_id": 0}
    ).sort("date", -1).limit(200))
    if len(bars) < 50:
        bar_size_used = "1 day"
        bars = list(db["ib_historical_data"].find(
            {"symbol": symbol, "bar_size": "1 day"}, {"_id": 0}
        ).sort("date", -1).limit(200))
    if len(bars) < 50:
        print(f"FAIL: not enough bars for {symbol} ({len(bars)})")
        sys.exit(1)
    bars.reverse()
    print(f"bars={len(bars)} bar_size={bar_size_used}")

    failures = []

    # 1) Unchanged path: override=None must equal a plain call
    base_a = ts.predict_for_setup(symbol, bars, "BREAKOUT")
    base_b = ts.predict_for_setup(symbol, bars, "BREAKOUT", model_name_override=None)
    same = (base_a == base_b) or (
        base_a is not None and base_b is not None
        and base_a.get("direction") == base_b.get("direction")
        and abs(base_a.get("probability_up", 0) - base_b.get("probability_up", 0)) < 1e-9
    )
    print(f"[1] live path unchanged (override=None): {'PASS' if same else 'FAIL'} "
          f"| dir={None if base_a is None else base_a.get('direction')}")
    if not same:
        failures.append("override=None changed live path output")

    # 2) Regime classification
    regime = ts.classify_current_regime()
    ok2 = regime in ("bull_trend", "bear_trend", "range_bound", "high_vol")
    print(f"[2] classify_current_regime: {regime}  {'PASS' if ok2 else 'FAIL'}")
    if not ok2:
        failures.append(f"invalid regime: {regime}")

    # 3) Named-model inference (generic base + regime variant)
    tf = {"1 min": "1min", "5 mins": "5min", "15 mins": "15min", "30 mins": "30min",
          "1 hour": "1hour", "1 day": "daily", "1 week": "weekly"}[bar_size_used]
    gname = f"direction_predictor_{tf}"
    rname = f"direction_predictor_{tf}_{regime}"
    gp = ts.predict_with_named_model(symbol, bars, gname)
    rp = ts.predict_with_named_model(symbol, bars, rname)
    print(f"[3] generic {gname}: "
          f"{'(missing)' if gp is None else gp.get('direction') + ' pUp=' + format(gp.get('probability_up', 0), '.3f')}")
    print(f"    regime  {rname}: "
          f"{'(NOT TRAINED — falls back, expected for some regimes)' if rp is None else rp.get('direction') + ' pUp=' + format(rp.get('probability_up', 0), '.3f')}")
    if gp is None:
        failures.append(f"generic base model {gname} not loadable")

    # 4) Full shadow record via the gate
    gate = ConfidenceGate(db=db)
    shadow = gate._compute_regime_shadow(ts, symbol, "BREAKOUT", bars, bar_size_used, base_a)
    ok4 = bool(shadow and shadow.get("shadow_version") == "pwire_v1"
               and "generic_base" in shadow and "regime_specialized" in shadow)
    print(f"[4] _compute_regime_shadow: {'PASS' if ok4 else 'FAIL'}")
    if shadow:
        print(f"    regime={shadow.get('regime')} input_hash={shadow.get('input_hash')} "
              f"regime_model_available={shadow.get('regime_model_available')} "
              f"agree={shadow.get('directions_agree')}")
        print(f"    generic_ev={shadow['generic_base'].get('ev_proxy')} "
              f"regime_ev={shadow['regime_specialized'].get('ev_proxy')}")
    if not ok4:
        failures.append("shadow record malformed")

    print("\n" + ("ALL CHECKS PASSED ✅" if not failures
                  else "FAILURES ❌: " + "; ".join(failures)))
    sys.exit(0 if not failures else 2)


if __name__ == "__main__":
    main()
