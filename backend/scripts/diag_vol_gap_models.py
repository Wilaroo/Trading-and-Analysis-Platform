#!/usr/bin/env python3
"""
diag_vol_gap_models.py  —  audit  (2026-06-10)   READ-ONLY

Audit finding: the VOLATILITY and GAP-FILL model families are TRAINED nightly
but NEVER consumed at inference — no code reads their predictions (the
confidence gate has no vol/gap layer; dynamic_risk_engine / stop_manager /
position sizing don't query them; compute_vol_specific_features is dead code).

This script quantifies the waste / opportunity: how many vol/gap models exist,
their accuracy, sample counts and staleness — so we can decide to either
(a) WIRE THEM IN as new gate layers / sizing inputs (if they have edge), or
(b) STOP training them to reclaim nightly GPU time.

Run:
    cd ~/Trading-and-Analysis-Platform && \
      .venv/bin/python backend/scripts/diag_vol_gap_models.py
"""
import os
import sys
from collections import Counter

from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")

CANDIDATE_COLLECTIONS = ["timeseries_models", "volatility_models", "gap_fill_models", "dl_models"]
EDGE_FLOOR = 0.52


def hr(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def _acc(doc):
    for k in ("accuracy", "val_accuracy", "test_accuracy", "cv_accuracy"):
        v = doc.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    metrics = doc.get("metrics") or {}
    for k in ("accuracy", "val_accuracy"):
        v = metrics.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return None


def main():
    if not MONGO_URL or not DB_NAME:
        print("ERROR: MONGO_URL / DB_NAME not set in backend/.env")
        sys.exit(1)
    db = MongoClient(MONGO_URL, serverSelectionTimeoutMS=8000)[DB_NAME]

    for fam, prefix in (("VOLATILITY", "vol_predictor"), ("GAP-FILL", "gap_fill")):
        hr(f"{fam} MODELS  (name ~ '{prefix}*')")
        found = []
        for coll in CANDIDATE_COLLECTIONS:
            if coll not in db.list_collection_names():
                continue
            for d in db[coll].find(
                {"model_name": {"$regex": f"^{prefix}"}},
                {"_id": 0, "model_name": 1, "accuracy": 1, "val_accuracy": 1,
                 "test_accuracy": 1, "metrics": 1, "samples": 1, "n_samples": 1,
                 "trained_at": 1, "updated_at": 1},
            ):
                d["_coll"] = coll
                found.append(d)

        if not found:
            print(f"  none found in {CANDIDATE_COLLECTIONS}")
            continue

        accs = []
        print(f"  {'model':>22} {'coll':>18} {'acc':>7} {'samples':>9} {'trained':>12}")
        for d in sorted(found, key=lambda x: x.get("model_name", "")):
            a = _acc(d)
            accs.append(a if a is not None else 0.0)
            samples = d.get("samples") or d.get("n_samples") or "?"
            trained = str(d.get("trained_at") or d.get("updated_at") or "?")[:10]
            astr = f"{a:.3f}" if a is not None else "  n/a"
            edge = " *EDGE*" if (a is not None and a >= EDGE_FLOOR) else ""
            print(f"  {d.get('model_name','?'):>22} {d['_coll']:>18} {astr:>7} {str(samples):>9} {trained:>12}{edge}")

        n = len(found)
        with_edge = sum(1 for a in accs if a >= EDGE_FLOOR)
        avg = sum(accs) / n if n else 0
        print(f"\n  total={n}  avg_acc={avg:.3f}  with_edge(>= {EDGE_FLOOR})={with_edge}/{n}")
        print(f"  -> consumed at inference: NO (audit: no code reads {prefix}_* predictions)")
        if with_edge:
            print(f"  -> {with_edge} model(s) show edge — candidates to WIRE INTO the gate/sizing.")
        else:
            print("  -> no edge above floor — candidates to STOP training (reclaim GPU).")

    print("\nDONE.\n")


if __name__ == "__main__":
    main()
