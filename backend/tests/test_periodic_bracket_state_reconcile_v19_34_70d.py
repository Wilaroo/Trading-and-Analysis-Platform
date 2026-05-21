"""v19.34.70 PATCH D — Periodic bracket-state reconciler loop.

The loop runs in the background at 120s default cadence (env-overridable)
and calls `reconcile_bracket_state` to auto-clear stale `stop_order_id`
/ `target_order_ids` refs from `_open_trades`. Closes the loop on the
2026-05-21 incident class: even if Patches A+B make every code path
resilient to staleness, this loop ensures stale refs never accumulate
silently in the first place.

These tests verify:
  - Disabled by env flag → loop exits immediately (no work, no waits).
  - Enabled → cadence matches env override.
  - Modified > 0 → warning logged with naked-symbols list.
  - ib_cache unavailable → loop skips silently, no clearing.
  - Endpoint raises → loop catches and continues.

The loop is defined inline inside the bot service startup, so these
tests reach in via the same contract the loop expects: a callable
`reconcile_bracket_state` + `ReconcileBracketStateRequest`, plus the
`self._running` flag.
"""
import asyncio
import os
import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock


# Match the inline loop from trading_bot_service.py:
#   • reads AUTO_RECONCILE_BRACKET_STATE env (default "true")
#   • reads AUTO_RECONCILE_BRACKET_STATE_S env (default "120")
#   • sleeps one full interval, then loops calling reconcile_bracket_state
#
# We can't import the inline loop directly (it's a closure inside
# `start_trading()`), so we reproduce the contract here and assert that
# THIS reference implementation behaves correctly. The contract test is
# what we'd really want to keep stable across refactors.

async def _reference_loop(bot_running_flag, reconcile_fn, request_cls,
                          logger=None, env=None):
    """Mirrors the v19.34.70 PATCH D loop body exactly. Kept as test
    fixture so the contract is locked even if the inline loop in
    trading_bot_service.py moves around."""
    env = env if env is not None else os.environ
    if env.get("AUTO_RECONCILE_BRACKET_STATE", "true").lower() != "true":
        return "disabled"
    interval_s = float(env.get("AUTO_RECONCILE_BRACKET_STATE_S", "120"))
    await asyncio.sleep(interval_s)
    while bot_running_flag["v"]:
        try:
            report = await reconcile_fn(request_cls(dry_run=False))
            modified = report.get("trades_modified", 0)
            if modified > 0 and logger is not None:
                naked = [
                    r["symbol"] for r in report.get("trades", [])
                    if r.get("fully_unprotected")
                ]
                logger.warning(
                    "cleared %d; naked=%s", modified, naked,
                )
            elif not report.get("ib_cache_available", True) and logger is not None:
                logger.debug("skipped — ib cache unavailable")
        except Exception as e:
            if logger is not None:
                logger.debug("tick err: %s", e)
        await asyncio.sleep(interval_s)


class _FakeRequest:
    def __init__(self, dry_run=False, symbols=None):
        self.dry_run = dry_run
        self.symbols = symbols


# -----------------------------------------------------------------
# 1. Disabled via env → loop returns immediately
# -----------------------------------------------------------------
def test_loop_disabled_by_env_returns_immediately():
    flag = {"v": True}
    called = []

    async def _reconcile_should_not_be_called(req):
        called.append(req)
        return {"trades_modified": 99}

    res = asyncio.run(_reference_loop(
        flag, _reconcile_should_not_be_called, _FakeRequest,
        env={"AUTO_RECONCILE_BRACKET_STATE": "false"},
    ))
    assert res == "disabled"
    assert called == []


# -----------------------------------------------------------------
# 2. Cadence: respects AUTO_RECONCILE_BRACKET_STATE_S
# -----------------------------------------------------------------
def test_cadence_respects_env_interval():
    """When interval is tiny, the loop should iterate quickly. We
    short-circuit by flipping _running=False after one iteration so
    the test doesn't hang."""
    flag = {"v": True}
    call_count = {"n": 0}

    async def _reconcile(req):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            flag["v"] = False   # halt the loop
        return {"trades_modified": 0, "ib_cache_available": True}

    asyncio.run(_reference_loop(
        flag, _reconcile, _FakeRequest,
        env={"AUTO_RECONCILE_BRACKET_STATE": "true",
             "AUTO_RECONCILE_BRACKET_STATE_S": "0.01"},
    ))
    assert call_count["n"] >= 2


# -----------------------------------------------------------------
# 3. Modified > 0 → warning logged with naked-symbols list
# -----------------------------------------------------------------
def test_modified_triggers_warning_with_naked_list():
    flag = {"v": True}

    async def _reconcile(req):
        flag["v"] = False
        return {
            "trades_modified": 3,
            "trades": [
                {"symbol": "CF",   "fully_unprotected": True},
                {"symbol": "INTU", "fully_unprotected": True},
                {"symbol": "AAPL", "fully_unprotected": False},  # partially
            ],
            "ib_cache_available": True,
        }

    log_calls = []
    fake_logger = types.SimpleNamespace(
        warning=lambda fmt, *args: log_calls.append(("warning", fmt, args)),
        debug=lambda fmt, *args: log_calls.append(("debug", fmt, args)),
    )

    asyncio.run(_reference_loop(
        flag, _reconcile, _FakeRequest, logger=fake_logger,
        env={"AUTO_RECONCILE_BRACKET_STATE": "true",
             "AUTO_RECONCILE_BRACKET_STATE_S": "0.01"},
    ))

    warnings = [c for c in log_calls if c[0] == "warning"]
    assert warnings, "should have logged at least one warning"
    # Naked list should only contain the fully_unprotected ones
    naked_arg = warnings[0][2][1]
    assert sorted(naked_arg) == ["CF", "INTU"]


# -----------------------------------------------------------------
# 4. ib_cache_available=False → debug-log skip, no warning
# -----------------------------------------------------------------
def test_cache_unavailable_logs_debug_no_warning():
    flag = {"v": True}

    async def _reconcile(req):
        flag["v"] = False
        return {
            "trades_modified": 0,
            "trades": [],
            "ib_cache_available": False,
        }

    log_calls = []
    fake_logger = types.SimpleNamespace(
        warning=lambda fmt, *args: log_calls.append(("warning", fmt)),
        debug=lambda fmt, *args: log_calls.append(("debug", fmt)),
    )

    asyncio.run(_reference_loop(
        flag, _reconcile, _FakeRequest, logger=fake_logger,
        env={"AUTO_RECONCILE_BRACKET_STATE": "true",
             "AUTO_RECONCILE_BRACKET_STATE_S": "0.01"},
    ))

    assert not [c for c in log_calls if c[0] == "warning"]
    assert [c for c in log_calls if c[0] == "debug"]


# -----------------------------------------------------------------
# 5. Endpoint raises → loop catches, continues, doesn't crash
# -----------------------------------------------------------------
def test_endpoint_exception_caught_and_loop_continues():
    flag = {"v": True}
    call_count = {"n": 0}

    async def _reconcile(req):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("ib_direct connection lost mid-call")
        if call_count["n"] >= 2:
            flag["v"] = False
        return {"trades_modified": 0, "ib_cache_available": True}

    log_calls = []
    fake_logger = types.SimpleNamespace(
        warning=lambda *a, **k: None,
        debug=lambda fmt, *args: log_calls.append(("debug", fmt, args)),
    )

    asyncio.run(_reference_loop(
        flag, _reconcile, _FakeRequest, logger=fake_logger,
        env={"AUTO_RECONCILE_BRACKET_STATE": "true",
             "AUTO_RECONCILE_BRACKET_STATE_S": "0.01"},
    ))

    # Should have called twice (once raised, once succeeded then halted)
    assert call_count["n"] >= 2
    # The error should have been logged at debug level
    assert any("tick err" in c[1] for c in log_calls if c[0] == "debug")


# -----------------------------------------------------------------
# 6. Request object is constructed with dry_run=False (live mode)
# -----------------------------------------------------------------
def test_loop_always_calls_with_dry_run_false():
    """The whole POINT of the loop is to ACT, not preview. dry_run must
    be False on every call."""
    flag = {"v": True}
    seen_dry_run_values = []

    async def _reconcile(req):
        seen_dry_run_values.append(req.dry_run)
        flag["v"] = False
        return {"trades_modified": 0, "ib_cache_available": True}

    asyncio.run(_reference_loop(
        flag, _reconcile, _FakeRequest,
        env={"AUTO_RECONCILE_BRACKET_STATE": "true",
             "AUTO_RECONCILE_BRACKET_STATE_S": "0.01"},
    ))
    assert seen_dry_run_values == [False]


# -----------------------------------------------------------------
# 7. Bot shutdown (_running=False) breaks the loop cleanly
# -----------------------------------------------------------------
def test_bot_shutdown_breaks_loop_cleanly():
    """Setting _running=False between ticks should end the loop on the
    next iteration boundary without crashing."""
    flag = {"v": False}   # already shutting down before the first tick

    async def _reconcile(req):
        return {"trades_modified": 0, "ib_cache_available": True}

    # Even though _running=False, the loop sleeps once first. Use a
    # tiny interval so the test runs fast.
    asyncio.run(_reference_loop(
        flag, _reconcile, _FakeRequest,
        env={"AUTO_RECONCILE_BRACKET_STATE": "true",
             "AUTO_RECONCILE_BRACKET_STATE_S": "0.01"},
    ))
    # No assertion needed — just must not hang or raise.
