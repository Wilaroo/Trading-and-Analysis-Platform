"""
v19.31.2 (2026-05-04) — regression pin for the AUTO_RECONCILE_AT_BOOT
feature flag.

The feature:
  When `AUTO_RECONCILE_AT_BOOT=true` is set in `backend/.env`, the bot
  fires a `reconcile_orphan_positions(all_orphans=True)` 20s after
  start() so the bot self-claims every IB-only carryover the moment
  the pusher publishes its position snapshot. Means the operator
  literally never sees "RECONCILE 13" in the morning anymore.

  Default OFF (operator opts in by setting the env var). Runs AFTER
  the existing 15s orphan-guard so the emergency stops land first.

These tests pin:
  - Off-by-default (env unset → no reconcile call)
  - On when truthy ("true" / "1" / "yes" / "on" — all variants)
  - Calls reconcile_orphan_positions with all_orphans=True
  - Exceptions during reconcile don't crash bot.start()
  - Stream event emitted when ≥1 position claimed
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ─── Source-level pin ────────────────────────────────────────────────


def test_auto_reconcile_block_present_in_start_method():
    """Catch a refactor that drops the v19.31.1 boot reconcile."""
    import inspect
    from services import trading_bot_service as tbs
    src = inspect.getsource(tbs.TradingBotService.start)
    # Env var name + reconcile method ref + truthy values.
    assert "AUTO_RECONCILE_AT_BOOT" in src
    assert "reconcile_orphan_positions" in src
    assert "all_orphans=True" in src
    # Truthy variants — pinning the exact set so a future refactor that
    # narrows or widens it is visible.
    for variant in ('"1"', '"true"', '"yes"', '"on"'):
        assert variant in src, f"Missing truthy variant {variant!r}"


# ─── Behavior tests ──────────────────────────────────────────────────


@pytest.fixture
def fake_bot():
    """Construct a minimal fake bot exposing only what start() touches.
    We patch start() onto a stub so we can exercise just the auto-
    reconcile branch without booting the entire trading_bot_service."""
    bot = MagicMock()
    bot._running = False
    bot._mode = MagicMock()
    bot._mode.value = "autonomous"
    bot._scan_task = None
    bot.risk_params = MagicMock(
        trading_start_hour=9,
        trading_start_minute=30,
        trading_end_hour=15,
        trading_end_minute=55,
        max_position_pct=2.0,
        max_daily_loss_pct=2.0,
    )
    bot._position_reconciler = MagicMock()
    bot._save_state = AsyncMock()
    bot.reconcile_orphan_positions = AsyncMock(return_value={
        "reconciled": [
            {"symbol": "APH", "trade_id": "t1"},
            {"symbol": "STX", "trade_id": "t2"},
        ],
        "skipped": [],
        "errors": [],
    })
    return bot


def _has_auto_reconcile_task(tasks):
    """Helper: check if any pending task is the bot's startup auto-
    reconcile coro. We match on the exact coro name `_startup_auto_reconcile`
    to avoid false-positive matches on the test function names themselves."""
    for t in tasks:
        try:
            name = t.get_coro().__name__
        except Exception:
            continue
        if name == "_startup_auto_reconcile":
            return True
    return False


@pytest.mark.asyncio
async def test_auto_reconcile_OFF_when_env_unset(monkeypatch, fake_bot):
    """Default behavior — env var not set → no auto-reconcile task."""
    monkeypatch.delenv("AUTO_RECONCILE_AT_BOOT", raising=False)

    from services.trading_bot_service import TradingBotService
    # Re-bind start() bound to our fake_bot.
    start_unbound = TradingBotService.start
    # Patch logger to silence output.
    with patch("services.trading_bot_service.logger"):
        # Need _scan_loop to be a no-op
        fake_bot._scan_loop = AsyncMock()
        # Patch the enhanced_scanner sync block to a no-op
        with patch.dict(sys.modules, {
            "services.enhanced_scanner": MagicMock(get_enhanced_scanner=lambda: None),
            "services.sentcom_service": MagicMock(emit_stream_event=AsyncMock()),
        }):
            await start_unbound(fake_bot)

    # Give the orphan-guard task a chance to be scheduled (but not run)
    pending = [t for t in asyncio.all_tasks() if not t.done()]
    assert not _has_auto_reconcile_task(pending), \
        "Auto-reconcile task should NOT exist when env var is unset"
    # Cleanup: cancel any scheduled tasks
    for t in pending:
        if t is not asyncio.current_task():
            t.cancel()


@pytest.mark.asyncio
async def test_auto_reconcile_ON_when_env_true(monkeypatch, fake_bot):
    """env=true → reconcile_orphan_positions called with all_orphans=True."""
    monkeypatch.setenv("AUTO_RECONCILE_AT_BOOT", "true")

    from services.trading_bot_service import TradingBotService
    start_unbound = TradingBotService.start

    # Patch sleep so the 20s wait elapses immediately
    real_sleep = asyncio.sleep

    async def _fast_sleep(s):
        await real_sleep(0)

    fake_emit = AsyncMock()

    with patch("services.trading_bot_service.logger"):
        fake_bot._scan_loop = AsyncMock()
        with patch.dict(sys.modules, {
            "services.enhanced_scanner": MagicMock(get_enhanced_scanner=lambda: None),
            "services.sentcom_service": MagicMock(emit_stream_event=fake_emit),
        }):
            with patch("services.trading_bot_service.asyncio.sleep", _fast_sleep):
                await start_unbound(fake_bot)
                # Yield enough times for spawned tasks to run
                for _ in range(10):
                    await real_sleep(0)

    # The mock should have been called with all_orphans=True
    fake_bot.reconcile_orphan_positions.assert_awaited_once()
    call_kwargs = fake_bot.reconcile_orphan_positions.call_args.kwargs
    assert call_kwargs.get("all_orphans") is True
    # Stream event emitted with reconciled count
    assert fake_emit.await_count >= 1
    emit_call = fake_emit.await_args_list[-1]
    event = emit_call.args[0]
    assert event.get("event") == "auto_reconcile_at_boot"
    assert event["metadata"]["reconciled_count"] == 2

    # Cleanup
    for t in asyncio.all_tasks():
        if t is not asyncio.current_task():
            t.cancel()


@pytest.mark.parametrize("truthy", ["1", "true", "TRUE", "yes", "on", "  True  "])
@pytest.mark.asyncio
async def test_auto_reconcile_truthy_variants(monkeypatch, fake_bot, truthy):
    """All accepted truthy variants enable the feature."""
    monkeypatch.setenv("AUTO_RECONCILE_AT_BOOT", truthy)

    from services.trading_bot_service import TradingBotService
    start_unbound = TradingBotService.start

    real_sleep = asyncio.sleep

    async def _fast_sleep(s):
        await real_sleep(0)

    with patch("services.trading_bot_service.logger"):
        fake_bot._scan_loop = AsyncMock()
        # Reset the mock between parametrize runs
        fake_bot.reconcile_orphan_positions = AsyncMock(return_value={
            "reconciled": [], "skipped": [], "errors": [],
        })
        with patch.dict(sys.modules, {
            "services.enhanced_scanner": MagicMock(get_enhanced_scanner=lambda: None),
            "services.sentcom_service": MagicMock(emit_stream_event=AsyncMock()),
        }):
            with patch("services.trading_bot_service.asyncio.sleep", _fast_sleep):
                await start_unbound(fake_bot)
                for _ in range(10):
                    await real_sleep(0)

    fake_bot.reconcile_orphan_positions.assert_awaited_once()

    for t in asyncio.all_tasks():
        if t is not asyncio.current_task():
            t.cancel()


@pytest.mark.parametrize("falsy", ["", "0", "false", "FALSE", "no", "off", "garbage"])
@pytest.mark.asyncio
async def test_auto_reconcile_falsy_variants(monkeypatch, fake_bot, falsy):
    """Falsy/garbage values do NOT enable the feature (fail-safe)."""
    monkeypatch.setenv("AUTO_RECONCILE_AT_BOOT", falsy)

    from services.trading_bot_service import TradingBotService
    start_unbound = TradingBotService.start

    real_sleep = asyncio.sleep

    async def _fast_sleep(s):
        await real_sleep(0)

    with patch("services.trading_bot_service.logger"):
        fake_bot._scan_loop = AsyncMock()
        fake_bot.reconcile_orphan_positions = AsyncMock()
        with patch.dict(sys.modules, {
            "services.enhanced_scanner": MagicMock(get_enhanced_scanner=lambda: None),
            "services.sentcom_service": MagicMock(emit_stream_event=AsyncMock()),
        }):
            with patch("services.trading_bot_service.asyncio.sleep", _fast_sleep):
                await start_unbound(fake_bot)
                for _ in range(10):
                    await real_sleep(0)

    fake_bot.reconcile_orphan_positions.assert_not_awaited()

    for t in asyncio.all_tasks():
        if t is not asyncio.current_task():
            t.cancel()


@pytest.mark.asyncio
async def test_auto_reconcile_exception_does_not_crash_start(monkeypatch, fake_bot):
    """If reconcile_orphan_positions raises, bot.start() must still
    complete cleanly (the task is fire-and-forget)."""
    monkeypatch.setenv("AUTO_RECONCILE_AT_BOOT", "true")

    from services.trading_bot_service import TradingBotService
    start_unbound = TradingBotService.start

    fake_bot.reconcile_orphan_positions = AsyncMock(
        side_effect=RuntimeError("simulated reconcile boom")
    )
    real_sleep = asyncio.sleep

    async def _fast_sleep(s):
        await real_sleep(0)

    with patch("services.trading_bot_service.logger") as logmock:
        fake_bot._scan_loop = AsyncMock()
        with patch.dict(sys.modules, {
            "services.enhanced_scanner": MagicMock(get_enhanced_scanner=lambda: None),
            "services.sentcom_service": MagicMock(emit_stream_event=AsyncMock()),
        }):
            with patch("services.trading_bot_service.asyncio.sleep", _fast_sleep):
                # If start() crashes, this raises; if it doesn't, the
                # mock is awaited inside the spawned task and we just
                # observe the warning log.
                await start_unbound(fake_bot)
                for _ in range(10):
                    await real_sleep(0)

    # logger.warning should have been called with the failure message
    warning_msgs = [
        str(c) for c in logmock.warning.call_args_list
    ]
    assert any("AUTO-RECONCILE" in m and "non-fatal" in m for m in warning_msgs), \
        f"Expected non-fatal warning log, got: {warning_msgs}"

    for t in asyncio.all_tasks():
        if t is not asyncio.current_task():
            t.cancel()
