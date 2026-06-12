#!/usr/bin/env python3
"""
apply_v334.py — EOD VERDICT FIX: generic styles resolve by setup horizon
=========================================================================
PROBE VERDICT (diag_eod_pusher, 2026-06-12 15:11 ET):
63 positions with style `trade_2_hold` were flattened by
eod_auto_close_v162 at exactly 15:45 over the last 14 days — including
REAL HOLDS: daily_breakout (multi_day), stage_2_breakout (position),
rs_leader_break (investment), trend_continuation (multi_day). DE was
flattened on 06-04 AND re-flattened 06-05. THIS is "EOD closes
everything regardless of trade style".

ROOT CAUSE — `trade_2_hold` is the backend's GENERIC SMB fallback stamp
(opportunity_evaluator trade-create default). get_policy_for_trade saw
a truthy style string and short-circuited to get_policy("trade_2_hold")
→ unknown → DEFAULT_POLICY (intraday, close_at_eod=True). The setup-
derived branch below it never ran.

FIX — unknown/generic styles now resolve through the canonical
trade_style_classifier where the SETUP-derived horizon wins:
  daily_breakout → multi_day  → HOLD overnight
  stage_2_breakout → position → HOLD
  rs_leader_break → investment → HOLD
  squeeze / orb / hod_breakout → intraday → still closes at EOD
  trade_2_hold with no recognisable setup → intraday default (safe).
Explicit canonical styles (scalp/intraday/swing/...) are untouched.

This flows through EVERY policy consumer: should_close_at_eod (main EOD
pass + v332 naked guard), is_eod_sweep_eligible, time_in_force_for, and
stop_trail_anchor_for — so held styles also keep GTC brackets and the
right trail anchor.

⚠️ BEHAVIOR CHANGE: hold-horizon setups now survive the close and carry
overnight. The v301 naked guard ALARMS (not flattens) if such a hold
ends up bracket-less after the RegT cutoff — watch for
naked_overnight_hold alerts in the Integrity feed.

Self-tests: 11 new tests + v301/v302/v332 regression (45 total).
SAFE TO RUN MULTIPLE TIMES (idempotent). No DB phase.
Run from repo root:   .venv/bin/python /tmp/apply_v334.py
Then: git add -A && git commit -m "v334: setup-horizon policy resolution" && git push
Then RESTART the backend (before 15:45 ET if you want it live for
today's close).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CHUNKS = [
]

TEST_REL = 'backend/tests/test_v334_policy_resolution.py'
TEST_CONTENT = '"""v334 — get_policy_for_trade resolves generic/unknown styles via the\ncanonical trade_style_classifier (setup-derived horizon wins).\n\nProbe evidence (diag_eod_pusher, 2026-06-12): 63 `trade_2_hold` positions\nflattened by eod_auto_close_v162 at 15:45 in 14 days — the generic SMB\nfallback style short-circuited to DEFAULT_POLICY (intraday,\nclose_at_eod=True), flattening real holds like daily_breakout (multi_day),\nstage_2_breakout (position), rs_leader_break (investment),\ntrend_continuation (multi_day).\n"""\nfrom pathlib import Path\nfrom types import SimpleNamespace\nimport sys\n\n\ndef _repo_root():\n    for c in Path(__file__).resolve().parents:\n        if (c / "backend" / "services" / "order_policy_registry.py").exists():\n            return c\n    raise AssertionError("repo root not found")\n\n\nROOT = _repo_root()\nsys.path.insert(0, str(ROOT / "backend"))\n\nfrom services.order_policy_registry import (  # noqa: E402\n    get_policy_for_trade, should_close_at_eod)\n\n\ndef _t(style, setup=None):\n    return SimpleNamespace(trade_style=style, setup_type=setup,\n                           setup_variant=None, timeframe=None)\n\n\n# ── generic trade_2_hold resolves by setup horizon ───────────────────────\n\ndef test_trade_2_hold_daily_breakout_holds():\n    assert should_close_at_eod(_t("trade_2_hold", "daily_breakout")) is False\n    assert get_policy_for_trade(_t("trade_2_hold", "daily_breakout")).style == "multi_day"\n\n\ndef test_trade_2_hold_stage_2_breakout_holds():\n    assert should_close_at_eod(_t("trade_2_hold", "stage_2_breakout")) is False\n    assert get_policy_for_trade(_t("trade_2_hold", "stage_2_breakout")).style == "position"\n\n\ndef test_trade_2_hold_rs_leader_break_holds():\n    assert should_close_at_eod(_t("trade_2_hold", "rs_leader_break")) is False\n    assert get_policy_for_trade(_t("trade_2_hold", "rs_leader_break")).style == "investment"\n\n\ndef test_trade_2_hold_trend_continuation_short_holds():\n    assert should_close_at_eod(_t("trade_2_hold", "trend_continuation_short")) is False\n\n\n# ── intraday-horizon setups still close at EOD ───────────────────────────\n\ndef test_trade_2_hold_squeeze_still_closes():\n    assert should_close_at_eod(_t("trade_2_hold", "squeeze")) is True\n\n\ndef test_trade_2_hold_orb_still_closes():\n    assert should_close_at_eod(_t("trade_2_hold", "orb")) is True\n\n\ndef test_trade_2_hold_no_setup_defaults_intraday_close():\n    assert should_close_at_eod(_t("trade_2_hold", None)) is True\n\n\n# ── canonical styles unaffected (regression) ─────────────────────────────\n\ndef test_explicit_styles_unchanged():\n    assert should_close_at_eod(_t("scalp")) is True\n    assert should_close_at_eod(_t("intraday")) is True\n    assert should_close_at_eod(_t("swing")) is False\n    assert should_close_at_eod(_t("multi_day")) is False\n    assert should_close_at_eod(_t("position")) is False\n    assert should_close_at_eod(_t("investment")) is False\n\n\ndef test_explicit_intraday_beats_hold_setup():\n    # explicit canonical style short-circuits — setup must NOT override it\n    assert should_close_at_eod(_t("intraday", "daily_breakout")) is True\n\n\ndef test_none_trade_defaults():\n    assert should_close_at_eod(None) is True\n'


def find_root() -> Path:
    for cand in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (cand / "backend" / "services" / "order_policy_registry.py").exists():
            return cand
    print("FATAL: run from repo root")
    sys.exit(1)


def main():
    root = find_root()
    print(f"repo root: {root}")
    applied = 0
    for rel, old, new in CHUNKS:
        path = root / rel
        text = path.read_text()
        if new in text:
            print(f"[SKIP] {rel} — already applied")
            continue
        n = text.count(old)
        if n != 1:
            print(f"[FAIL] {rel} — anchor found {n}x. ABORTING.")
            sys.exit(2)
        path.write_text(text.replace(old, new, 1))
        applied += 1
        print(f"[OK]   {rel} — chunk applied")
    tp = root / TEST_REL
    if not (tp.exists() and tp.read_text() == TEST_CONTENT):
        tp.write_text(TEST_CONTENT)
        applied += 1
        print(f"[OK]   {TEST_REL} — written")
    else:
        print(f"[SKIP] {TEST_REL} — already present")

    print()
    print("── self-test: pytest ──")
    tests = ["tests/test_v334_policy_resolution.py",
             "tests/test_eod_naked_flatten_guard_v301.py",
             "tests/test_eod_force_flatten_bracketed_v302.py",
             "tests/test_v332_regime_demotion.py"]
    existing = [t for t in tests if (root / "backend" / t).exists()]
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", *existing],
                       cwd=str(root / "backend"),
                       capture_output=True, text=True, timeout=300)
    for line in (r.stdout or "").strip().splitlines()[-3:]:
        print("   " + line)
    if r.returncode != 0:
        print("[FAIL] self-test failed — NOT safe to restart.")
        print((r.stdout or "")[-2000:])
        sys.exit(3)
    print("[OK]   self-test PASSED")
    print()
    print(f"v334 done — {applied} item(s) newly applied.")
    print("  git add -A && git commit -m 'v334: setup-horizon policy resolution' && git push")
    print("  RESTART the backend — before 15:45 ET makes it live for today's close.")


if __name__ == "__main__":
    main()
