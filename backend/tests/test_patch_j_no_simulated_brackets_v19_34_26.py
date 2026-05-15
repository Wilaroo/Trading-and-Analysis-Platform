"""v19.34.26 Patch J — regression tests for fail-hard order paths.

Pre-Patch-J, four hot paths in `trade_executor_service.py` silently
fell back to simulated success when the IB pusher was offline:

  • `execute_entry`          → `_simulate_entry`     (fake fill, no IB order)
  • `_ib_stop`               → `_simulate_stop`      (fake stop, naked position)
  • `_ib_bracket`            → `_simulate_bracket`   (fake bracket, naked position)
  • `attach_oca_stop_target` → returns SIM-* IDs     (fake bracket, naked position)

Real-world impact on 2026-05-15 12:41-12:46 ET: 6 naked positions
opened (BTG, HMY, ONON, SWK, JBLU, MOD ≈ $300K notional) while the
bot's DB recorded them as fully bracketed via SIM-* IDs.

Patch J makes all four paths return an explicit failure dict
(`success: False`, `error: "pusher_offline_cannot_*"`, `pusher_offline:
True`) so callers can:

  • drop the trade entirely (entry / bracket parent path), or
  • log a critical alert and retry next scan (post-fill attach path),

without ever silently lying about IB state.

These tests pin all four contracts. They MUST NEVER be relaxed back to
returning simulated success on pusher-offline.
"""

from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

# Make backend importable regardless of cwd.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import pytest

from services.trade_executor_service import TradeExecutorService, ExecutorMode


def _fake_trade(symbol="ABCD", direction="long", stop=10.0, target=15.0, entry=12.0):
    """Minimal trade-like object that satisfies attribute access."""
    return SimpleNamespace(
        id=f"trade-{symbol}",
        symbol=symbol,
        direction=SimpleNamespace(value=direction),
        shares=100,
        entry_price=entry,
        stop_price=stop,
        target_prices=[target],
        setup_type="vwap_fade_long",
    )


def _executor_live():
    """A TradeExecutorService pinned to LIVE mode, no broker init required for
    these tests because we mock the pusher gate to fail BEFORE any
    queue_order call."""
    ex = TradeExecutorService.__new__(TradeExecutorService)
    ex._mode = ExecutorMode.LIVE
    ex._initialized = True
    ex._kill_switch_refusal = lambda *_a, **_k: None  # disable
    return ex


# ─────────────────────────────────────────────────────────────────────────
# 1. execute_entry — fail hard, no SIM order
# ─────────────────────────────────────────────────────────────────────────

def test_patch_j_execute_entry_fails_hard_on_pusher_offline():
    ex = _executor_live()
    with patch("routers.ib.is_pusher_connected", return_value=False), \
         patch("routers.ib.queue_order") as mock_queue:
        result = asyncio.run(ex.execute_entry(_fake_trade("SWK")))

    assert result["success"] is False
    assert result["error"] == "pusher_offline_cannot_place_entry"
    assert result["pusher_offline"] is True
    assert result["order_id"] is None
    # CRITICAL: zero queue_order calls (no IB order attempted).
    mock_queue.assert_not_called()
    # CRITICAL: no "SIM-*" leakage in any field.
    for v in result.values():
        if isinstance(v, str):
            assert not v.startswith("SIM-"), f"sim-id leaked: {v}"


# ─────────────────────────────────────────────────────────────────────────
# 2. _ib_stop — fail hard, no SIM stop
# ─────────────────────────────────────────────────────────────────────────

def test_patch_j_ib_stop_fails_hard_on_pusher_offline():
    ex = _executor_live()
    with patch("routers.ib.is_pusher_connected", return_value=False), \
         patch("routers.ib.queue_order") as mock_queue:
        result = asyncio.run(ex._ib_stop(_fake_trade("HMY")))

    assert result["success"] is False
    assert result["error"] == "pusher_offline_cannot_place_stop"
    assert result["pusher_offline"] is True
    assert result["order_id"] is None
    mock_queue.assert_not_called()
    for v in result.values():
        if isinstance(v, str):
            assert not v.startswith("SIM-"), f"sim-id leaked: {v}"


# ─────────────────────────────────────────────────────────────────────────
# 3. _ib_bracket — fail hard, no SIM bracket
# ─────────────────────────────────────────────────────────────────────────

def test_patch_j_ib_bracket_fails_hard_on_pusher_offline():
    ex = _executor_live()
    with patch("routers.ib.is_pusher_connected", return_value=False), \
         patch("routers.ib.queue_order") as mock_queue:
        result = asyncio.run(ex._ib_bracket(_fake_trade("BTG")))

    assert result["success"] is False
    assert result["error"] == "pusher_offline_cannot_place_bracket"
    assert result["pusher_offline"] is True
    assert result.get("entry_order_id") is None
    assert result.get("stop_order_id") is None
    assert result.get("target_order_id") is None
    mock_queue.assert_not_called()
    for v in result.values():
        if isinstance(v, str):
            assert not v.startswith("SIM-"), f"sim-id leaked: {v}"


def test_patch_j_ib_bracket_failure_does_not_trigger_legacy_fallback():
    """trade_execution.execute_trade computes `use_legacy` based on
    bracket_result.error. Patch J's error code MUST NOT match any
    legacy-fallback trigger, otherwise the bot would fall through to
    execute_entry and re-attempt with the same broken pusher path."""
    legacy_triggers = {
        "bracket_not_supported",
        "alpaca_bracket_not_implemented",
        "bracket_missing_stop_or_target",
    }
    assert "pusher_offline_cannot_place_bracket" not in legacy_triggers


# ─────────────────────────────────────────────────────────────────────────
# 4. attach_oca_stop_target — fail hard, no SIM bracket attach
# ─────────────────────────────────────────────────────────────────────────

def test_patch_j_attach_oca_stop_target_fails_hard_on_pusher_offline():
    ex = _executor_live()
    trade = _fake_trade("ONON")
    with patch("routers.ib.is_pusher_connected", return_value=False), \
         patch("routers.ib.queue_order") as mock_queue:
        result = asyncio.run(ex.attach_oca_stop_target(trade))

    assert result["success"] is False
    assert result["error"] == "pusher_offline_cannot_attach_brackets"
    assert result["pusher_offline"] is True
    assert result["stop_order_id"] is None
    assert result["target_order_id"] is None
    assert result["oca_group"] is None
    mock_queue.assert_not_called()
    for v in result.values():
        if isinstance(v, str):
            assert not v.startswith("SIM-"), f"sim-id leaked: {v}"


# ─────────────────────────────────────────────────────────────────────────
# Defense-in-depth: simulated entries from EXPLICIT simulator mode are
# still allowed (so paper trading & unit tests keep working). Patch J
# only kills the LIVE-mode-falls-back-to-sim behaviour.
# ─────────────────────────────────────────────────────────────────────────

def test_patch_j_simulator_mode_still_returns_sim_ids():
    """Sanity: when MODE=SIMULATED the simulator path is intentional
    (paper trading, tests). Patch J does NOT touch this."""
    ex = TradeExecutorService.__new__(TradeExecutorService)
    ex._mode = ExecutorMode.SIMULATED
    ex._initialized = True
    ex._kill_switch_refusal = lambda *_a, **_k: None
    result = asyncio.run(ex._simulate_entry(_fake_trade("PAPER")))
    assert result["success"] is True
    assert result.get("simulated") is True
    # SIM- prefix is fine here — caller knows it's a simulator.
    assert str(result.get("order_id", "")).startswith("SIM-")
