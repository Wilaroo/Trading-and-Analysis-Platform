#!/usr/bin/env python3
"""
DL-ACCURACY AUDIT (read-only) — are TFT / CNN-LSTM genuinely collapsed, or just
missing their accuracy metric?

The confidence gate IGNORES any DL model whose `model_accuracy` is < 0.52
(`confidence_gate.py` lines 615/622 and 708/712). Crucially the lookup defaults
to **0.5** when the metric is absent — which is ITSELF below the 0.52 gate. So a
perfectly fine model with an unpopulated metric is silently treated as
"majority-class collapse". This script tells the two cases apart by showing:

  (A) the ACTUAL accuracy values the gate logged (un-normalized), pulled from the
      "TFT/CNN-LSTM signal IGNORED — model accuracy XX.X%" reasoning lines, and
  (B) what's actually stored in the model-registry collections (so we can see if
      the metric exists there but isn't reaching the gate).

Verdict:
  • values cluster EXACTLY at 50.0%  → metric MISSING → defaulting to 0.5 → a
    loading/wiring bug, NOT real collapse → fixable without retraining.
  • values spread 40-51%             → genuine sub-edge models → retrain needed.

Usage:
  cd ~/Trading-and-Analysis-Platform
  .venv/bin/python backend/scripts/diag_dl_accuracy_audit.py [HOURS]   # default 8
"""
import re
import sys
import statistics
from collections import Counter
from datetime import datetime, timezone, timedelta

from pymongo import MongoClient

HOURS = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0

_IGNORE_RE = re.compile(
    r"(TFT|CNN-LSTM)\s+signal IGNORED — model accuracy\s+([\d.]+)%", re.I
)


def _load_db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return MongoClient(env["MONGO_URL"])[env["DB_NAME"]]


def _audit_gate_log(db):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=HOURS)).isoformat()
    rows = list(db.confidence_gate_log.find({"timestamp": {"$gte": cutoff}},
                                            {"reasoning": 1}))
    print(f"=== (A) ACCURACY VALUES THE GATE SAW — last {HOURS:g}h "
          f"({len(rows)} decisions) ===")
    vals = {"TFT": [], "CNN-LSTM": []}
    for r in rows:
        for line in (r.get("reasoning") or []):
            m = _IGNORE_RE.search(str(line))
            if m:
                vals[m.group(1).upper()].append(float(m.group(2)))
    for model, vlist in vals.items():
        if not vlist:
            print(f"  {model:<9}: no IGNORED lines (either contributing, or "
                  f"has_prediction=False — see (B))")
            continue
        dist = Counter(round(v, 1) for v in vlist)
        print(f"  {model:<9}: n={len(vlist)}  min={min(vlist):.1f}%  "
              f"median={statistics.median(vlist):.1f}%  max={max(vlist):.1f}%")
        top = ", ".join(f"{k}%×{n}" for k, n in dist.most_common(6))
        print(f"             value spread: {top}")
        if abs(statistics.median(vlist) - 50.0) < 0.05 and len(dist) <= 2:
            print(f"             ⚠ pinned at 50.0% → METRIC MISSING (defaulted) "
                  f"→ loading bug, NOT real collapse.")
        else:
            print(f"             → real measured spread → genuine sub-edge model.")


def _dump_registry(db):
    print("\n=== (B) MODEL REGISTRY — stored accuracy fields ===")
    # Candidate collections + likely accuracy field names. Defensive: skip any
    # that don't exist. We surface anything that looks like an accuracy metric.
    candidates = [
        "timeseries_models", "dl_models", "cnn_models", "setup_type_models",
        "model_validations", "model_baselines", "tft_models", "cnn_lstm_models",
    ]
    acc_fields = ["model_accuracy", "accuracy", "val_accuracy", "test_accuracy",
                  "directional_accuracy", "oos_accuracy", "validation_accuracy"]
    existing = set(db.list_collection_names())
    for coll in candidates:
        if coll not in existing:
            continue
        n = db[coll].count_documents({})
        if n == 0:
            print(f"  {coll}: (empty)")
            continue
        # Pull a few recent docs and show any accuracy-like fields + model id/type.
        docs = list(db[coll].find({}, {"_id": 0}).sort([("_id", -1)]).limit(8))
        print(f"  {coll}: {n} docs — recent sample:")
        for d in docs:
            ident = (d.get("model_type") or d.get("setup_type") or d.get("name")
                     or d.get("model_name") or d.get("model_id") or "?")
            accs = {f: d.get(f) for f in acc_fields if d.get(f) is not None}
            ts = d.get("trained_at") or d.get("created_at") or d.get("updated_at") or ""
            if accs:
                print(f"      {str(ident)[:34]:<34} {accs}  {str(ts)[:19]}")
            else:
                # show the keys so we can find the real accuracy field name
                keys = [k for k in d.keys() if "acc" in k.lower() or "score" in k.lower()]
                print(f"      {str(ident)[:34]:<34} (no std acc field; acc-like keys: {keys})")


def main():
    db = _load_db()
    _audit_gate_log(db)
    _dump_registry(db)
    print("\nNEXT:")
    print("  • If (A) is pinned at 50.0% but (B) shows a real stored accuracy "
          ">=0.52 → the metric isn't being threaded into the live signal → "
          "wiring fix (no retrain).")
    print("  • If both (A) and (B) show <0.52 → genuine collapse → retrain with "
          "triple-barrier targets.")


if __name__ == "__main__":
    main()
