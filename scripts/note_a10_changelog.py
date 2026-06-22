#!/usr/bin/env python3
"""
note_a10_changelog.py — prepend the (A10) CHANGELOG entry to memory/CHANGELOG.md
(newest-first). Idempotent. Run via python (NOT a terminal paste).

    PYTHONPATH=backend .venv/bin/python scripts/note_a10_changelog.py
    git add memory/CHANGELOG.md && git commit -m "A10: CHANGELOG note" && git push origin main
"""
import os

ANCHOR = "(A10) — Auto-exec trigger re-validation (drift) gate"
ENTRY = """## 2026-06-22 — (A10) — Auto-exec trigger re-validation (drift) gate (kills the stale/extended daily-setup drip) — SHIPPED
A8's restart/feed guard stopped the INSTANT post-restart burst, but a steady
DRIP of old-created_at stage_2_breakout positions kept auto-executing later in
the session (operator re-ran diag_a9: ~9 new BACKLOGGED entries crept in AFTER
the A8 warm-up finished). ROOT CAUSE (settled by reading _scan_daily_setups +
_maybe_auto_execute_daily): it is NOT a stale-price replay — _scan_daily_setups
REBUILDS each daily-breakout alert every cycle on fresh bars (current_price IS
live). The real failure mode is that trigger_price is the STABLE daily breakout
level, so the detector keeps re-firing every cycle while price stays beyond it,
and _auto_execute_alert enters at an ever-more-EXTENDED live price far past the
clean break. (The old created_at the diag flagged is a dedup/upsert first-seen
labeling artifact — exactly why an alert-AGE gate was the wrong tool.)
FIX (patch_a10, paste.rs/fSYav): a TRIGGER RE-VALIDATION GATE inserted into
_auto_execute_alert right after the A8 guard, before the auto-exec try-block.
Re-fetches the live quote via _get_quote_with_ib_priority(symbol) and SKIPs the
execution when abs(live - trigger)/trigger exceeds AUTO_EXEC_MAX_TRIGGER_DRIFT_PCT
(default 2.0%). Universal: BOTH the intraday and A6 daily callers funnel through
_auto_execute_alert, so one gate covers both. Policy knob
AUTO_EXEC_TRIGGER_DRIFT_POLICY = block | observe | off (default block; observe
logs but still fires; off disables). FAIL-OPEN: no trigger_price / no live quote
/ any error never blocks a valid signal. Span-SHA guarded (A8-block->auto-exec
try span PRE a4b86c98), idempotent, .a10.bak backup, AST-compile gate,
--check/--rollback. Local round-trip: check->apply->idempotent->compile->rollback
IDENTICAL; 7/7 gate-logic cases (block@8%, proceed@1%, observe logs+proceeds,
off proceeds, no-trigger fail-open, custom-threshold block, no-live fail-open).
PRE whole-file 4045078f -> POST b87b0b0f.
VERIFY next RTH (re-run diag_a9_entry_provenance): the late-session drip of
extended/backlogged stage_2_breakout entries should collapse to ~0; any blocked
entry logs "A10 trigger-drift gate (BLOCK)". Tip: deploy in observe mode first
(AUTO_EXEC_TRIGGER_DRIFT_POLICY=observe) for one RTH to size the real drift
distribution, then flip to block. Open follow-ups (unchanged): target_price +
live-mark plumbing for position holds (Issue 2), per-style position cap (Issue 3),
card timestamp/price transparency UI (Task 1).

"""

for cand in ["memory/CHANGELOG.md", os.path.join(os.path.dirname(__file__), "..", "memory", "CHANGELOG.md")]:
    if os.path.isfile(cand):
        p = os.path.abspath(cand)
        c = open(p, encoding="utf-8").read()
        if ANCHOR in c:
            print(f"Idempotent: anchor present in {p} — no change.")
        else:
            open(p, "w", encoding="utf-8").write(ENTRY + c)
            print(f"Prepended (A10) entry to {p}.")
        break
else:
    print("ERROR: memory/CHANGELOG.md not found. Run from repo root.")
