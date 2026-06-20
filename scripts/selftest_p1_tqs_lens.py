#!/usr/bin/env python3
"""
selftest_p1_tqs_lens.py — OFFLINE, READ-ONLY proof that the P1 patch flips the
TQS scoring LENS to the pattern's intrinsic style (NOT the liquidity-inflated
stamp). No DB, no IB, no network, no market needed.

HOW IT WORKS (gold-standard unit test):
  - Instantiates the REAL (patched) TQSEngine and runs the REAL calculate_tqs()
    code path, but STUBS the 5 pillar services so no data/network is touched.
  - For each (setup_type, liquidity-stamped trade_style) case it reads back
    result.trade_style (the scoring lens the engine actually used) and
    result.weights_used, then asserts:
       scoring lens == style_of(setup)         (when style_of is a real style)
       scoring lens == stamp                    (for watch triggers / kill-switch)
       weights_used == STYLE_WEIGHTS[lens]      (weight fidelity)

  Run it AFTER `patch_p1_style_pattern.py --apply`. It imports the file from
  disk, so it reflects the patched bytes immediately — no backend restart needed
  for THIS test (a restart is still needed for the live scanner to use it).

Run from repo root with the venv python (AGENTS.md §2):
    .venv/bin/python scripts/selftest_p1_tqs_lens.py
"""
import os
import sys
import asyncio

# ── locate backend on sys.path ──────────────────────────────────────────────
for bd in ("backend", ".", os.path.join(os.path.dirname(__file__), "..", "backend")):
    if os.path.isdir(bd) and os.path.exists(os.path.join(bd, "services", "tqs", "tqs_engine.py")):
        sys.path.insert(0, os.path.abspath(bd))
        break

from services.tqs.tqs_engine import TQSEngine          # noqa: E402
from services.setup_taxonomy import style_of            # noqa: E402

STYLE_WEIGHTS = TQSEngine.STYLE_WEIGHTS


# ── stub pillar scores so calculate_tqs() needs no data/network ──────────────
class _StubScore:
    def __init__(self):
        self.score = 50.0
        self.grade = "C"
        self.factors = []
        self.warnings = []


class _StubSvc:
    async def calculate_score(self, *a, **k):
        return _StubScore()


def _stub_engine():
    eng = TQSEngine()
    eng._setup_service = _StubSvc()
    eng._technical_service = _StubSvc()
    eng._fundamental_service = _StubSvc()
    eng._context_service = _StubSvc()
    eng._execution_service = _StubSvc()
    return eng


def expected_lens(setup, stamped, flag_on=True):
    """Mirror the patch's lens-selection so the test is self-checking."""
    if not flag_on:
        return stamped
    try:
        ps = (style_of(setup) or "").strip().lower()
    except Exception:
        ps = ""
    if ps and ps != "unknown" and ps in STYLE_WEIGHTS:
        return ps
    return stamped


# (setup_type, liquidity-stamped trade_style, note)
FLIP_CASES = [
    ("breakdown_confirmed", "intraday", "SSOT fix: stamp=intraday -> pattern=multi_day"),
    ("daily_breakout",      "intraday", "daily_breakout -> multi_day"),
    ("vwap_fade",           "intraday", "vwap_fade -> scalp"),
    ("stage_2_breakout",    "intraday", "stage_2_breakout -> position"),
    ("orb",                 "intraday", "orb stays intraday (sanity, no change)"),
]
WATCH_CASES = [
    ("approaching_breakout", "intraday", "WATCH trigger -> keeps stamp (no relabel)"),
    ("carry_forward_watch",  "swing",    "WATCH carry-over -> keeps stamp"),
]


async def run_case(eng, setup, stamped, flag_on):
    os.environ["TQS_STYLE_FROM_PATTERN"] = "true" if flag_on else "false"
    res = await eng.calculate_tqs(symbol="TEST", setup_type=setup,
                                  direction="long", trade_style=stamped)
    return res.trade_style, res.weights_used


async def main():
    eng = _stub_engine()
    print("=" * 84)
    print("  P1 SELF-TEST — TQS scoring LENS follows PATTERN, not liquidity stamp")
    print("  (offline · stubbed pillars · reads the patched calculate_tqs path)")
    print("=" * 84)

    fails = 0

    def check(label, setup, stamped, lens, weights, exp):
        nonlocal fails
        lens_ok = (lens == exp)
        wt_ok = (weights == STYLE_WEIGHTS.get(exp))
        flag = "PASS" if (lens_ok and wt_ok) else "FAIL"
        if not (lens_ok and wt_ok):
            fails += 1
        arrow = "==" if stamped == lens else "->"
        print(f"  [{flag}] {setup:22} stamp={stamped:9} {arrow} lens={lens:10} "
              f"(want {exp:10}) wt_ok={wt_ok!s:5} | {label}")

    print("\n  FLIP / SANITY (TQS_STYLE_FROM_PATTERN=on):")
    for setup, stamped, note in FLIP_CASES:
        lens, weights = await run_case(eng, setup, stamped, True)
        check(note, setup, stamped, lens, weights, expected_lens(setup, stamped, True))

    print("\n  WATCH TRIGGERS (style_of=unknown -> stamp kept, never crashes):")
    for setup, stamped, note in WATCH_CASES:
        lens, weights = await run_case(eng, setup, stamped, True)
        check(note, setup, stamped, lens, weights, expected_lens(setup, stamped, True))

    print("\n  KILL-SWITCH (TQS_STYLE_FROM_PATTERN=false -> revert to stamp):")
    setup, stamped = "breakdown_confirmed", "intraday"
    lens, weights = await run_case(eng, setup, stamped, False)
    check("env off -> lens stays liquidity stamp", setup, stamped, lens, weights,
          expected_lens(setup, stamped, False))
    os.environ["TQS_STYLE_FROM_PATTERN"] = "true"  # restore default

    print("\n" + "=" * 84)
    if fails == 0:
        print("  \u2705 ALL PASS — engine is PATCHED: scoring lens = pattern; weights match;")
        print("     watch triggers keep their stamp; env kill-switch reverts cleanly.")
    else:
        print(f"  \u274c {fails} FAIL(s). If lens==stamp on flip cases, the engine is NOT")
        print("     patched (run patch_p1_style_pattern.py --apply first, then re-run).")
    print("=" * 84)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
