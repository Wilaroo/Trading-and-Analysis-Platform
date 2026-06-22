#!/usr/bin/env python3
"""
patch_tqs1_ai_honest_encoding.py
================================
TQS HONESTY FIX #1 — stop scoring an ABSENT AI signal as a 35 penalty.

WHY (proven by diag_tqs.py + diag_tqs_b.py on live DGX, 48h / 1011 alerts):
  context.ai_model is PINNED at 35 ("AI model weakly disagrees") for ~98% of the
  book (990/1011), stdev 0. Confirmed root cause: the timeseries model returns
  no usable forecast for the live universe, so 100% of alerts carry the LiveAlert
  dataclass DEFAULTS — ai_prediction="", ai_confidence=0.0,
  ai_agrees_with_direction=False. Those are all NON-None, so when
  _enrich_alert_with_tqs reads them and passes them to the Context pillar, the
  pillar falls through to the penalising "weakly disagrees -> 35" branch instead
  of its honest neutral 50 ("No model signal"). Absence is scored as a penalty
  on every single alert.

FIX (1 anchored block in backend/services/enhanced_scanner.py,
     _enrich_alert_with_tqs): coerce a "no signal" to None — mirror the v214
  win_rate/EV idiom that already sits a few lines below. When there is no real
  prediction the pillar gets ai_model_direction=None / ai_model_confidence=None /
  ai_model_agrees=None and scores the honest neutral 50. When a REAL forecast
  exists (non-empty direction + >0 confidence) every value flows through
  UNCHANGED — zero behaviour change for real signals.

SAFETY: presentation/scoring-input only; no order/close/bracket/kill-switch path
  touched. Anchored to an exact unique block (count==1) — ABORTS cleanly on
  drift (prints a grep to rebase). Idempotent (marker guard). Writes .bak.
  py_compile-gated. PRE/POST file sha256 printed. --check / --apply / --rollback.

USAGE (on the DGX, from repo root ~/Trading-and-Analysis-Platform):
    curl -sS -o /tmp/patch_tqs1.py https://paste.rs/XXXXX
    .venv/bin/python /tmp/patch_tqs1.py --check     # dry run + py_compile
    .venv/bin/python /tmp/patch_tqs1.py --apply
    ./start_backend.sh --force
    # verify: re-run diag_tqs.py --hours 1 after a fresh scan ->
    #   context.ai_model should move OFF the pinned 35 (absent -> 50).
    .venv/bin/python /tmp/patch_tqs1.py --rollback   # restores .bak
"""

import argparse
import hashlib
import os
import sys
import py_compile

TARGET = "backend/services/enhanced_scanner.py"
BAK = TARGET + ".bak.tqs1"
MARKER = "v19.34.392"  # TQS honesty: AI absent -> None

OLD = """            ai_dir = getattr(alert, 'ai_prediction', None)
            ai_conf = getattr(alert, 'ai_confidence', None)
            if ai_conf is not None:
                ai_conf = ai_conf / 100.0  # Convert 0-100 to 0.0-1.0
            ai_agrees = getattr(alert, 'ai_agrees_with_direction', None)
"""

NEW = """            # v19.34.392 (TQS honesty) — an ABSENT AI signal must read as
            # NEUTRAL, not as a fabricated "weakly disagrees" PENALTY. The
            # LiveAlert dataclass defaults (ai_prediction="", ai_confidence=0.0,
            # ai_agrees_with_direction=False) are all NON-None, so without this
            # coercion the Context pillar scored ai_model=35 for ~100% of the
            # book (diag_tqs: 990/1011 pinned at 35, stdev 0). Mirror the v214
            # win_rate/EV idiom below: coerce "no signal" to None so the pillar
            # falls back to its honest neutral 50. Real forecasts pass through
            # unchanged (non-empty direction + >0 confidence).
            ai_dir = getattr(alert, 'ai_prediction', None) or None
            _ai_conf_raw = getattr(alert, 'ai_confidence', None)
            ai_conf = (_ai_conf_raw / 100.0) if _ai_conf_raw else None  # 0/None -> None
            ai_agrees = getattr(alert, 'ai_agrees_with_direction', None)
            if not ai_dir or ai_conf is None:
                ai_agrees = None
"""


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _read(path):
    if not os.path.exists(path):
        print(f"ERROR: target not found: {path}")
        print("Run from the repo root (~/Trading-and-Analysis-Platform).")
        sys.exit(2)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _grep_hint():
    print("\n  Rebase hint — send me the live block:")
    print(f"    grep -n -A6 \"ai_dir = getattr(alert, 'ai_prediction'\" {TARGET}")


def cmd_check(src, applied):
    print(f"  target : {TARGET}")
    print(f"  sha256 : {_sha(src.encode())}")
    if applied:
        print("  STATUS : ALREADY PATCHED (marker present) — apply would no-op.")
        return 0
    n = src.count(OLD)
    if n != 1:
        print(f"  ERROR  : anchor block found {n} times (need exactly 1) — DRIFT.")
        _grep_hint()
        return 3
    new_src = src.replace(OLD, NEW, 1)
    print("  anchor : found (count==1) ✓")
    print(f"  POST   : {_sha(new_src.encode())}  (predicted)")
    print("  --check OK. Re-run with --apply to write.")
    return 0


def cmd_apply(src, applied):
    if applied:
        print("  ALREADY PATCHED — no-op.")
        return 0
    n = src.count(OLD)
    if n != 1:
        print(f"  ERROR: anchor block found {n} times (need exactly 1) — DRIFT. Aborting.")
        _grep_hint()
        return 3
    pre = _sha(src.encode())
    new_src = src.replace(OLD, NEW, 1)
    with open(BAK, "w", encoding="utf-8") as f:
        f.write(src)
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(new_src)
    try:
        py_compile.compile(TARGET, doraise=True)
    except py_compile.PyCompileError as e:
        with open(TARGET, "w", encoding="utf-8") as f:
            f.write(src)  # restore
        print(f"  ERROR: py_compile failed, reverted. {e}")
        return 4
    print(f"  PRE  sha256: {pre}")
    print(f"  POST sha256: {_sha(new_src.encode())}")
    print(f"  backup     : {BAK}")
    print("  ✅ APPLIED + py_compile OK. Restart backend, then verify with diag_tqs.py.")
    return 0


def cmd_rollback():
    if not os.path.exists(BAK):
        print(f"  ERROR: no backup at {BAK}")
        return 2
    with open(BAK, "r", encoding="utf-8") as f:
        src = f.read()
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(src)
    os.remove(BAK)
    print(f"  ✅ ROLLED BACK from {BAK}. sha256: {_sha(src.encode())}")
    return 0


def main():
    global TARGET, BAK
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--rollback", action="store_true")
    ap.add_argument("--target", default=TARGET)
    args = ap.parse_args()
    TARGET = args.target
    BAK = TARGET + ".bak.tqs1"

    if args.rollback:
        sys.exit(cmd_rollback())

    src = _read(TARGET)
    applied = (MARKER in src and "or None" in src and "_ai_conf_raw" in src)

    if args.apply:
        sys.exit(cmd_apply(src, applied))
    # default: check
    sys.exit(cmd_check(src, applied))


if __name__ == "__main__":
    main()
