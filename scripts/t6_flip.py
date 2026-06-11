#!/usr/bin/env python3
"""t6_flip.py — v322j: audit the T6 shadow data, then flip the per-setup×regime
expectancy suppressor to ACTIVE.

T6 (`regime_expectancy_calibrator.py`) has been running in SHADOW mode: every
gate decision logs what suppression WOULD have done (👁️ [SHADOW] lines +
`regime_suppression` field in confidence_gate_log) without changing anything.

This script:
  1. Prints the current expectancy table — every actionable cell
     (eff_n >= min) with its weighted mean R and SKIP/REDUCE verdict.
  2. Replays the shadow record: how many live decisions WOULD have been
     suppressed, and — for the ones with tracked outcomes — whether the
     suppressor would have dodged losers (the flip-validation signal).
  3. --flip --apply  : sets mode=active (gate enforces SKIP/REDUCE)
     --shadow --apply: reverts to shadow
     Mode is read by the gate at startup and after the daily 16:35 refresh —
     RESTART THE BACKEND for an immediate effect.

Usage (repo root):
  python3 scripts/t6_flip.py                # audit only
  python3 scripts/t6_flip.py --flip --apply
"""
import argparse
import os
import sys
from collections import defaultdict
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


def summarize_shadow(rows):
    """Pure: aggregate shadow suppression records from confidence_gate_log.

    rows: [{regime_suppression: {action, matched_key|canonical_setup, band},
            outcome_tracked, trade_outcome}, ...]
    Returns {(key, action): {n, tracked, wins, losses}} keyed for printing.
    """
    agg = defaultdict(lambda: {"n": 0, "tracked": 0, "wins": 0, "losses": 0})
    for r in rows:
        sup = r.get("regime_suppression") or {}
        action = sup.get("action")
        if action not in ("SKIP", "REDUCE"):
            continue
        key = sup.get("matched_key") or (
            f"{sup.get('canonical_setup')}|{sup.get('band')}")
        a = agg[(key, action)]
        a["n"] += 1
        if r.get("outcome_tracked"):
            a["tracked"] += 1
            if r.get("trade_outcome") == "win":
                a["wins"] += 1
            elif r.get("trade_outcome") == "loss":
                a["losses"] += 1
    return dict(agg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--flip", action="store_true", help="set mode=active")
    ap.add_argument("--shadow", action="store_true", help="revert to shadow")
    ap.add_argument("--apply", action="store_true", help="write the mode change")
    args = ap.parse_args()

    env = load_env(ENV_PATH)
    mongo_url = env.get("MONGO_URL") or os.environ.get("MONGO_URL")
    db_name = env.get("DB_NAME") or os.environ.get("DB_NAME", "tradecommand")
    if not mongo_url:
        print("ERROR: MONGO_URL not found in backend/.env or environment")
        sys.exit(1)
    from pymongo import MongoClient
    db = MongoClient(mongo_url, serverSelectionTimeoutMS=10000)[db_name]

    col = db["setup_regime_expectancy"]
    cfg = col.find_one({"_id": "config"}) or {}
    table = col.find_one({"_id": "current"}) or {}
    cells = table.get("cells") or {}
    params = table.get("params") or {}
    min_eff_n = params.get("min_eff_n", 25.0)
    hard_r = params.get("hard_r", -0.50)
    soft_r = params.get("soft_r", -0.12)

    print(f"\n=== T6 STATUS ===")
    print(f"mode: {cfg.get('mode', 'shadow')} | table cells: {table.get('cell_count', len(cells))} "
          f"| refreshed: {table.get('computed_at', table.get('updated_at', '?'))}")
    print(f"thresholds: SKIP @ R<={hard_r} | REDUCE @ R<={soft_r} | min_eff_n={min_eff_n}")

    print(f"\n=== ACTIONABLE CELLS (eff_n >= {min_eff_n}) ===\n")
    actionable = []
    for key, c in cells.items():
        r = c.get("weighted_mean_r")
        n = c.get("eff_n") or 0.0
        if r is None or n < min_eff_n:
            continue
        action = "SKIP" if r <= hard_r else ("REDUCE" if r <= soft_r else "ok")
        actionable.append((key, r, n, action))
    actionable.sort(key=lambda x: x[1])
    print(f"{'cell':<48} {'wR':>7} {'eff_n':>6}  verdict")
    for key, r, n, action in actionable:
        mark = {"SKIP": "⛔ SKIP", "REDUCE": "⚠ REDUCE", "ok": ""}[action]
        print(f"{key:<48} {r:>+7.2f} {n:>6.0f}  {mark}")
    n_skip = sum(1 for a in actionable if a[3] == "SKIP")
    n_reduce = sum(1 for a in actionable if a[3] == "REDUCE")
    print(f"\n{len(actionable)} actionable cells → {n_skip} SKIP, {n_reduce} REDUCE, "
          f"{len(actionable) - n_skip - n_reduce} pass")

    print("\n=== SHADOW REPLAY (confidence_gate_log) ===\n")
    rows = list(db["confidence_gate_log"].find(
        {"regime_suppression.action": {"$in": ["SKIP", "REDUCE"]}},
        {"_id": 0, "regime_suppression": 1, "outcome_tracked": 1,
         "trade_outcome": 1}).limit(20000))
    agg = summarize_shadow(rows)
    if not agg:
        print("No shadow suppression records found — the gate has not seen any")
        print("decision land in a suppressible cell yet. Flipping is still safe")
        print("(the suppressor only acts on cells with eff_n >= min), but there")
        print("is no replay evidence to validate against.")
    else:
        print(f"{'cell':<48} {'act':<7} {'n':>5} {'trk':>4} {'win':>4} {'loss':>5}")
        tot_n = tot_loss = tot_win = 0
        for (key, action), a in sorted(agg.items(), key=lambda kv: -kv[1]["n"]):
            print(f"{key:<48} {action:<7} {a['n']:>5} {a['tracked']:>4} "
                  f"{a['wins']:>4} {a['losses']:>5}")
            tot_n += a["n"]
            tot_win += a["wins"]
            tot_loss += a["losses"]
        print(f"\nTotal would-suppress: {tot_n} decisions | tracked outcomes: "
              f"{tot_win} wins / {tot_loss} losses")
        if tot_loss > tot_win:
            print("→ Shadow evidence SUPPORTS the flip (suppressor dodges more losers than winners).")
        elif tot_win > tot_loss:
            print("→ ⚠ Shadow evidence is AGAINST the flip — suppressed cells were net winners. Review before flipping.")

    if args.flip or args.shadow:
        target = "active" if args.flip else "shadow"
        if not args.apply:
            print(f"\n(dry run — add --apply to set mode={target})")
            return
        col.update_one(
            {"_id": "config"},
            {"$set": {"mode": target,
                      "updated_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True)
        print(f"\nmode set to '{target}'. RESTART THE BACKEND for immediate effect")
        print("(otherwise the gate picks it up at the daily 16:35 ET refresh):")
        print("  ./start_backend.sh --force")
        print("Verify after restart:  grep 'regime expectancy' /tmp/backend.log | head -3")


if __name__ == "__main__":
    main()
