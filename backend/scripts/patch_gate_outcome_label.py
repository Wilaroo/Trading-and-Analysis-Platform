#!/usr/bin/env python3
"""
patch_gate_outcome_label.py  (2026-06-10)

Idempotent patcher for the GAP-5 outcome-label bug in
services/ai_modules/confidence_gate.py.

The primary genuine-close path passes "won"/"lost"/"breakeven" into the gate,
but gate_calibrator only counts "win"/"loss" -> the dominant feed is recorded
yet invisible to calibration. This inserts a canonicalization block at the top
of ConfidenceGate.record_trade_outcome so {won,win}->win, {lost,loss}->loss,
everything else->scratch, regardless of caller vocabulary.

Run on the DGX:
    cd /app/backend && python scripts/patch_gate_outcome_label.py
    (then) sudo supervisorctl restart backend
"""
import os
import sys

TARGET = os.path.join(
    os.path.dirname(__file__), "..", "services", "ai_modules", "confidence_gate.py"
)
TARGET = os.path.abspath(TARGET)

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

        # GAP-5 fix (2026-06-10): normalize outcome vocabulary at this single
        # boundary. The primary genuine-close path
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

MARKER = "GAP-5 fix (2026-06-10): normalize outcome vocabulary"


def main():
    with open(TARGET, "r") as f:
        src = f.read()

    if MARKER in src:
        print(f"[skip] Already patched: {TARGET}")
        return 0

    if ANCHOR not in src:
        print("[ERROR] Anchor block not found — the file may already differ from")
        print("        the expected source. Aborting (no changes made).")
        print("        Manually add the canonicalization block at the top of")
        print("        ConfidenceGate.record_trade_outcome instead.")
        return 1

    src = src.replace(ANCHOR, REPLACEMENT, 1)
    with open(TARGET, "w") as f:
        f.write(src)
    print(f"[ok] Patched {TARGET}")
    print("     Now run: sudo supervisorctl restart backend")
    return 0


if __name__ == "__main__":
    sys.exit(main())
