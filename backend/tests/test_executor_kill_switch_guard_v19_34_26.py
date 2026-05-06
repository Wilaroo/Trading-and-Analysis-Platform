"""
test_executor_kill_switch_guard_v19_34_26.py — pins the executor-layer
kill-switch refusal shipped in v19.34.26.

Bug class — operator-discovered 2026-02-XX:
    Six bracket entries (UPS 619sh, ADBE 82sh, AMDL 741sh short, XOP
    341sh, TSLG 5,600sh short, TEAM 784sh) fired at IB between
    2:45-2:54 PM ET while the kill-switch was demonstrably active
    (latch reason `v19_34_25_persistence_test` set, UI banner visible,
    Mongo `safety_state` doc confirmed `active=True`). IB order history
    showed each had a full OCA bracket (parent + profit-taker child +
    stop-loss child), confirming all six routed through
    `trade_executor_service.place_bracket_order`.

    Some upstream code path in the bot's autonomous flow had skipped
    `safety_guardrails.check_can_enter()` — the only kill-switch gate
    in the entry pipeline pre-fix. Soft-brake at scanner-eval was not
    bypass-proof.

v19.34.26 fix: defense-in-depth. Every executor entry-creating method
now calls `_kill_switch_refusal()` at its very top. Bypass-proof
because every order path traverses the executor — guarding here
catches anything the bot layer missed. The today's bypass would have
been blocked at `place_bracket_order` line 1.

Tests below cover:
  - `_kill_switch_refusal` returns None when latch is inactive
    (regression pin — no false positives).
  - `_kill_switch_refusal` returns a structured refusal dict when
    latch is active.
  - `execute_entry` honors the refusal — does NOT submit to broker.
  - `place_bracket_order` honors the refusal — the exact method
    today's bypass routed through.
  - Refusal is fail-open if guardrails import crashes (operator
    safety vs paranoia trade-off — same behaviour as pre-v19.34.26).
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.trade_executor_service import (  # noqa: E402
    ExecutorMode,
    TradeExecutorService,
)
from services.safety_guardrails import SafetyGuardrails, SafetyConfig  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_trade(symbol="UPS", direction="long", shares=619):
    return SimpleNamespace(
        id=f"T-{symbol}",
        symbol=symbol,
        direction=SimpleNamespace(value=direction),
        shares=shares,
        entry_price=100.02,
        stop_price=94.98,
        target_prices=[107.57],
        current_price=100.02,
    )


def _live_executor():
    svc = TradeExecutorService()
    svc._mode = ExecutorMode.LIVE
    svc._initialized = True
    return svc


# ─────────────────────────────────────────────────────────────────────
# 1. Latch INACTIVE → guard returns None (no false positives — the
#    executor must not refuse legitimate orders).
# ─────────────────────────────────────────────────────────────────────
def test_guard_returns_none_when_kill_switch_inactive():
    svc = TradeExecutorService()

    fresh_guard = SafetyGuardrails(SafetyConfig(enabled=True))
    assert fresh_guard.state.kill_switch_active is False

    with patch("services.safety_guardrails.get_safety_guardrails",
               return_value=fresh_guard):
        result = svc._kill_switch_refusal("test_method", _make_trade())

    assert result is None


# ─────────────────────────────────────────────────────────────────────
# 2. Latch ACTIVE → guard returns refusal dict with the canonical shape.
# ─────────────────────────────────────────────────────────────────────
def test_guard_returns_refusal_when_kill_switch_active():
    svc = TradeExecutorService()

    g = SafetyGuardrails(SafetyConfig(enabled=True))
    g.state.kill_switch_active = True
    g.state.kill_switch_reason = "v19_34_25_persistence_test"

    with patch("services.safety_guardrails.get_safety_guardrails", return_value=g):
        result = svc._kill_switch_refusal("place_bracket_order", _make_trade("UPS"))

    assert result is not None
    assert result["success"] is False
    assert result["error"] == "kill_switch_active"
    assert "persistence_test" in result["reason"]
    assert result["refused_at"] == "executor_layer"
    assert result["method"] == "place_bracket_order"


# ─────────────────────────────────────────────────────────────────────
# 3. CRITICAL — execute_entry does NOT submit when latch active.
#    Today's bypass would have been blocked here too if it had taken
#    this path. Pin both behaviours: refusal returned + broker side
#    NEVER touched.
# ─────────────────────────────────────────────────────────────────────
def test_execute_entry_refuses_when_kill_switch_active():
    svc = _live_executor()

    g = SafetyGuardrails(SafetyConfig(enabled=True))
    g.state.kill_switch_active = True
    g.state.kill_switch_reason = "operator_test"

    # Mock the actual broker path so we can prove it was NEVER called.
    svc._ib_entry = AsyncMock(return_value={"success": True, "order_id": "SHOULD-NOT-FIRE"})

    with patch("services.safety_guardrails.get_safety_guardrails", return_value=g):
        result = _run(svc.execute_entry(_make_trade("UPS")))

    assert result["success"] is False
    assert result["error"] == "kill_switch_active"
    svc._ib_entry.assert_not_called()   # the actual regression pin


# ─────────────────────────────────────────────────────────────────────
# 4. CRITICAL — place_bracket_order does NOT submit when latch active.
#    This is the EXACT method today's six bypass orders routed through
#    (UPS, ADBE, AMDL, XOP, TSLG, TEAM all had OCA brackets attached).
# ─────────────────────────────────────────────────────────────────────
def test_place_bracket_order_refuses_when_kill_switch_active():
    svc = _live_executor()

    g = SafetyGuardrails(SafetyConfig(enabled=True))
    g.state.kill_switch_active = True
    g.state.kill_switch_reason = "v19_34_25_persistence_test"

    # If place_bracket_order calls into pusher / paper / sim, fail loudly.
    svc._ib_place_bracket = AsyncMock(return_value={"success": True})
    svc._alpaca_entry = AsyncMock(return_value={"success": True})
    svc._simulate_entry = AsyncMock(return_value={"success": True})

    with patch("services.safety_guardrails.get_safety_guardrails", return_value=g):
        result = _run(svc.place_bracket_order(_make_trade("TSLG", "short", 5600)))

    assert result["success"] is False
    assert result["error"] == "kill_switch_active"
    assert result["method"] == "place_bracket_order"
    svc._ib_place_bracket.assert_not_called()
    svc._alpaca_entry.assert_not_called()
    svc._simulate_entry.assert_not_called()


# ─────────────────────────────────────────────────────────────────────
# 5. Defense in depth: guardrail import crash → fail-open (no refusal).
#    Operator safety trade-off — preserving pre-v19.34.26 behaviour
#    when the guardrail layer itself is broken.
# ─────────────────────────────────────────────────────────────────────
def test_guard_fails_open_when_guardrails_unavailable():
    svc = TradeExecutorService()

    with patch("services.safety_guardrails.get_safety_guardrails",
               side_effect=ImportError("guardrails module corrupt")):
        result = svc._kill_switch_refusal("execute_entry", _make_trade())

    assert result is None  # fail open — preserves pre-fix behaviour
