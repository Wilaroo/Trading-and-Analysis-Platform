#!/usr/bin/env python3
"""diag_promotion_macro_f1_audit_v2.py  —  READ-ONLY  (2026-06-16)

V2 — fixes v1's broken query that returned "no prior comparison: 0".
Strategy: for each currently-promoted model, find the MOST RECENT
archive doc with the same `name` but a DIFFERENT `version` (i.e., the
previously-promoted predecessor). Use `saved_at` for ordering. Promoted
archive entries don't carry a rejected_reason field — that was the bug.
"""
import os, sys
import numpy as np
from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass


def _f1(metrics):
    if not isinstance(metrics, dict): return None
    for k in ("macro_f1", "macro_F1", "f1_macro"):
        v = metrics.get(k)
        if isinstance(v, (int, float)): return float(v)
    ups, fls, dns = metrics.get("f1_up"), metrics.get("f1_flat"), metrics.get("f1_down")
    if all(isinstance(x, (int, float)) for x in (ups, fls, dns)):
        return float((ups + fls + dns) / 3.0)
    # Last resort — synthesize from precision/recall pairs.
    return None


def _acc(metrics):
    if not isinstance(metrics, dict): return None
    for k in ("accuracy", "val_accuracy", "test_accuracy", "oos_accuracy"):
        v = metrics.get(k)
        if isinstance(v, (int, float)): return float(v)
    return None


def main():
    mu, dn = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not mu or not dn: print("ERROR: env"); sys.exit(1)
    db = MongoClient(mu, serverSelectionTimeoutMS=8000)[dn]
    models = list(db["timeseries_models"].find(
        {"name": {"$regex": "^direction_predictor_"}},
        {"_id": 0, "name": 1, "version": 1, "metrics": 1,
         "saved_at": 1, "quarantined": 1},
    ))
    archive = db["timeseries_model_archive"]
    print(f"  promoted models scanned: {len(models)}")
    # Schema probe — what fields does archive actually have?
    arch_sample = archive.find_one({}, {"_id": 0})
    if arch_sample:
        print(f"  archive sample keys: {sorted(arch_sample.keys())[:18]}")

    print(f"\n  {'model':>44} {'cur_v':>6} {'prev_v':>6} "
          f"{'cur_f1':>7} {'prev_f1':>7} {'Δf1':>7} "
          f"{'cur_acc':>7} {'prev_acc':>7}")
    deltas_f1, deltas_acc = [], []
    no_prev_doc, no_prev_metrics = 0, 0
    regressions_f1, improvements_f1, flat_f1 = [], [], []
    for m in models:
        cur_f1 = _f1(m.get("metrics") or {})
        cur_acc = _acc(m.get("metrics") or {})
        cur_v = m.get("version") or ""
        # Find previous version in archive: same name, version != current,
        # most recent by saved_at.
        prev = archive.find_one(
            {"name": m["name"], "version": {"$ne": cur_v},
             "metrics": {"$exists": True}},
            {"_id": 0, "version": 1, "metrics": 1, "saved_at": 1},
            sort=[("saved_at", -1)],
        )
        if prev is None:
            no_prev_doc += 1; continue
        prev_f1 = _f1(prev.get("metrics") or {})
        prev_acc = _acc(prev.get("metrics") or {})
        if prev_f1 is None and prev_acc is None:
            no_prev_metrics += 1; continue
        df = (cur_f1 - prev_f1) if (cur_f1 is not None and prev_f1 is not None) else None
        da = (cur_acc - prev_acc) if (cur_acc is not None and prev_acc is not None) else None
        if df is not None:
            deltas_f1.append(df)
            if df < -0.005: regressions_f1.append((m["name"], df))
            elif df > 0.005: improvements_f1.append((m["name"], df))
            else: flat_f1.append((m["name"], df))
        if da is not None: deltas_acc.append(da)
        df_s = f"{df:+.4f}" if df is not None else "   n/a"
        da_s = "" if da is None else ""
        print(f"  {m['name']:>44} {cur_v:>6} {prev.get('version','?'):>6} "
              f"{(cur_f1 if cur_f1 is not None else 0):>7.4f} "
              f"{(prev_f1 if prev_f1 is not None else 0):>7.4f} "
              f"{df_s:>7} "
              f"{(cur_acc if cur_acc is not None else 0):>7.4f} "
              f"{(prev_acc if prev_acc is not None else 0):>7.4f}")
    print(f"\n  skipped: no prior archive doc = {no_prev_doc}  ·  "
          f"no metrics in prev = {no_prev_metrics}")
    if deltas_f1:
        arr = np.array(deltas_f1)
        print(f"\n  macro_F1 delta distribution (n={len(arr)}):")
        print(f"    median: {float(np.median(arr)):+.4f}")
        print(f"    mean  : {float(np.mean(arr)):+.4f}")
        print(f"    std   : {float(np.std(arr)):.4f}")
        print(f"    min   : {float(np.min(arr)):+.4f}")
        print(f"    max   : {float(np.max(arr)):+.4f}")
        n = len(arr)
        print(f"    regressions (Δ<-0.005): {len(regressions_f1)}/{n} "
              f"({len(regressions_f1)/n*100:.0f}%)")
        print(f"    improvements (Δ>+0.005): {len(improvements_f1)}/{n} "
              f"({len(improvements_f1)/n*100:.0f}%)")
        print(f"    flat (|Δ|≤0.005)      : {len(flat_f1)}/{n}")
    if deltas_acc:
        arr = np.array(deltas_acc)
        print(f"\n  accuracy delta median: {float(np.median(arr)):+.4f}  "
              f"mean: {float(np.mean(arr)):+.4f}")
    print("\n  Verdict guidance:")
    print("    • median Δf1 ≥ 0 AND regressions < 30%  →  8% slack is fine")
    print("    • median Δf1 < -0.005 OR regressions > 60% →  tighten "
          "MACRO_F1_FLOOR (0.92 → 0.97)")
    print("    • mixed signal → look at WHICH models regressed; "
          "may be cell-specific")
    print("\nDONE.\n")


if __name__ == "__main__":
    main()
