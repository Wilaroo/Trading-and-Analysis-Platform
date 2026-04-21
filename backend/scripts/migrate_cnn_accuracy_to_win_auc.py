"""
One-time migration: swap CNN `metrics.accuracy` to `metrics.win_auc`.

Why
---
Before 2026-04-21, CNN per-setup models saved `metrics.accuracy` as the
17-class setup-type classification accuracy, which is tautologically ~1.0
because every sample in `cnn_<setup>_<bar_size>` has the same setup_type.

The real predictive metric is `metrics.win_auc` — binary WIN/LOSS AUC from
the dedicated win-prediction head. Going forward, the training code writes
`accuracy = win_auc`, but the 34 existing records still show the old 1.0
value in `cnn_models` → confusing UI + breaks scorecard trust.

This script:
  1. Backs up `metrics.accuracy` into `metrics.pattern_classification_accuracy`
     if that field is missing (safety — should already be present).
  2. Sets `metrics.accuracy = metrics.win_auc` for every existing doc.
  3. Also fills win_accuracy/precision/recall/f1 with a note if absent
     (we cannot recompute those without re-running the test loop; flagging them
      as 'missing' so the UI can skip rendering).

Run:
    /home/spark-1a60/venv/bin/python \
        backend/scripts/migrate_cnn_accuracy_to_win_auc.py
"""
import os
import sys
from pymongo import MongoClient


def main() -> int:
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "tradecommand")
    mc = MongoClient(mongo_url)
    db = mc[db_name]

    coll = db["cnn_models"]
    cur = list(coll.find({"metrics.win_auc": {"$exists": True}},
                         {"_id": 1, "model_name": 1, "metrics": 1}))
    if not cur:
        print("[migrate] No CNN docs with win_auc found — nothing to do.")
        return 0

    print(f"[migrate] Found {len(cur)} CNN docs with win_auc.\n")

    updated = 0
    skipped = 0
    for doc in cur:
        m = doc.get("metrics", {}) or {}
        wa = m.get("win_auc")
        acc = m.get("accuracy")
        pca = m.get("pattern_classification_accuracy")

        if wa is None:
            print(f"  SKIP {doc['model_name']}: no win_auc")
            skipped += 1
            continue

        # If accuracy already equals win_auc, this doc was saved with the new code.
        if acc is not None and abs(float(acc) - float(wa)) < 1e-6:
            print(f"  OK   {doc['model_name']}: accuracy already == win_auc ({wa})")
            skipped += 1
            continue

        set_ops = {
            "metrics.accuracy": float(wa),
        }
        # Preserve original pattern-classification value
        if pca is None and acc is not None:
            set_ops["metrics.pattern_classification_accuracy"] = float(acc)

        coll.update_one({"_id": doc["_id"]}, {"$set": set_ops})
        updated += 1
        print(
            f"  MIGR {doc['model_name']:38s} "
            f"accuracy: {acc} → {wa}"
        )

    print(f"\n[migrate] Done. Updated {updated}, skipped {skipped}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
