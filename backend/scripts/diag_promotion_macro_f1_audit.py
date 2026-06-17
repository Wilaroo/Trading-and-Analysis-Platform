#!/usr/bin/env python3
"""diag_promotion_macro_f1_audit.py  —  READ-ONLY  (2026-06-16)

For every model in `timeseries_models` with metrics, pull macro_F1 +
the prior-version macro_F1 from `timeseries_model_archive`, compute the
promotion delta, and report the distribution. Tells us whether the
8% MACRO_F1_FLOOR=0.92 slack consistently allowed regressions or whether
today's `1min_bull_trend` was a one-off.
"""
import os, sys
import numpy as np
from collections import defaultdict
from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass


def _f1(metrics):
    if not isinstance(metrics, dict):
        return None
    for k in ("macro_f1", "macro_F1", "f1_macro"):
        v = metrics.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    # Approximation from per-class f1.
    ups, fls, dns = metrics.get("f1_up"), metrics.get("f1_flat"), metrics.get("f1_down")
    if all(isinstance(x, (int, float)) for x in (ups, fls, dns)):
        return float((ups + fls + dns) / 3.0)
    return None


def main():
    mu, dn = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not mu or not dn: print("ERROR: env"); sys.exit(1)
    db = MongoClient(mu, serverSelectionTimeoutMS=8000)[dn]
    models = list(db["timeseries_models"].find(
        {"name": {"$regex": "^direction_predictor_"}},
        {"_id": 0, "name": 1, "version": 1, "metrics": 1, "saved_at": 1},
    ))
    archive = db["timeseries_model_archive"]
    print(f"  scanned: {len(models)} promoted models")
    print(f"  {'model':>44} {'cur_v':>6} {'prev_v':>6} "
          f"{'cur_f1':>7} {'prev_f1':>7} {'delta':>7}")
    deltas, regressions, improvements, no_prior = [], [], [], 0
    for m in models:
        cur_f1 = _f1(m.get("metrics") or {})
        if cur_f1 is None: continue
        # Find the prior promoted version in archive (rejected_reason=null AND
        # saved_at < current's saved_at AND not the same version).
        prev = archive.find_one(
            {"name": m["name"],
             "version": {"$ne": m.get("version")},
             "rejected_reason": {"$in": [None, "", "promoted"]}},
            {"_id": 0, "version": 1, "metrics": 1, "saved_at": 1},
            sort=[("saved_at", -1)],
        )
        prev_f1 = _f1((prev or {}).get("metrics") or {})
        if prev_f1 is None:
            no_prior += 1; continue
        d = cur_f1 - prev_f1
        deltas.append((m["name"], m.get("version"), (prev or {}).get("version"),
                       cur_f1, prev_f1, d))
        if d < -0.005: regressions.append((m["name"], d, cur_f1, prev_f1))
        elif d > 0.005: improvements.append((m["name"], d, cur_f1, prev_f1))
    for name, cv, pv, cf, pf, d in sorted(deltas, key=lambda r: r[5]):
        arrow = "↓" if d < 0 else ("↑" if d > 0 else "·")
        print(f"  {name:>44} {str(cv):>6} {str(pv):>6} "
              f"{cf:>7.4f} {pf:>7.4f} {d:>+7.4f}{arrow}")
    print(f"\n  no prior comparison: {no_prior}")
    if deltas:
        arr = np.array([d[5] for d in deltas])
        print(f"  delta median: {float(np.median(arr)):+.4f}")
        print(f"  delta mean  : {float(np.mean(arr)):+.4f}")
        print(f"  delta std   : {float(np.std(arr)):.4f}")
        print(f"  regressions (>{0.005:.0%}): {len(regressions)}/{len(deltas)} "
              f"({len(regressions)/len(deltas)*100:.0f}%)")
        print(f"  improvements (>{0.005:.0%}): {len(improvements)}/{len(deltas)} "
              f"({len(improvements)/len(deltas)*100:.0f}%)")
        print(f"\n  Verdict guidance:")
        print(f"    • if median Δ ≈ 0 or +: gate slack is fine, today was a one-off")
        print(f"    • if median Δ < -0.01:  systematic decay → tighten MACRO_F1_FLOOR")
        print(f"    • if regressions >> improvements: same conclusion")
    print("\nDONE.\n")


if __name__ == "__main__":
    main()
