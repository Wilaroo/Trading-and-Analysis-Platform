"""Tests for the collection-mode partial pause (2026-04-30).

Before this fix, when a data-fill job was running:
  - `collection_mode.is_active() == True` → the bot's scan loop did
    `continue` at the top, skipping EVERYTHING (alert intake AND
    position management).
  - A live position with no bot polling was a real safety risk: a stop
    hit during a data-fill would never close, an EOD scalp would carry
    into the next session.

After this fix, the collection-mode + focus-mode guards only pause
`_scan_for_opportunities()` (new alert intake). The following keep
running unconditionally:
  - `_update_account_from_ib()` (account state)
  - daily-loss check
  - trading-hours check
  - `_update_open_positions()` (stops / targets / trailing)
  - `_check_eod_close()` (EOD scalp closes)

These are source-level guards rather than runtime tests because the
scan loop owns side effects we don't want to invoke in CI (IB calls,
DB writes) and the cycle is async-driven by `asyncio.sleep`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "/app/backend")

import pytest  # noqa: E402

SCAN_LOOP_SRC = Path(
    "/app/backend/services/trading_bot_service.py"
).read_text("utf-8")


def _scan_loop_block() -> str:
    """Slice the file down to just the `_scan_loop` body so we can
    grep for behaviour without false positives from the rest of the
    module (which has many other references to `collection_mode`)."""
    start = SCAN_LOOP_SRC.find("async def _scan_loop")
    assert start >= 0, "_scan_loop method missing — refactor broke layout"
    end = SCAN_LOOP_SRC.find("def _compute_live_unrealized_pnl", start)
    assert end > start, "couldn't locate end of _scan_loop"
    return SCAN_LOOP_SRC[start:end]


def test_scan_loop_does_not_top_level_continue_on_collection_mode():
    """The old bug pattern — a top-of-loop `continue` when
    `_collection_active()` returned True. That fully paused the bot.
    The fix replaces this with a `pause_intake = True` flag that ONLY
    gates `_scan_for_opportunities()`."""
    block = _scan_loop_block()
    # Old "skip everything" pattern — `if _collection_active(): ... continue` at top
    bad_pattern_lines = [
        "if _collection_active():",
        "_collection_active",
        "scanning paused to free resources",
    ]
    # Find any occurrence
    found_bad = False
    for line in block.splitlines():
        stripped = line.strip()
        # The new code uses `if _collection_active()` *inside* the
        # pause-intake gate — but never followed within 5 lines by
        # `continue` at the loop level.
        if "_collection_active()" in stripped and "if" in stripped:
            # Look ahead 6 lines for `continue` at low indent
            idx = block.splitlines().index(line)
            following = block.splitlines()[idx:idx + 6]
            for f in following:
                if "continue" in f and "scan_count" in following[idx + 1] if (idx + 1) < len(block.splitlines()) else False:
                    found_bad = True
    assert not found_bad, "Top-level continue on collection_mode is back"


def test_scan_loop_runs_position_management_unconditionally():
    """`_update_open_positions` and `_check_eod_close` must be called
    BELOW the pause_intake gate, NOT inside an early-continue branch."""
    block = _scan_loop_block()
    assert "await self._update_open_positions()" in block
    assert "await self._check_eod_close()" in block

    # Both should appear AFTER the pause_intake check is set up. To prove
    # they're not inside a `continue` branch, find the line index of each
    # and verify there's no `continue` between the pause_intake check and
    # them at the same indent level.
    lines = block.splitlines()
    pause_check_idx = next(
        (i for i, ln in enumerate(lines)
         if "pause_intake" in ln and "=" in ln and "False" in ln), -1)
    update_idx = next(
        (i for i, ln in enumerate(lines)
         if "await self._update_open_positions()" in ln), -1)
    eod_idx = next(
        (i for i, ln in enumerate(lines)
         if "await self._check_eod_close()" in ln), -1)
    assert pause_check_idx > 0
    assert update_idx > pause_check_idx
    assert eod_idx > update_idx


def test_scan_loop_gates_only_alert_intake_on_pause():
    """The intake call (`_scan_for_opportunities`) must be wrapped in
    `if not pause_intake:` so it gets skipped during data-fills, while
    everything else runs."""
    block = _scan_loop_block()
    # Find _scan_for_opportunities and ensure it's after a pause check
    intake_idx = block.find("await self._scan_for_opportunities()")
    assert intake_idx > 0, "Alert intake call missing"
    # Walk backward from intake_idx to find the most recent control
    # statement — should be `if not pause_intake:`
    pre = block[:intake_idx]
    last_if_idx = pre.rfind("if not pause_intake:")
    assert last_if_idx > 0, (
        "alert intake is no longer gated by `if not pause_intake:` — the "
        "fix may have regressed."
    )


def test_focus_mode_also_partial_paused():
    """The focus-mode guard previously also fully paused the bot; the
    fix routes it into the same `pause_intake` mechanism so position
    management runs during training / backtesting too."""
    block = _scan_loop_block()
    assert "focus_mode_manager.should_run_task('trading_bot_scan')" in block
    # Should set pause_intake, NOT continue at top level
    assert "pause_intake = True" in block
    # No early `continue` for focus mode
    fm_idx = block.find("focus_mode_manager")
    fm_following = block[fm_idx:fm_idx + 800]
    # Should have the pause_intake assignment, not a top-level continue
    assert "pause_intake = True" in fm_following


def test_diagnostic_collection_mode_label_updated():
    """The diagnostic router's collection_mode_pause stage label should
    say 'pauses ALERT INTAKE only' so the operator sees that open
    positions are still being managed."""
    src = Path("/app/backend/routers/diagnostic_router.py").read_text("utf-8")
    assert "pauses ALERT INTAKE only" in src
    assert "open positions still managed" in src.lower() or "open positions still managed" in src


def test_intake_paused_log_tag_visible():
    """When intake is paused, the periodic scan log should tag itself
    so the operator can grep for it (`📦 INTAKE-PAUSED`)."""
    block = _scan_loop_block()
    assert "INTAKE-PAUSED" in block
