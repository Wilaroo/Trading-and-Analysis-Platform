#!/usr/bin/env python3
"""
diag_gate_calibration_audit.py  —  v19.34.311  (2026-06-10)

Investigation deliverable for the gate-conservatism work:
  B) Is the auto-calibration loop actually learning, and why is it stricter
     than the static defaults?  (outcome-label integrity + threshold drift)
  C) Quantify the "dark budget" — additive layers that contribute ZERO because
     their model is below its accuracy floor / mode-collapsed / has no news /
     has no Phase-8 ensemble.

READ-ONLY by default. Pass `--apply-relabel` to perform the one-time historical
relabel of confidence_gate_log.trade_outcome (won->win, lost->loss,
breakeven->scratch) so the calibrator can finally see the existing outcomes.

Reads MONGO_URL / DB_NAME from backend/.env (DB is `tradecommand`).

Run on the DGX (per AGENTS.md §2 — use the venv python, not `python`):
    cd ~/Trading-and-Analysis-Platform/backend && \
      .venv/bin/python scripts/diag_gate_calibration_audit.py
    (then, once reviewed)
    .venv/bin/python scripts/diag_gate_calibration_audit.py --apply-relabel
"""
import os
import re
import sys
from collections import Counter, defaultdict

from pymongo import MongoClient

# --- env (no hardcoded creds) ---
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")
APPLY = "--apply-relabel" in sys.argv

GATE_DEFAULTS = {  # static fallbacks live in confidence_gate.py
    "aggressive": 28, "normal": 38, "cautious": 50, "defensive": 60,
}

# Signature substrings that mark a layer as DARK (contributed 0) in reasoning[]
DARK_MARKERS = {
    "TFT": "TFT signal IGNORED",
    "CNN-LSTM": "CNN-LSTM signal IGNORED",
    "VAE": "VAE signal IGNORED",
    "FinBERT(no-news)": "FinBERT sentiment: no data",
    "Ensemble(missing)": "Ensemble meta-labeler unavailable",
    "No-models": "No trained models for this setup",
}
# Signature substrings that mark a layer as ACTIVE (fired with points)
ACTIVE_MARKERS = {
    "ModelConsensus": "Model consensus",
    "LivePred": "Live ",
    "Quality": "Quality score",
    "CNNvisual": "CNN visual analysis",
    "TFT": "TFT ",
    "VAE": "VAE detects",
    "CNN-LSTM": "CNN-LSTM temporal",
    "EnsembleMeta": "Ensemble meta-labeler",
    "FinBERT": "FinBERT sentiment",
    "Learning": "Historical",
}


def hr(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def main():
    if not MONGO_URL or not DB_NAME:
        print("ERROR: MONGO_URL / DB_NAME not set in backend/.env")
        sys.exit(1)

    db = MongoClient(MONGO_URL, serverSelectionTimeoutMS=8000)[DB_NAME]
    col = db["confidence_gate_log"]
    total = col.count_documents({})
    hr(f"CONFIDENCE_GATE_LOG  (total docs: {total:,})")
    if total == 0:
        print("No gate logs found — nothing to audit.")
        return

    # ---- (B1) outcome-label integrity ----
    hr("B1) OUTCOME LABEL INTEGRITY  (the calibrator only counts 'win'/'loss')")
    tracked = col.count_documents({"outcome_tracked": True})
    untracked = total - tracked
    print(f"  outcome_tracked=True : {tracked:,}")
    print(f"  outcome_tracked!=True: {untracked:,}")
    label_dist = Counter()
    for d in col.find({"outcome_tracked": True}, {"_id": 0, "trade_outcome": 1}):
        label_dist[str(d.get("trade_outcome"))] += 1
    print("  trade_outcome distribution (tracked docs):")
    for k, v in label_dist.most_common():
        flag = ""
        if k in ("won", "lost", "breakeven"):
            flag = "  <-- MISLABELED (invisible to calibrator!)"
        print(f"     {k:>12}: {v:,}{flag}")
    mislabeled = label_dist["won"] + label_dist["lost"] + label_dist["breakeven"]
    print(f"\n  => {mislabeled:,} outcomes are mislabeled and NOT counted as win/loss.")

    # ---- (B2) current calibrated thresholds vs defaults ----
    hr("B2) GATE_CALIBRATION  (is the learned threshold stricter than default?)")
    cal = db["gate_calibration"].find_one({"_id": "current"})
    if not cal:
        print("  No gate_calibration doc — gate is running on STATIC defaults.")
    else:
        print(f"  success={cal.get('success')}  outcomes={cal.get('total_outcomes')}")
        print(f"  base_go={cal.get('base_go_threshold')}  base_reduce={cal.get('base_reduce_threshold')}")
        th = cal.get("thresholds", {})
        for mode, dflt in GATE_DEFAULTS.items():
            go = (th.get(mode) or {}).get("go")
            if go is not None:
                arrow = "STRICTER" if go > dflt else ("looser" if go < dflt else "same")
                print(f"     {mode:>10}: learned GO={go}  vs default {dflt}  -> {arrow}")

    # ---- (B3) trading-mode distribution ----
    hr("B3) TRADING-MODE DISTRIBUTION  (why 63% cautious/defensive?)")
    mode_dist = Counter()
    for d in col.find({}, {"_id": 0, "trading_mode": 1}).limit(20000):
        mode_dist[str(d.get("trading_mode", "?"))] += 1
    seen = sum(mode_dist.values())
    for k, v in mode_dist.most_common():
        print(f"     {k:>10}: {v:,} ({100*v/seen:.1f}%)")

    # ---- (C) dark-budget: how often each layer is OFF ----
    hr("C) DARK-BUDGET  (additive layers that contributed ZERO)")
    sample_n = 8000
    dark = Counter()
    active = Counter()
    decision_dist = Counter()
    score_vals = []
    for d in col.find({}, {"_id": 0, "reasoning": 1, "decision": 1, "confidence_score": 1}).sort("timestamp", -1).limit(sample_n):
        decision_dist[str(d.get("decision"))] += 1
        sc = d.get("confidence_score")
        if isinstance(sc, (int, float)):
            score_vals.append(sc)
        blob = " || ".join(d.get("reasoning", []) or [])
        for name, marker in DARK_MARKERS.items():
            if marker in blob:
                dark[name] += 1
        for name, marker in ACTIVE_MARKERS.items():
            if marker in blob:
                active[name] += 1
    n = sum(decision_dist.values()) or 1
    print(f"  sampled {n:,} most-recent decisions")
    print("  decision mix:")
    for k, v in decision_dist.most_common():
        print(f"     {k:>8}: {v:,} ({100*v/n:.1f}%)")
    if score_vals:
        score_vals.sort()
        med = score_vals[len(score_vals)//2]
        p75 = score_vals[int(len(score_vals)*0.75)]
        print(f"  confidence_score: median={med}  p75={p75}  max={score_vals[-1]}")
    print("\n  LAYER DARK-RATE (contributed 0 / was gated off):")
    for name in DARK_MARKERS:
        v = dark[name]
        print(f"     {name:>18}: {v:,} ({100*v/n:.1f}%)")
    print("\n  LAYER ACTIVE-RATE (appeared in reasoning at all):")
    for name in ACTIVE_MARKERS:
        v = active[name]
        print(f"     {name:>18}: {v:,} ({100*v/n:.1f}%)")

    # ---- one-time relabel ----
    hr("RELABEL  (won->win, lost->loss, breakeven->scratch)")
    if not APPLY:
        print(f"  DRY-RUN. {mislabeled:,} docs WOULD be relabeled.")
        print("  Re-run with --apply-relabel to unlock these outcomes for calibration.")
    else:
        r1 = col.update_many({"trade_outcome": "won"}, {"$set": {"trade_outcome": "win"}})
        r2 = col.update_many({"trade_outcome": "lost"}, {"$set": {"trade_outcome": "loss"}})
        r3 = col.update_many({"trade_outcome": "breakeven"}, {"$set": {"trade_outcome": "scratch"}})
        print(f"  won->win:        {r1.modified_count:,}")
        print(f"  lost->loss:      {r2.modified_count:,}")
        print(f"  breakeven->scr.: {r3.modified_count:,}")
        print("  Done. Next scheduled gate_calibration (or a manual calibrate()) will")
        print("  now see real win/loss buckets.")

    print("\nDONE.\n")


if __name__ == "__main__":
    main()
