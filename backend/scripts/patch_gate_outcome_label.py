#!/usr/bin/env python3
"""
patch_gate_outcome_label.py  —  v19.34.311  (2026-06-10)

Idempotent patcher for the GAP-5 outcome-label bug in
services/ai_modules/confidence_gate.py.

The primary genuine-close path passes "won"/"lost"/"breakeven" into the gate,
but gate_calibrator only counts "win"/"loss" -> the dominant outcome feed is
recorded yet invisible to calibration, so every score bucket reads ~0% win-rate
and the auto-calibrator falls back to a STRICTER threshold than the static
defaults. This inserts a canonicalization block at the top of
ConfidenceGate.record_trade_outcome so {won,win}->win, {lost,loss}->loss,
everything else->scratch, regardless of caller vocabulary.

NOT a safety-critical close path (this is a learning-loop write — Journey 1
step 6, not the close spine), so an in-place edit is appropriate here.

Run on the DGX (per AGENTS.md §2):
    cd ~/Trading-and-Analysis-Platform/backend && \
      .venv/bin/python scripts/patch_gate_outcome_label.py
    (then)  cd .. && ./start_backend.sh --force
"""
import os
import sys

TARGET = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "services", "ai_modules", "confidence_gate.py"
))

ANCHOR = """        if self._db is None:
            return False
            
        try:
            result = self._db["confidence_gate_log"].find_one_and_update(
                {
                    "symbol": symbol,
                    "setup_type": setup_type,
                    "outcome_tracked": False,
                },"""

REPLACEMENT = """        if self._db is None:
            return False

        # v19.34.311 (GAP-5 fix, 2026-06-10): normalize outcome vocabulary at
        # this single boundary. The primary genuine-close path
        # (position_manager -> learning_loop_service.record_trade_outcome)
        # passes "won"/"lost"/"breakeven", while trade_journal passes
        # "win"/"loss"/"scratch". gate_calibrator counts ONLY "win"/"loss", so
        # the dominant feed was silently bucketed as scratches -> every score
        # bucket read ~0% win-rate -> calibrator fell back to a STRICTER
        # threshold than the defaults. Canonicalize here so the loop learns.
        _o = str(outcome or "").strip().lower()
        if _o in ("win", "won", "w"):
            outcome = "win"
        elif _o in ("loss", "lost", "lose", "l"):
            outcome = "loss"
        else:  # breakeven / scratch / be / flat / unknown
            outcome = "scratch"

        try:
            result = self._db["confidence_gate_log"].find_one_and_update(
                {
                    "symbol": symbol,
                    "setup_type": setup_type,
                    "outcome_tracked": False,
                },"""

MARKER = "v19.34.311 (GAP-5 fix, 2026-06-10): normalize outcome vocabulary"


def main():
    with open(TARGET, "r") as f:
        src = f.read()

    if MARKER in src:
        print(f"[skip] Already patched (v19.34.311): {TARGET}")
        return 0

    if ANCHOR not in src:
        print("[ERROR] Anchor block not found — the file already differs from the")
        print("        expected source. Aborting (no changes made). Manually add the")
        print("        canonicalization block at the top of")
        print("        ConfidenceGate.record_trade_outcome instead.")
        return 1

    src = src.replace(ANCHOR, REPLACEMENT, 1)
    with open(TARGET, "w") as f:
        f.write(src)
    print(f"[ok] Patched (v19.34.311): {TARGET}")
    print("     Now run:  cd .. && ./start_backend.sh --force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
