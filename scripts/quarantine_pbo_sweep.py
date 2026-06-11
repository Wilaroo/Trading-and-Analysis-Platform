#!/usr/bin/env python3
"""quarantine_pbo_sweep.py — v322i: quarantine already-ACTIVE models that
fail the PBO gate.

Shadow mode promoted several provably-overfit models (e.g. the exit_timing
family at PBO 0.93-1.00 with negative OOS edge). TB_PBO_GATE=enforce only
protects FUTURE promotions — this sweep flags the active legacies so every
load path serves no model instead (predict() degrades to the neutral
flat/0-confidence prediction; consumers fall back to rule-based behaviour).

The flag is reversible (--undo) and auto-lifts when a future healthy
version of the same model passes the gate and gets promoted.

Usage (from the repo root):
  python3 scripts/quarantine_pbo_sweep.py             # DRY RUN (default)
  python3 scripts/quarantine_pbo_sweep.py --apply     # write the flags
  python3 scripts/quarantine_pbo_sweep.py --strict    # also flag PBO-only
                                                      # failers w/ positive edge
  python3 scripts/quarantine_pbo_sweep.py --undo --apply   # clear all flags

After --apply: RESTART THE BACKEND (./start_backend.sh --force) so
in-memory boosters are evicted.
"""
import argparse
import os
import sys
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(REPO, "backend", ".env")


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


def select_quarantine_targets(rows, pbo_max=0.20, min_edge=0.0, strict=False):
    """Pure: pick quarantine targets from CPCV-bearing active models.

    rows: [{name, pbo, edge, folds}, ...] with folds > 0.
    Default scope: gate failers with edge <= min_edge (provably NO OOS
    edge — toxic). With strict=True: every gate failer (pbo > pbo_max OR
    edge <= min_edge), i.e. exactly what enforce would have blocked.
    """
    out = []
    for r in rows:
        fails_gate = (r["pbo"] > pbo_max) or (r["edge"] <= min_edge)
        if not fails_gate:
            continue
        if strict or r["edge"] <= min_edge:
            out.append(r)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--strict", action="store_true",
                    help="also quarantine PBO-only failers with positive edge")
    ap.add_argument("--undo", action="store_true", help="clear ALL quarantine flags")
    args = ap.parse_args()

    env = load_env(ENV_PATH)
    mongo_url = env.get("MONGO_URL") or os.environ.get("MONGO_URL")
    db_name = env.get("DB_NAME") or os.environ.get("DB_NAME", "tradecommand")
    if not mongo_url:
        print("ERROR: MONGO_URL not found in backend/.env or environment")
        sys.exit(1)
    pbo_max = float(env.get("TB_PBO_MAX") or os.environ.get("TB_PBO_MAX", "0.20"))
    min_edge = float(env.get("TB_CPCV_MIN_EDGE") or os.environ.get("TB_CPCV_MIN_EDGE", "0.0"))

    from pymongo import MongoClient
    db = MongoClient(mongo_url, serverSelectionTimeoutMS=10000)[db_name]
    col = db["timeseries_models"]

    if args.undo:
        flagged = list(col.find({"quarantined": True}, {"_id": 0, "name": 1}))
        print(f"UNDO: {len(flagged)} quarantined model(s): "
              f"{[d['name'] for d in flagged]}")
        if args.apply and flagged:
            res = col.update_many(
                {"quarantined": True},
                {"$unset": {"quarantined": "", "quarantine_reason": "",
                            "quarantined_at": ""}})
            print(f"Cleared {res.modified_count} flag(s). RESTART THE BACKEND.")
        elif not args.apply:
            print("(dry run — add --apply to clear)")
        return

    rows = []
    for d in col.find({"metrics.cpcv_n_folds": {"$gt": 0}},
                      {"_id": 0, "name": 1, "version": 1,
                       "metrics.cpcv_pbo": 1, "metrics.cpcv_edge_mean": 1,
                       "metrics.cpcv_n_folds": 1, "quarantined": 1}):
        m = d.get("metrics") or {}
        rows.append({"name": d["name"], "version": d.get("version"),
                     "pbo": float(m.get("cpcv_pbo") or 0.0),
                     "edge": float(m.get("cpcv_edge_mean") or 0.0),
                     "folds": int(m.get("cpcv_n_folds") or 0),
                     "already": bool(d.get("quarantined"))})

    targets = select_quarantine_targets(rows, pbo_max, min_edge, args.strict)
    scope = "STRICT (all gate failers)" if args.strict else "default (negative-edge failers only)"
    print(f"\nGate: PBO_MAX={pbo_max} MIN_EDGE={min_edge} | scope: {scope}")
    print(f"CPCV-bearing active models: {len(rows)} | quarantine targets: {len(targets)}\n")
    print(f"{'model':<42} {'ver':<10} {'PBO':>6} {'edge':>8}  flag")
    for r in sorted(targets, key=lambda x: -x["pbo"]):
        mark = "already" if r["already"] else ("WILL SET" if args.apply else "would set")
        print(f"{r['name']:<42} {str(r['version'])[:10]:<10} "
              f"{r['pbo']:>6.2f} {r['edge']:>+8.3f}  {mark}")

    if not args.apply:
        print("\n(dry run — add --apply to write the flags)")
        return

    now = datetime.now(timezone.utc).isoformat()
    n = 0
    for r in targets:
        if r["already"]:
            continue
        reason = (f"pbo_sweep v322i: PBO {r['pbo']:.2f} > {pbo_max:.2f}"
                  if r["pbo"] > pbo_max else "pbo_sweep v322i") + (
                  f" & OOS edge {r['edge']:+.3f} <= {min_edge:+.3f}"
                  if r["edge"] <= min_edge else "")
        col.update_one({"name": r["name"]},
                       {"$set": {"quarantined": True,
                                 "quarantine_reason": reason,
                                 "quarantined_at": now}})
        n += 1
    print(f"\nQuarantined {n} model(s). RESTART THE BACKEND to evict "
          f"in-memory boosters:  ./start_backend.sh --force")
    print("Reverse anytime:  python3 scripts/quarantine_pbo_sweep.py --undo --apply")


if __name__ == "__main__":
    main()
