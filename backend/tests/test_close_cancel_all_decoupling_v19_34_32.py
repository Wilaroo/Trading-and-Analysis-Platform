"""
v19.34.32 — Close/Cancel All decoupling + flatten-in-progress race guard.

Pre-fix the `/api/safety/flatten-all` endpoint unconditionally tripped
the kill-switch. That conflated "clean my books" (close+cancel) with
"halt trading" (refuse new entries permanently). Post-fix the endpoint
does ONLY close+cancel. A short-lived (30s TTL) `flatten_in_progress`
flag blocks concurrent NEW ENTRIES during the iteration to prevent
the close-races-with-entry sign-flip scenario, but auto-expires so a
crashed endpoint can't permanently lock out the bot.
"""
from __future__ import annotations

import time

import pytest
from unittest.mock import MagicMock

from services.safety_guardrails import SafetyGuardrails


# ─── SafetyGuardrails.set_flatten_in_progress / is_flatten_in_progress ──

def test_flatten_lock_defaults_off():
    g = SafetyGuardrails()
    assert g.is_flatten_in_progress() is False
    assert g.state.flatten_in_progress is False


def test_flatten_lock_set_and_cleared():
    g = SafetyGuardrails()
    g.set_flatten_in_progress(ttl_s=30, reason="close_cancel_all")
    assert g.is_flatten_in_progress() is True
    assert g.state.flatten_reason == "close_cancel_all"
    assert g.state.flatten_expires_at > time.time()
    g.clear_flatten_in_progress()
    assert g.is_flatten_in_progress() is False


def test_flatten_lock_auto_expires_on_ttl():
    g = SafetyGuardrails()
    g.set_flatten_in_progress(ttl_s=0.01, reason="test_ttl")
    time.sleep(0.05)
    # First read after TTL must return False AND self-clear state.
    assert g.is_flatten_in_progress() is False
    assert g.state.flatten_in_progress is False
    assert g.state.flatten_expires_at is None


def test_flatten_lock_status_payload_exposed():
    g = SafetyGuardrails()
    status = g.status()
    assert "flatten_in_progress" in status["state"]
    assert status["state"]["flatten_in_progress"] is False
    g.set_flatten_in_progress(reason="ui_test")
    status2 = g.status()
    assert status2["state"]["flatten_in_progress"] is True
    assert status2["state"]["flatten_reason"] == "ui_test"
    assert status2["state"]["flatten_expires_at"] is not None


def test_flatten_lock_independent_of_kill_switch():
    """Setting flatten lock must NOT trip kill-switch, and vice versa."""
    g = SafetyGuardrails()
    g.set_flatten_in_progress(reason="x")
    assert g.is_flatten_in_progress() is True
    assert g.state.kill_switch_active is False  # ← critical decoupling

    g.clear_flatten_in_progress()
    g.trip_kill_switch(reason="y")
    assert g.state.kill_switch_active is True
    assert g.is_flatten_in_progress() is False


# ─── trade_executor_service._kill_switch_refusal honors flatten lock ────

def test_executor_refuses_entry_during_flatten():
    """While flatten_in_progress is set, entry methods must be refused."""
    from services.safety_guardrails import get_safety_guardrails
    from services.trade_executor_service import TradeExecutorService

    guard = get_safety_guardrails()
    guard.clear_flatten_in_progress()  # clean slate
    guard.set_flatten_in_progress(ttl_s=30, reason="close_cancel_all")

    try:
        ex = TradeExecutorService()
        fake_trade = MagicMock()
        fake_trade.symbol = "UPS"

        refusal = ex._kill_switch_refusal("execute_entry", fake_trade)
        assert refusal is not None, "entry must be refused while flatten in progress"
        assert refusal["error"] == "flatten_in_progress"
        assert refusal["refused_at"] == "executor_layer"
        assert refusal["method"] == "execute_entry"
        assert "expires_at" in refusal
    finally:
        guard.clear_flatten_in_progress()


def test_executor_allows_close_during_flatten():
    """Close paths (method_name starts with 'close_') must NOT be refused
    — flatten itself relies on closes firing."""
    from services.safety_guardrails import get_safety_guardrails
    from services.trade_executor_service import TradeExecutorService

    guard = get_safety_guardrails()
    guard.clear_flatten_in_progress()
    guard.set_flatten_in_progress(ttl_s=30, reason="close_cancel_all")

    try:
        ex = TradeExecutorService()
        fake_trade = MagicMock()
        fake_trade.symbol = "UPS"

        refusal = ex._kill_switch_refusal("close_position", fake_trade)
        assert refusal is None, "close paths must pass through while flatten in progress"
    finally:
        guard.clear_flatten_in_progress()


def test_executor_refuses_entry_when_kill_switch_active_too():
    """Kill-switch refusal still fires independently of flatten lock."""
    from services.safety_guardrails import get_safety_guardrails
    from services.trade_executor_service import TradeExecutorService

    guard = get_safety_guardrails()
    guard.clear_flatten_in_progress()
    guard.reset_kill_switch()
    guard.trip_kill_switch(reason="halt_test")

    try:
        ex = TradeExecutorService()
        fake_trade = MagicMock()
        fake_trade.symbol = "UPS"

        refusal = ex._kill_switch_refusal("execute_entry", fake_trade)
        assert refusal is not None
        # Kill-switch takes precedence over flatten-lock check order.
        assert refusal["error"] == "kill_switch_active"
    finally:
        guard.reset_kill_switch()


def test_executor_allows_entry_when_no_guards_active():
    """Normal baseline: neither guard set → no refusal."""
    from services.safety_guardrails import get_safety_guardrails
    from services.trade_executor_service import TradeExecutorService

    guard = get_safety_guardrails()
    guard.clear_flatten_in_progress()
    guard.reset_kill_switch()

    ex = TradeExecutorService()
    fake_trade = MagicMock()
    fake_trade.symbol = "UPS"

    refusal = ex._kill_switch_refusal("execute_entry", fake_trade)
    assert refusal is None, "baseline state must allow entries"


def test_executor_allows_entry_after_flatten_ttl_expires():
    """Flatten lock must self-heal — entries allowed again after TTL."""
    from services.safety_guardrails import get_safety_guardrails
    from services.trade_executor_service import TradeExecutorService

    guard = get_safety_guardrails()
    guard.clear_flatten_in_progress()
    guard.reset_kill_switch()
    guard.set_flatten_in_progress(ttl_s=0.01, reason="ttl_test")
    time.sleep(0.05)

    ex = TradeExecutorService()
    fake_trade = MagicMock()
    fake_trade.symbol = "UPS"

    refusal = ex._kill_switch_refusal("execute_entry", fake_trade)
    assert refusal is None, "entries must resume after flatten lock auto-expires"


# ─── /api/safety/flatten-all endpoint semantics (regression-pinned) ─────

def test_flatten_endpoint_source_decoupled_from_kill_switch():
    """Regression pin: source no longer contains the
    `trip_kill_switch(reason="flatten-all initiated")` call."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "routers" / "safety_router.py").read_text()
    assert 'trip_kill_switch(reason="flatten-all initiated")' not in src, (
        "v19.34.32 decoupling regressed — flatten-all must NOT auto-trip "
        "the kill-switch. Operators who want halt should click the "
        "'Also halt bot?' checkbox which fires a separate kill-switch call."
    )
    assert 'set_flatten_in_progress(reason="close_cancel_all")' in src, (
        "v19.34.32 race-guard missing — flatten-all must engage the "
        "short-lived flatten_in_progress flag before iterating."
    )
    assert "clear_flatten_in_progress()" in src, (
        "v19.34.32 happy-path release missing — flatten-all must "
        "proactively clear the lock when iteration completes."
    )
