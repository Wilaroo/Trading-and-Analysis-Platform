#!/usr/bin/env python3
"""
diag_tft_real_baseline.py  (READ-ONLY)
======================================
Answers the ONE question the current dl_models record can't:

    Is the TFT's 46.8% accuracy a COLLAPSE, or a genuine EDGE?

For a 3-class triple-barrier target, "random" is ~33%, NOT 50%. The stored
TFT record has majority_baseline=None, so nobody can tell. This script
reconstructs the TFT's EXACT daily triple-barrier labels (1-day bars,
features start at bar 20, 5-bar horizon — identical to
temporal_fusion_transformer.py lines 343-390) and reports:

  1. The REAL class distribution (down / flat / up) the TFT trained on.
  2. The majority-class baseline (= "always predict the biggest class").
  3. Verdict: 46.8% vs that baseline  ->  COLLAPSED or HAS-EDGE.
  4. What the SWEPT generic-daily config (get_tb_config) WOULD produce, so you
     can decide whether switching the TFT to the swept config is worth a retrain.

It writes NOTHING. Safe to run anytime.

Usage:
  cd ~/Trading-and-Analysis-Platform
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_tft_real_baseline.py
"""
import os
import numpy as np
from collections import Counter

for _l in open("backend/.env"):
    _l = _l.strip()
    if "=" in _l and not _l.startswith("#"):
        k, v = _l.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from pymongo import MongoClient  # noqa: E402
from services.ai_modules.triple_barrier_labeler import (  # noqa: E402
    triple_barrier_label_single, atr as _atr, label_to_class_index,
)
from services.ai_modules.triple_barrier_config import get_tb_config  # noqa: E402

db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

STORED_TFT_ACC = None
_d = db.dl_models.find_one({"model_type": "tft"}) or db.dl_models.find_one({"name": "tft"})
if _d:
    STORED_TFT_ACC = _d.get("accuracy")


def _daily_labels(highs, lows, closes, pt, sl, max_bars, atr_period=14):
    """Replicate TFT label gen: entries from bar 20 onward, ATR-gated."""
    atr_series = _atr(highs, lows, closes, period=atr_period)
    out = []
    for i in range(20, len(closes) - 1):
        if i >= len(atr_series):
            break
        a = atr_series[i]
        if not np.isfinite(a) or a <= 0:
            continue
        tb = triple_barrier_label_single(
            highs, lows, closes, entry_idx=i,
            pt_atr_mult=pt, sl_atr_mult=sl, max_bars=max_bars, atr_value=float(a),
        )
        out.append(label_to_class_index(tb))  # 0=down,1=flat,2=up
    return out


def _collect(pt, sl, max_bars, max_symbols=500):
    pipeline = [
        {"$match": {"bar_size": "1 day"}},
        {"$group": {"_id": "$symbol", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gte": 60}}},
        {"$sort": {"count": -1}},
        {"$limit": max_symbols},
    ]
    syms = [d["_id"] for d in db.ib_historical_data.aggregate(pipeline, allowDiskUse=True)]
    all_lbls = []
    used = 0
    for s in syms:
        bars = list(db.ib_historical_data.find(
            {"symbol": s, "bar_size": "1 day"},
            {"high": 1, "low": 1, "close": 1, "_id": 0}).sort("date", 1).limit(5000))
        if len(bars) < 30:
            continue
        highs = np.array([b.get("high", b["close"]) for b in bars], float)
        lows = np.array([b.get("low", b["close"]) for b in bars], float)
        closes = np.array([b["close"] for b in bars], float)
        all_lbls.extend(_daily_labels(highs, lows, closes, pt, sl, max_bars))
        used += 1
    return all_lbls, used, len(syms)


def _report(title, lbls, used):
    n = len(lbls)
    print(f"\n--- {title} ---")
    if n == 0:
        print("  no labels produced")
        return None
    c = Counter(lbls)
    names = {0: "down (-1, SL)", 1: "flat (0, timeout)", 2: "up (+1, PT)"}
    for k in (0, 1, 2):
        print(f"    {names[k]:<18}: {c.get(k,0):>8}  ({100.0*c.get(k,0)/n:5.1f}%)")
    maj = max(c.values()) / n
    print(f"  symbols used: {used}   total labels: {n:,}")
    print(f"  majority-class baseline = {100*maj:.1f}%  (random 3-class = 33.3%)")
    return maj


print("=" * 78)
print("TFT REAL BASELINE DIAGNOSTIC  (read-only)")
print("=" * 78)
print(f"Stored TFT accuracy in dl_models: "
      f"{STORED_TFT_ACC if STORED_TFT_ACC is not None else 'NOT FOUND'}")

# 1) Exactly what the TFT trains on today (hardcoded 2.0 / 1.0 / 5)
lbls_hard, used_hard, n_syms = _collect(pt=2.0, sl=1.0, max_bars=5)
maj_hard = _report("TFT CURRENT labels  (hardcoded pt=2.0 sl=1.0 max_bars=5)", lbls_hard, used_hard)

# 2) What the SWEPT generic-daily config would produce
cfg = get_tb_config(db, "_GENERIC_", "1 day", "long", default_max_bars=5)
print(f"\nSwept generic-daily config in Mongo: pt={cfg['pt_atr_mult']} "
      f"sl={cfg['sl_atr_mult']} max_bars={cfg['max_bars']} (source={cfg['source']})")
lbls_sw, used_sw, _ = _collect(pt=cfg["pt_atr_mult"], sl=cfg["sl_atr_mult"], max_bars=cfg["max_bars"])
maj_sw = _report("TFT WITH SWEPT config", lbls_sw, used_sw)

# Verdict
print("\n" + "=" * 78)
print("VERDICT")
print("=" * 78)
if STORED_TFT_ACC is not None and maj_hard is not None:
    edge = STORED_TFT_ACC - maj_hard
    print(f"  TFT acc {STORED_TFT_ACC:.3f}  vs  current-label baseline {maj_hard:.3f}"
          f"  ->  edge = {edge:+.3f}")
    if edge <= 0.01:
        print("  ❌ COLLAPSED: at/below baseline. The model just predicts the majority class.")
        print("     Re-tuning triple-barrier (or switching to the swept config) is warranted.")
    else:
        print(f"  ✅ HAS EDGE: {edge*100:.1f} pts above the always-majority baseline.")
        print("     46.8% is NOT a collapse for a 3-class target — it is a real edge.")
        print("     The '47% = broken' narrative compared against a wrong 50% binary baseline.")
if maj_hard is not None and maj_sw is not None:
    print(f"\n  Class-balance comparison (lower majority% = more learnable):")
    print(f"     current hardcoded : majority {maj_hard*100:.1f}%")
    print(f"     swept config      : majority {maj_sw*100:.1f}%")
    if maj_sw < maj_hard - 0.02:
        print("  -> Swept config is BETTER balanced. Worth wiring TFT to get_tb_config + retrain.")
    elif maj_sw > maj_hard + 0.02:
        print("  -> Swept config is WORSE balanced. Keep the hardcoded labels.")
    else:
        print("  -> Roughly equivalent. No urgent need to switch.")
print("\nDONE — paste this whole block back.")
