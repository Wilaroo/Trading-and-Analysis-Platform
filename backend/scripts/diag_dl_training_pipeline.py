#!/usr/bin/env python3
"""
#4 investigation (read-only) — WHY the deep-learning stack (TFT/CNN-LSTM/VAE)
collapsed, plus the last training run's per-phase failures and the environment.

Sections:
  A. Environment — torch / CUDA presence (DL trains on CPU if no CUDA → slow but
     not collapse; collapse is a labeling/feature problem).
  B. Last `training_pipeline_status` — phase reached, per-model errors, completes.
  C. dl_models registry — accuracy vs majority_baseline + edge (the collapse flag).
  D. TRIPLE-BARRIER LABEL DISTRIBUTION on a real sample — the suspected root: if
     class 0 (time-barrier) dominates, the model can only learn "predict majority".
  E. FinBERT / news data availability.

Usage:
  cd ~/Trading-and-Analysis-Platform
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_dl_training_pipeline.py
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

db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def section(t):
    print(f"\n=== {t} ===")


# A. Environment
section("A. ENVIRONMENT (torch / CUDA)")
try:
    import torch
    print(f"  torch {torch.__version__}  CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"  device: {torch.cuda.get_device_name(0)}")
    else:
        print("  → CPU-only. DL training will be SLOW (not the cause of collapse).")
except Exception as e:
    print(f"  torch NOT importable: {e}  → DL training would hard-fail here.")

# B. Last training run status
section("B. LAST training_pipeline_status")
st = db.training_pipeline_status.find_one(sort=[("_id", -1)])
if not st:
    print("  (no training_pipeline_status doc — pipeline may never have persisted)")
else:
    print(f"  phase={st.get('phase')}  current_model={st.get('current_model')}")
    print(f"  started={st.get('started_at')}  updated={st.get('updated_at')}")
    errs = st.get("errors") or []
    print(f"  errors ({len(errs)}):")
    for e in errs[-15:]:
        if isinstance(e, dict):
            print(f"    - {e.get('model') or e.get('name')}: {str(e.get('error') or e.get('reason'))[:140]}")
        else:
            print(f"    - {str(e)[:140]}")
    comp = st.get("completed") or st.get("completed_models") or []
    print(f"  completed ({len(comp)})")

# C. DL model registry
section("C. dl_models REGISTRY (accuracy vs majority baseline)")
for d in db.dl_models.find({}, {"_id": 0}):
    name = d.get("model_type") or d.get("name") or "?"
    acc = d.get("accuracy")
    mb = d.get("majority_baseline")
    edge = d.get("edge_above_baseline")
    mt = d.get("metric_type", "accuracy")
    ts = d.get("trained_at") or d.get("updated_at") or ""
    line = f"  {str(name):<22} acc={acc}"
    if mb is not None:
        line += f"  majority_baseline={mb}"
    if edge is not None:
        line += f"  edge={edge:+.4f}  {'COLLAPSED' if edge <= 0.01 else 'has-edge'}"
    line += f"  ({mt})  {str(ts)[:19]}"
    print(line)

# D. Triple-barrier label distribution on a real sample
section("D. TRIPLE-BARRIER LABEL DISTRIBUTION (the collapse suspect)")
try:
    from services.ai_modules.triple_barrier_labeler import triple_barrier_labels
    # sample a few liquid symbols' 5-min bars
    syms = ["AAPL", "MSFT", "NVDA", "AMD", "TSLA", "SPY", "QQQ", "META", "AMZN", "GOOGL"]
    all_lbls = []
    used = []
    for s in syms:
        bars = list(db.ib_historical_data.find(
            {"symbol": s, "bar_size": "5 mins"},
            {"high": 1, "low": 1, "close": 1, "_id": 0}).sort("date", 1).limit(4000))
        if len(bars) < 200:
            continue
        highs = np.array([b["high"] for b in bars], dtype=float)
        lows = np.array([b["low"] for b in bars], dtype=float)
        closes = np.array([b["close"] for b in bars], dtype=float)
        lbls = triple_barrier_labels(highs, lows, closes,
                                     pt_atr_mult=2.0, sl_atr_mult=1.0, max_bars=20)
        all_lbls.extend(list(np.asarray(lbls).ravel()))
        used.append(s)
    if all_lbls:
        c = Counter(int(x) for x in all_lbls)
        n = len(all_lbls)
        print(f"  sample symbols: {used}  (n={n} labels, 5min, default 2.0/1.0/20)")
        for cls, name in [(-1, "stop (-1)"), (0, "timeout (0)"), (1, "target (+1)")]:
            print(f"    {name:<14}: {c.get(cls,0):>7}  ({100.0*c.get(cls,0)/n:.1f}%)")
        maj = max(c.values()) / n
        print(f"  → majority class = {100*maj:.1f}%. A model that just predicts it")
        print(f"    scores ~{100*maj:.0f}% — which is ~where TFT/CNN-LSTM are stuck.")
        if c.get(0, 0) / n > 0.45:
            print("  VERDICT: class-0 (timeout) DOMINATES → re-tune PT/SL/max_bars so")
            print("  more entries resolve to ±1 (use sweep_triple_barrier.py).")
    else:
        print("  (no 5-min bars found for the sampled symbols)")
except Exception as e:
    print(f"  triple-barrier sampling failed: {e}")

# E. FinBERT / news
section("E. FINBERT / NEWS DATA")
for coll in ["news_sentiment", "news_articles", "finbert_sentiment_cache"]:
    if coll in db.list_collection_names():
        print(f"  {coll}: {db[coll].count_documents({})} docs")
print("\nDONE — paste this whole block back.")
