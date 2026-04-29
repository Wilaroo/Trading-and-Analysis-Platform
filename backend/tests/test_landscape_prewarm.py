"""Tests for the after-hours Setup-landscape pre-warm (2026-04-30, P1).

Operator-flagged gap (Q3 in fork):
  - `MarketSetupClassifier.classify` is called on every alert intraday
    but NOT in the after-hours/premarket scan loops.
  - First morning briefing of the day paid the full 200×classify
    latency since the snapshot cache was cold.

Post-fix:
  - `enhanced_scanner._scan_loop` CLOSED branch now also calls
    `_prewarm_setup_landscape()` every after-hours sweep.
  - PREMARKET branch calls it with `force_morning=True`.
  - `eod_generation_service` adds a Saturday 12:00 ET cron job that
    pre-warms the WEEKEND-context snapshot (uses `get_weekly_summary`).

These are source-level guards because the scan loop and BackgroundScheduler
both own side effects (IB calls, asyncio loop, cron worker thread)
that are awkward to invoke in CI.
"""

from __future__ import annotations

from pathlib import Path

SCANNER_SRC = Path(
    "/app/backend/services/enhanced_scanner.py"
).read_text("utf-8")

EOD_SRC = Path(
    "/app/backend/services/eod_generation_service.py"
).read_text("utf-8")


def test_prewarm_method_exists_in_scanner():
    """The new `_prewarm_setup_landscape` method must be defined."""
    assert "async def _prewarm_setup_landscape(" in SCANNER_SRC


def test_prewarm_called_in_after_hours_branch():
    """CLOSED branch (after-hours) must call the pre-warm at the
    same cadence as `_scan_daily_setups`."""
    # Find the CLOSED if-block and assert the call is inside.
    closed_idx = SCANNER_SRC.find("if current_window == TimeWindow.CLOSED:")
    assert closed_idx > 0
    premarket_idx = SCANNER_SRC.find(
        "if current_window == TimeWindow.PREMARKET:", closed_idx
    )
    assert premarket_idx > closed_idx
    closed_block = SCANNER_SRC[closed_idx:premarket_idx]
    assert "await self._prewarm_setup_landscape()" in closed_block


def test_prewarm_called_in_premarket_branch_force_morning():
    """PREMARKET branch must pass force_morning=True so the snapshot
    uses the morning voice even if today happens to be a Sunday."""
    pm_idx = SCANNER_SRC.find("if current_window == TimeWindow.PREMARKET:")
    assert pm_idx > 0
    pm_block = SCANNER_SRC[pm_idx:pm_idx + 1500]
    assert "await self._prewarm_setup_landscape(force_morning=True)" in pm_block


def test_prewarm_picks_weekend_context_on_saturday_sunday():
    """The pre-warm helper must derive context from the ET weekday
    when force_morning is False — Sat/Sun → 'weekend', else 'morning'."""
    block = SCANNER_SRC[
        SCANNER_SRC.find("async def _prewarm_setup_landscape("):
    ]
    # Find the dispatch table
    assert "weekday in (5, 6)" in block, (
        "Pre-warm must select 'weekend' context on Sat (5) and Sun (6)"
    )
    assert 'context = "weekend"' in block
    assert 'context = "morning"' in block


def test_prewarm_invalidates_cache_to_force_fresh_snapshot():
    """`get_setup_landscape_service.invalidate()` must be called
    BEFORE `get_snapshot()` so the pre-warm produces a fresh classify
    rather than re-reading a stale 60s-old snapshot."""
    block = SCANNER_SRC[
        SCANNER_SRC.find("async def _prewarm_setup_landscape("):
    ]
    invalidate_idx = block.find("svc.invalidate()")
    snapshot_idx = block.find("svc.get_snapshot(context=context)")
    assert invalidate_idx > 0
    assert snapshot_idx > 0
    assert invalidate_idx < snapshot_idx, (
        "invalidate() must precede get_snapshot() in the pre-warm flow"
    )


def test_eod_scheduler_registers_saturday_landscape_prewarm():
    """eod_generation_service must register the Saturday 12:00 ET cron job."""
    assert "auto_weekend_landscape_prewarm" in EOD_SRC


def test_saturday_prewarm_uses_weekend_context():
    """The Saturday cron must request the weekend-context snapshot."""
    job_idx = EOD_SRC.find("def _run_weekend_landscape_prewarm():")
    assert job_idx > 0
    # Slice forward up to where the next add_job kicks in
    job_block = EOD_SRC[job_idx:job_idx + 1500]
    assert 'svc.get_snapshot(context="weekend")' in job_block


def test_saturday_prewarm_cron_is_sat_12_et():
    """Cron should be Saturday at 12:00 ET — late-morning so any
    Friday data corrections have settled."""
    block = EOD_SRC[EOD_SRC.find("auto_weekend_landscape_prewarm") - 200:]
    # Look forward to find the registration block
    end = block.find("self.scheduler.start()")
    if end > 0:
        block = block[:end]
    assert "day_of_week='sat'" in block
    assert "hour=12" in block
    assert "minute=0" in block
