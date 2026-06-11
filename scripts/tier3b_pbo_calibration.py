#!/usr/bin/env python3
"""tier3b_pbo_calibration.py — Tier 3b step 1: calibrate the PBO bouncer
from the fresh retrain's CPCV honesty metrics BEFORE flipping
TB_PBO_GATE=enforce.

Reads backend/.env for Mongo, inspects `timeseries_models` (active) +
`timeseries_model_archive` (shadow verdicts from this run), prints the
PBO/edge distribution, simulates the gate across threshold combos, and
prints a recommendation.

Run from the repo root:  python3 tier3b_pbo_calibration.py
(stdlib + pymongo only — works with system python3 or .venv)
"""
import os
import re
import sys
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(REPO, "backend", ".env")
LOG_PATH = os.path.join(REPO, "backend", "training_subprocess.log")
FRESH_HOURS = 36          # only judge models saved in the last N hours
PBO_GRID = [0.10, 0.15, 0.20, 0.25, 0.30]
EDGE_GRID = [0.0, 0.005, 0.01]


def load_env(path):
    out = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    out[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return out


def pct(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    i = min(len(s) - 1, int(round(p / 100.0 * (len(s) - 1))))
    return s[i]


def main():
    env = load_env(ENV_PATH)
    mongo_url = env.get("MONGO_URL") or os.environ.get("MONGO_URL")
    db_name = env.get("DB_NAME") or os.environ.get("DB_NAME", "tradecommand")
    if not mongo_url:
        print("ERROR: MONGO_URL not found in backend/.env or environment")
        sys.exit(1)

    from pymongo import MongoClient
    db = MongoClient(mongo_url, serverSelectionTimeoutMS=10000)[db_name]

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=FRESH_HOURS)).isoformat()
    rows = []
    for d in db["timeseries_models"].find(
            {"metrics.cpcv_n_folds": {"$gt": 0}},
            {"_id": 0, "name": 1, "version": 1, "saved_at": 1,
             "metrics.cpcv_pbo": 1, "metrics.cpcv_edge_mean": 1,
             "metrics.cpcv_n_folds": 1, "metrics.accuracy": 1}):
        saved = str(d.get("saved_at") or "")
        m = d.get("metrics") or {}
        rows.append({
            "name": d.get("name"), "version": d.get("version"),
            "saved_at": saved, "fresh": saved >= cutoff,
            "pbo": float(m.get("cpcv_pbo") or 0.0),
            "edge": float(m.get("cpcv_edge_mean") or 0.0),
            "folds": int(m.get("cpcv_n_folds") or 0),
            "acc": m.get("accuracy"),
        })

    fresh = [r for r in rows if r["fresh"]]
    judge = fresh if fresh else rows
    label = f"FRESH (last {FRESH_HOURS}h)" if fresh else "ALL (no fresh found!)"
    print(f"\n=== ACTIVE MODELS WITH CPCV METRICS — {label}: {len(judge)} "
          f"(total with CPCV: {len(rows)}) ===\n")
    judge.sort(key=lambda r: -r["pbo"])
    print(f"{'model':<42} {'ver':<10} {'folds':>5} {'PBO':>6} {'edge':>8} {'acc':>6}")
    for r in judge:
        acc = f"{r['acc']:.3f}" if isinstance(r["acc"], (int, float)) else "-"
        print(f"{str(r['name'])[:42]:<42} {str(r['version'])[:10]:<10} "
              f"{r['folds']:>5} {r['pbo']:>6.2f} {r['edge']:>+8.3f} {acc:>6}")

    pbos = [r["pbo"] for r in judge]
    edges = [r["edge"] for r in judge]
    if pbos:
        print(f"\nPBO  distribution: min {min(pbos):.2f} | p25 {pct(pbos,25):.2f} | "
              f"median {pct(pbos,50):.2f} | p75 {pct(pbos,75):.2f} | max {max(pbos):.2f}")
        print(f"edge distribution: min {min(edges):+.3f} | p25 {pct(edges,25):+.3f} | "
              f"median {pct(edges,50):+.3f} | p75 {pct(edges,75):+.3f} | max {max(edges):+.3f}")

    print("\n=== GATE SIMULATION (blocked / total under each threshold combo) ===\n")
    print(f"{'':>12}" + "".join(f"  edge>{e:<6}" for e in EDGE_GRID))
    for pm in PBO_GRID:
        cells = []
        for me in EDGE_GRID:
            blocked = sum(1 for r in judge if r["pbo"] > pm or r["edge"] <= me)
            cells.append(f"  {blocked:>3}/{len(judge):<6}")
        print(f"PBO_MAX {pm:<5}" + "".join(cells))

    # Shadow verdicts persisted by this run (archive collection).
    print("\n=== SHADOW VERDICTS (timeseries_model_archive, this run) ===\n")
    n_shadow = 0
    for d in db["timeseries_model_archive"].find(
            {"pbo_gate.verdict": {"$exists": True}},
            {"_id": 0, "name": 1, "version": 1, "saved_at": 1, "pbo_gate": 1}
            ).sort("saved_at", -1).limit(40):
        if str(d.get("saved_at") or "") < cutoff:
            continue
        n_shadow += 1
        g = d.get("pbo_gate") or {}
        print(f"  {d.get('name')} {d.get('version')}: {g.get('verdict')} — {g.get('reason')}")
    if n_shadow == 0:
        print("  (none persisted in the fresh window)")

    # Shadow log lines (best-effort).
    try:
        with open(LOG_PATH, errors="ignore") as f:
            shadow_lines = [l.strip() for l in f if "[PBO-GATE" in l]
        print(f"\n=== [PBO-GATE] LOG LINES (training_subprocess.log): {len(shadow_lines)} ===")
        for l in shadow_lines[-20:]:
            print(" ", l[:160])
    except FileNotFoundError:
        pass

    # Recommendation.
    print("\n=== RECOMMENDATION ===\n")
    if not judge:
        print("No CPCV-bearing models found — do NOT flip enforce yet; check why")
        print("cpcv_n_folds is 0 across the board (CPCV may be disabled).")
        return
    defaults_blocked = sum(1 for r in judge if r["pbo"] > 0.20 or r["edge"] <= 0.0)
    frac = defaults_blocked / len(judge)
    print(f"At the DEFAULTS (TB_PBO_MAX=0.20, TB_CPCV_MIN_EDGE=0.0): "
          f"{defaults_blocked}/{len(judge)} ({frac:.0%}) would be blocked.")
    if frac > 0.5:
        print("⚠ More than half blocked — defaults are too strict for this corpus.")
        print("  Consider TB_PBO_MAX=0.25 or 0.30 first, tighten over future runs.")
    elif frac == 0:
        print("Nothing blocked — gate is free protection. Flip to enforce as-is.")
    else:
        print("Healthy bouncer zone (blocks the overfit tail, keeps the rest).")
        print("Flip to enforce with the defaults.")
    print("\nTo FLIP (on the DGX):")
    print("  1. Add to backend/.env :  TB_PBO_GATE=enforce")
    print("     (plus TB_PBO_MAX=<value> if deviating from 0.20)")
    print("  2. ./start_backend.sh --force")
    print("  3. The gate activates at the NEXT training/promotion — fresh-trained")
    print("     models already promoted are unaffected.")


if __name__ == "__main__":
    main()
