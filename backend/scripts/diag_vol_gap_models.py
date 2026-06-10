#!/usr/bin/env python3
"""
diag_vol_gap_models.py  —  audit  (2026-06-10, rev2)   READ-ONLY

Audit finding: VOLATILITY (vol_predictor_*), GAP-FILL (gap_fill_*) and the
VOL-CONDITIONED direction models (direction_predictor_*_high_vol) are TRAINED
and PROMOTED to timeseries_models, but NEVER consumed at inference. The live
layer (timeseries_service.MODEL_CONFIGS) loads ONLY base direction_predictor_*.

rev2: the name field in timeseries_models is `name` (not `model_name`).

This prints each dead model's accuracy + sample count so we can decide to
WIRE IN the edge-positive ones or RETIRE the rest to reclaim nightly GPU.

Run:
    cd ~/Trading-and-Analysis-Platform && \
      .venv/bin/python backend/scripts/diag_vol_gap_models.py
"""
import os
import sys

from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")
COLL = "timeseries_models"
EDGE_FLOOR = 0.52

FAMILIES = {
    "VOLATILITY (vol_predictor_*)": "^vol_predictor",
    "GAP-FILL (gap_fill_*)": "^gap_fill",
    "VOL-CONDITIONED DIRECTION (*_high_vol)": "_high_vol$",
}


def hr(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def _acc(doc):
    m = doc.get("metrics") or {}
    for src in (m, doc):
        for k in ("accuracy", "val_accuracy", "test_accuracy", "cv_accuracy", "oos_accuracy"):
            v = src.get(k)
            if isinstance(v, (int, float)):
                return float(v)
    return None


def _samples(doc):
    m = doc.get("metrics") or {}
    for src in (doc, m):
        for k in ("training_samples", "samples", "n_samples", "total_samples"):
            v = src.get(k)
            if isinstance(v, (int, float)):
                return int(v)
    return None


def main():
    if not MONGO_URL or not DB_NAME:
        print("ERROR: MONGO_URL / DB_NAME not set in backend/.env")
        sys.exit(1)
    db = MongoClient(MONGO_URL, serverSelectionTimeoutMS=8000)[DB_NAME]
    col = db[COLL]

    grand_edge = grand_total = 0
    for title, rx in FAMILIES.items():
        hr(title)
        docs = list(col.find({"name": {"$regex": rx}},
                             {"_id": 0, "name": 1, "metrics": 1, "version": 1,
                              "updated_at": 1, "saved_at": 1, "training_samples": 1}))
        if not docs:
            print("  none found")
            continue
        print(f"  {'name':>34} {'acc':>7} {'samples':>9} {'updated':>12}")
        accs = []
        for d in sorted(docs, key=lambda x: x.get("name", "")):
            a = _acc(d)
            accs.append(a if a is not None else 0.0)
            s = _samples(d)
            upd = str(d.get("updated_at") or d.get("saved_at") or "?")[:10]
            astr = f"{a:.3f}" if a is not None else "  n/a"
            flag = " *EDGE*" if (a is not None and a >= EDGE_FLOOR) else ""
            print(f"  {d.get('name','?'):>34} {astr:>7} {str(s if s is not None else '?'):>9} {upd:>12}{flag}")
        n = len(docs)
        edge = sum(1 for a in accs if a >= EDGE_FLOOR)
        grand_total += n
        grand_edge += edge
        print(f"\n  total={n}  avg_acc={sum(accs)/n:.3f}  with_edge(>= {EDGE_FLOOR})={edge}/{n}")

    hr("SUMMARY")
    print(f"  dead-at-inference models: {grand_total}")
    print(f"  with edge (>= {EDGE_FLOOR}): {grand_edge}")
    print(f"  no edge (retire candidates): {grand_total - grand_edge}")
    print("  consumed at inference: NONE (live layer loads only direction_predictor_*)")
    print("\nDONE.\n")


if __name__ == "__main__":
    main()
