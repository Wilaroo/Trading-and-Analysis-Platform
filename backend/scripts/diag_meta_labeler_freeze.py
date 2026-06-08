#!/usr/bin/env python3
"""
diag_meta_labeler_freeze.py  (READ-ONLY)
========================================
WHY does the bot take ~zero trades?

The hard freeze lives in ensemble_live_inference.bet_size_multiplier_from_p_win:
    p_win < 0.50  ->  0.0  (force SKIP)

But predict_meta_label_p_win() has ~8 early-exit `miss()` points: if ANY required
sub-model (directional per-timeframe, setup 1-day, or the ensemble meta-labeler)
is untrained/unloadable, it returns has_prediction=False and the setup never even
gets a p_win. With the DL/training pipeline partially broken, that is a likely
freeze cause that has nothing to do with the 0.50 cut.

This script distinguishes the two causes empirically:

  PART 1 — REGISTRY: which meta-labelers + directional sub-models actually exist,
           their accuracy, and (for meta-labelers) the WIN base rate if stored.
  PART 2 — LIVE RUN: run predict_meta_label_p_win across a sample of liquid symbols
           for every ensemble setup, then tally:
             - has_prediction True vs False  (+ histogram of miss reasons)
             - p_win histogram for the successful ones
             - how many clear 0.50 (would TRADE) vs land in 0.33-0.50
               (positive-EV-but-skipped band for a 2:1 reward:risk)

Writes NOTHING. Safe anytime.

Usage:
  cd ~/Trading-and-Analysis-Platform
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_meta_labeler_freeze.py
"""
import os
from collections import Counter

for _l in open("backend/.env"):
    _l = _l.strip()
    if "=" in _l and not _l.startswith("#"):
        k, v = _l.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from pymongo import MongoClient  # noqa: E402

db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

from services.ai_modules.ensemble_model import (  # noqa: E402
    ENSEMBLE_MODEL_CONFIGS, STACKED_TIMEFRAMES,
)
from services.ai_modules.ensemble_live_inference import predict_meta_label_p_win  # noqa: E402

# Mirror of the in-function map (defined inside predict_meta_label_p_win)
DIRECTIONAL_MODEL_NAMES = {
    "1 min": "direction_predictor_1min",
    "5 mins": "direction_predictor_5min",
    "15 mins": "direction_predictor_15min",
    "30 mins": "direction_predictor_30min",
    "1 hour": "direction_predictor_1hour",
    "1 day": "direction_predictor_daily",
    "1 week": "direction_predictor_weekly",
}

print("=" * 80)
print("PART 1 — MODEL REGISTRY  (timeseries_models)")
print("=" * 80)

# Directional sub-models used by the stacked ensemble
print("\nDirectional sub-models (needed by EVERY meta-labeler):")
for tf in STACKED_TIMEFRAMES:
    nm = DIRECTIONAL_MODEL_NAMES.get(tf, f"direction_predictor_{tf.replace(' ', '_')}")
    doc = db.timeseries_models.find_one({"name": nm}, {"_id": 0, "metrics": 1, "label_scheme": 1, "updated_at": 1})
    if doc:
        acc = (doc.get("metrics") or {}).get("accuracy")
        print(f"  ✅ {nm:<30} acc={acc}  scheme={doc.get('label_scheme')}  {str(doc.get('updated_at'))[:19]}")
    else:
        print(f"  ❌ {nm:<30} NOT TRAINED")

print("\nEnsemble meta-labelers + their setup 1-day sub-models:")
for key, cfg in ENSEMBLE_MODEL_CONFIGS.items():
    nm = cfg["model_name"]
    doc = db.timeseries_models.find_one(
        {"name": nm}, {"_id": 0, "label_scheme": 1, "metrics": 1, "updated_at": 1})
    if not doc:
        print(f"  ❌ {key:<20} {nm:<22} NOT TRAINED")
        continue
    m = doc.get("metrics") or {}
    scheme = doc.get("label_scheme")
    ok = "✅" if scheme == "meta_label_binary" else "⚠️ "
    base = m.get("win_base_rate") or m.get("positive_rate") or m.get("base_rate")
    print(f"  {ok} {key:<20} {nm:<22} acc={m.get('accuracy')}  scheme={scheme}"
          f"  win_base_rate={base}  {str(doc.get('updated_at'))[:19]}")

print("\n" + "=" * 80)
print("PART 2 — LIVE p_win RUN across sample symbols")
print("=" * 80)

# Sample liquid symbols that have daily bars
syms = [d["_id"] for d in db.ib_historical_data.aggregate([
    {"$match": {"bar_size": "1 day"}},
    {"$group": {"_id": "$symbol", "c": {"$sum": 1}}},
    {"$match": {"c": {"$gte": 200}}},
    {"$sort": {"c": -1}},
    {"$limit": 40},
], allowDiskUse=True)]
print(f"Sampling {len(syms)} liquid symbols × {len(ENSEMBLE_MODEL_CONFIGS)} setups\n")

miss_reasons = Counter()
n_pred = 0
n_total = 0
p_wins = []
would_trade = 0          # p_win >= 0.50  (current rule trades)
pos_ev_skipped = 0       # 0.333 <= p_win < 0.50  (positive EV @ 2:1 but force-skipped)

for setup_key in ENSEMBLE_MODEL_CONFIGS.keys():
    for sym in syms:
        n_total += 1
        try:
            r = predict_meta_label_p_win(db, sym, setup_key)
        except Exception as e:
            miss_reasons[f"exception:{type(e).__name__}"] += 1
            continue
        if not r.get("has_prediction"):
            miss_reasons[r.get("reason_if_missing", "unknown")] += 1
            continue
        n_pred += 1
        pw = r["p_win"]
        p_wins.append(pw)
        if pw >= 0.50:
            would_trade += 1
        elif pw >= 1.0 / 3.0:
            pos_ev_skipped += 1

print(f"Total (symbol×setup) attempts : {n_total}")
print(f"  has_prediction = TRUE       : {n_pred}")
print(f"  has_prediction = FALSE      : {n_total - n_pred}")
if miss_reasons:
    print("\n  MISS-REASON histogram (why no prediction):")
    for reason, cnt in miss_reasons.most_common():
        print(f"    {cnt:>5}  {reason}")

if p_wins:
    import statistics
    p_wins.sort()
    print(f"\n  p_win distribution (n={len(p_wins)}):")
    print(f"    min={p_wins[0]:.3f}  p25={p_wins[len(p_wins)//4]:.3f}  "
          f"median={statistics.median(p_wins):.3f}  "
          f"p75={p_wins[3*len(p_wins)//4]:.3f}  max={p_wins[-1]:.3f}")
    print(f"    mean={statistics.mean(p_wins):.3f}")
    print(f"\n  WOULD TRADE now (p_win >= 0.50)          : {would_trade}  "
          f"({100.0*would_trade/len(p_wins):.1f}% of predictions)")
    print(f"  Positive-EV-but-SKIPPED (0.333<=p_win<0.50): {pos_ev_skipped}  "
          f"({100.0*pos_ev_skipped/len(p_wins):.1f}% of predictions)")
    print("  ^ these would be profitable at 2:1 reward:risk (breakeven p_win=0.333)")
    print("    but the flat 0.50 cut force-skips them.")

print("\n" + "=" * 80)
print("DIAGNOSIS HINTS")
print("=" * 80)
if n_pred == 0:
    print("  ➜ FREEZE CAUSE = MISSING MODELS. The meta-labeler chain never produces a")
    print("    prediction (see miss-reason histogram). Fixing the 0.50 cut would do")
    print("    NOTHING — you must train the missing sub-models/meta-labelers first.")
elif would_trade == 0 and pos_ev_skipped > 0:
    print("  ➜ FREEZE CAUSE = 0.50 CUT. Models work and produce p_win, but none reach")
    print("    0.50 while many sit in the positive-EV 0.333-0.50 band. An EV/breakeven-")
    print("    aware SKIP threshold would unfreeze profitable trades.")
elif would_trade > 0:
    print(f"  ➜ Models DO clear 0.50 on {would_trade} setups — the bot SHOULD be trading")
    print("    these. If it still isn't, the block is downstream (scanner filters, risk")
    print("    gate, or market hours), not the meta-labeler.")
print("\nDONE — paste this whole block back.")
