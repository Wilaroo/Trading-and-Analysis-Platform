#!/usr/bin/env python3
"""
diag_pwin_distribution.py — settle the 0% take-rate hypothesis OFFLINE.

Samples the ensemble meta-labeler's actual p_win across liquid symbols × setups
and reports the distribution + how the gate's hard veto (p_win < 0.50) behaves
vs a breakeven-relative threshold (2:1 barrier breakeven = SL/(PT+SL) = 0.333).

Run from repo root:
    source .venv/bin/activate && python backend/scripts/diag_pwin_distribution.py

Interpretation:
  • Mostly has_prediction=False  -> meta-labeler is UNAVAILABLE; the 0% take-rate
    is NOT the p_win veto — look at mode threshold / regime suppression / score.
  • p_win clusters BELOW 0.50    -> the 0.50 gate is force-skipping +EV trades
    (confirms the win-rate-vs-expectancy bug). Fix = breakeven-relative threshold.
  • p_win clusters AROUND 0.50   -> class-weighting re-centered it; choke is
    elsewhere (additive score / mode / suppression).
"""
import os
import sys
from pathlib import Path

import numpy as np

# allow `import services.*` when run from repo root
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, "backend")

from pymongo import MongoClient


def load_db():
    env = {}
    for line in Path("backend/.env").read_text().splitlines():
        s = line.strip()
        if "=" in s and not s.startswith("#"):
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return MongoClient(env["MONGO_URL"])[env.get("DB_NAME", "tradecommand")]


SYMBOLS = ["AAPL", "MSFT", "NVDA", "AMD", "TSLA", "AMZN", "META", "GOOGL",
           "NFLX", "AVGO", "JPM", "XOM", "BA", "CAT", "WMT", "SPY", "QQQ", "IWM"]


def main():
    db = load_db()
    from services.ai_modules.ensemble_live_inference import predict_meta_label_p_win
    try:
        from services.ai_modules.ensemble_model import ENSEMBLE_MODEL_CONFIGS
        setups = list(ENSEMBLE_MODEL_CONFIGS.keys())
    except Exception:
        setups = ["BREAKOUT", "REVERSAL", "MEAN_REVERSION", "MOMENTUM", "TREND_PULLBACK"]

    # breakeven win-rate for the live 2:1 barrier
    try:
        from services.ai_modules.triple_barrier_config import DEFAULT_PT, DEFAULT_SL
        pt, sl = float(DEFAULT_PT), float(DEFAULT_SL)
    except Exception:
        pt, sl = 2.0, 1.0
    breakeven = sl / (pt + sl)

    print(f"Barrier PT={pt} SL={sl}  ->  breakeven win-rate = {breakeven:.3f}")
    print(f"Probing {len(SYMBOLS)} symbols × {len(setups)} setups = {len(SYMBOLS)*len(setups)} calls...\n")

    pwins, rows, misses = [], [], {}
    for sym in SYMBOLS:
        for st in setups:
            try:
                r = predict_meta_label_p_win(db, sym, st)
            except Exception as e:
                misses[f"exception:{type(e).__name__}"] = misses.get(f"exception:{type(e).__name__}", 0) + 1
                continue
            if r.get("has_prediction"):
                pw = float(r["p_win"])
                pwins.append(pw)
                rows.append((sym, st, pw))
            else:
                why = r.get("reason_if_missing", "unknown")
                misses[why] = misses.get(why, 0) + 1

    total = len(pwins) + sum(misses.values())
    print(f"=== RESULT: {len(pwins)} predictions / {total} calls ===\n")

    if misses:
        print("MISS reasons (no p_win produced):")
        for k, v in sorted(misses.items(), key=lambda x: -x[1]):
            print(f"  {v:>4}  {k}")
        print()

    if not pwins:
        print("⚠️  Zero p_win predictions — the meta-labeler is UNAVAILABLE for these "
              "symbols/setups. The 0% take-rate is NOT the p_win veto; check mode "
              "threshold / regime suppression / additive score starvation.")
        return

    pw = np.array(pwins)
    print(f"p_win distribution: min={pw.min():.3f}  p25={np.percentile(pw,25):.3f}  "
          f"median={np.median(pw):.3f}  p75={np.percentile(pw,75):.3f}  max={pw.max():.3f}")
    print(f"force-SKIP @0.50 (current gate): {(pw < 0.50).mean()*100:5.1f}%  "
          f"({(pw < 0.50).sum()}/{len(pw)})")
    print(f"would-SKIP @breakeven {breakeven:.3f}: {(pw < breakeven).mean()*100:5.1f}%  "
          f"({(pw < breakeven).sum()}/{len(pw)})")
    print(f"would-SKIP @breakeven+margin {breakeven*1.05:.3f}: {(pw < breakeven*1.05).mean()*100:5.1f}%")
    tradeable_now = int((pw >= 0.50).sum())
    tradeable_fixed = int((pw >= breakeven * 1.05).sum())
    print(f"\nTRADEABLE setups:  current gate(@0.50) = {tradeable_now}   |   "
          f"breakeven gate(@{breakeven*1.05:.3f}) = {tradeable_fixed}")
    print("\nSample (symbol | setup | p_win | verdict@0.50 | verdict@breakeven):")
    for sym, st, pw_ in sorted(rows, key=lambda x: -x[2])[:20]:
        v50 = "SKIP" if pw_ < 0.50 else "TRADE"
        vbe = "SKIP" if pw_ < breakeven * 1.05 else "TRADE"
        print(f"  {sym:<5} {st:<16} {pw_:.3f}   {v50:<5}   {vbe}")


if __name__ == "__main__":
    main()
