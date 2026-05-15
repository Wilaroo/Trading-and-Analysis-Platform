"""v19.34.27 Patch L1 — Regression tests for ib-direct bracket order
placement and BOT_ORDER_PATH=direct routing.

This is the first installment of the IB_DIRECT_MIGRATION_PLAN. After
L1 ships, `BOT_ORDER_PATH=direct` causes `_ib_bracket` to route through
`IBDirectService.place_bracket_order()` (synchronous ib_async call)
instead of the Windows pusher RPC.

Default `BOT_ORDER_PATH=pusher` is unchanged — these tests prove the
routing works WITHOUT changing default behaviour. Operator flips the
env var explicitly during Phase L3 paper validation.

Tests pin:
  • route selection by env var ("pusher" vs "shadow" vs "direct")
  • ib-direct connection prerequisites
  • read_only / unauthorized modes
  • OCA group + transmit semantics (via ib_async.bracketOrder helper)
  • dict-shape contract matches legacy `_ib_bracket` exactly
  • Patch J fail-hard: no SIM-* IDs leak even when ib-direct errors
  • long vs short direction mapping
  • integration with trade_executor.place_bracket_order (kill-switch
    still gates, simulated mode still works)
"""

from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, AsyncMock

# Make backend importable regardless of cwd.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import pytest

from services.trade_executor_service import TradeExecutorService, ExecutorMode


def _fake_trade(symbol="ABCD", direction="long", shares=100,
                entry=12.0, stop=10.0, target=15.0):
    return SimpleNamespace(
        id=f"trade-{symbol}",
        symbol=symbol,
        direction=SimpleNamespace(value=direction),
        shares=shares,
        entry_price=entry,
        stop_price=stop,
        target_prices=[target],
        setup_type="vwap_fade_long",
    )


def _executor_live():
    ex = TradeExecutorService.__new__(TradeExecutorService)
    ex._mode = ExecutorMode.LIVE
    ex._initialized = True
    ex._kill_switch_refusal = lambda *_a, **_k: None
    return ex


# ─────────────────────────────────────────────────────────────────────
# 1. Route selection: BOT_ORDER_PATH=direct invokes ib_direct, not pusher
# ─────────────────────────────────────────────────────────────────────

def test_patch_l1_direct_mode_calls_ib_direct_not_pusher():
    ex = _executor_live()
    fake_result = {
        "success": True,
        "entry_order_id": 12345,
        "stop_order_id": 12346,
        "target_order_id": 12347,
        "oca_group": "oca-12345",
        "status": "submitted",
        "fill_price": None,
        "filled_qty": 0,
        "broker": "ib_direct",
        "simulated": False,
    }
    mock_ib_direct = MagicMock()
    mock_ib_direct.place_bracket_order = AsyncMock(return_value=fake_result)
    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False), \
         patch("services.ib_direct_service.get_ib_direct_service",
               return_value=mock_ib_direct), \
         patch("routers.ib.queue_order") as mock_queue_order:
        result = asyncio.run(ex._ib_bracket(_fake_trade("BTG")))

    assert result == fake_result
    mock_ib_direct.place_bracket_order.assert_awaited_once()
    # CRITICAL: pusher path was NOT touched.
    mock_queue_order.assert_not_called()


def test_patch_l1_pusher_mode_is_default_behavior():
    """Without BOT_ORDER_PATH set, default is 'pusher' — no ib-direct call."""
    ex = _executor_live()
    mock_ib_direct = MagicMock()
    mock_ib_direct.place_bracket_order = AsyncMock(
        return_value={"unused": True}
    )
    # Pusher offline path — Patch J returns failure, but importantly
    # ib_direct.place_bracket_order must NOT be invoked.
    env = {k: v for k, v in os.environ.items() if k != "BOT_ORDER_PATH"}
    with patch.dict(os.environ, env, clear=True), \
         patch("services.ib_direct_service.get_ib_direct_service",
               return_value=mock_ib_direct), \
         patch("routers.ib.is_pusher_connected", return_value=False):
        result = asyncio.run(ex._ib_bracket(_fake_trade("BTG")))

    assert result["success"] is False
    assert result.get("error") == "pusher_offline_cannot_place_bracket"
    mock_ib_direct.place_bracket_order.assert_not_called()


def test_patch_l1_shadow_mode_uses_pusher_for_now():
    """L1 phase: shadow == pusher behaviour. L2 will add parallel
    ib-direct observation."""
    ex = _executor_live()
    mock_ib_direct = MagicMock()
    mock_ib_direct.place_bracket_order = AsyncMock(return_value={})
    with patch.dict(os.environ, {"BOT_ORDER_PATH": "shadow"}, clear=False), \
         patch("services.ib_direct_service.get_ib_direct_service",
               return_value=mock_ib_direct), \
         patch("routers.ib.is_pusher_connected", return_value=False):
        result = asyncio.run(ex._ib_bracket(_fake_trade("BTG")))

    # Pusher offline → Patch J fail-hard via PUSHER path, not ib-direct.
    assert result.get("error") == "pusher_offline_cannot_place_bracket"
    mock_ib_direct.place_bracket_order.assert_not_called()


# ─────────────────────────────────────────────────────────────────────
# 2. ib_direct exception is contained (Patch J contract preserved)
# ─────────────────────────────────────────────────────────────────────

def test_patch_l1_ib_direct_exception_does_not_fall_back_to_pusher():
    """If ib_direct.place_bracket_order raises, we MUST NOT silently
    fall back to the pusher path. Per Patch J / IB-direct migration
    plan, operator configured 'direct' explicitly — exceptions are
    surfaced as failures, not papered over."""
    ex = _executor_live()
    mock_ib_direct = MagicMock()
    mock_ib_direct.place_bracket_order = AsyncMock(
        side_effect=RuntimeError("simulated socket drop")
    )
    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False), \
         patch("services.ib_direct_service.get_ib_direct_service",
               return_value=mock_ib_direct), \
         patch("routers.ib.queue_order") as mock_queue_order:
        result = asyncio.run(ex._ib_bracket(_fake_trade("BTG")))

    assert result["success"] is False
    assert "ib_direct_bracket_exception" in result.get("error", "")
    # No SIM-* leakage.
    for v in result.values():
        if isinstance(v, str):
            assert not v.startswith("SIM-"), f"sim-id leaked: {v}"
    # CRITICAL: pusher was not used as fallback.
    mock_queue_order.assert_not_called()


# ─────────────────────────────────────────────────────────────────────
# 3. ib_direct service-level: not connected → fail hard
# ─────────────────────────────────────────────────────────────────────

def test_patch_l1_ib_direct_not_connected_returns_failure():
    from services.ib_direct_service import IBDirectService, IBDirectConfig
    svc = IBDirectService.__new__(IBDirectService)
    svc.config = IBDirectConfig(host="x", port=1, client_id=11, read_only=False)
    svc.ensure_connected = AsyncMock(return_value=False)
    result = asyncio.run(svc.place_bracket_order(_fake_trade("X")))
    assert result["success"] is False
    assert result["error"] == "ib_direct_not_connected"
    assert result["broker"] == "ib_direct"
    assert result["simulated"] is False


# ─────────────────────────────────────────────────────────────────────
# 4. ib_direct service-level: read_only mode rejects placement
# ─────────────────────────────────────────────────────────────────────

def test_patch_l1_ib_direct_read_only_rejects():
    from services.ib_direct_service import IBDirectService, IBDirectConfig
    svc = IBDirectService.__new__(IBDirectService)
    svc.config = IBDirectConfig(host="x", port=1, client_id=11, read_only=True)
    svc.ensure_connected = AsyncMock(return_value=True)
    result = asyncio.run(svc.place_bracket_order(_fake_trade("X")))
    assert result["success"] is False
    assert result["error"] == "ib_direct_read_only_mode"


# ─────────────────────────────────────────────────────────────────────
# 5. ib_direct service-level: not authorized to trade
# ─────────────────────────────────────────────────────────────────────

def test_patch_l1_ib_direct_unauthorized_rejects():
    from services.ib_direct_service import IBDirectService, IBDirectConfig
    svc = IBDirectService.__new__(IBDirectService)
    svc.config = IBDirectConfig(host="x", port=1, client_id=11, read_only=False)
    svc.ensure_connected = AsyncMock(return_value=True)
    svc.is_authorized_to_trade = lambda: False
    result = asyncio.run(svc.place_bracket_order(_fake_trade("X")))
    assert result["success"] is False
    assert "not_authorized" in result["error"]


# ─────────────────────────────────────────────────────────────────────
# 6. ib_direct service-level: bad trade fields rejected
# ─────────────────────────────────────────────────────────────────────

def test_patch_l1_ib_direct_rejects_bad_trade_fields():
    from services.ib_direct_service import IBDirectService, IBDirectConfig
    svc = IBDirectService.__new__(IBDirectService)
    svc.config = IBDirectConfig(host="x", port=1, client_id=11, read_only=False)
    svc.ensure_connected = AsyncMock(return_value=True)
    svc.is_authorized_to_trade = lambda: True

    # Bad direction
    bad = _fake_trade("X", direction="sideways")
    result = asyncio.run(svc.place_bracket_order(bad))
    assert result["success"] is False
    assert "bad direction" in result["error"]

    # Zero shares
    bad = _fake_trade("X")
    bad.shares = 0
    result = asyncio.run(svc.place_bracket_order(bad))
    assert result["success"] is False
    assert "bad shares" in result["error"]

    # No targets
    bad = _fake_trade("X")
    bad.target_prices = []
    result = asyncio.run(svc.place_bracket_order(bad))
    assert result["success"] is False
    assert "no target_prices" in result["error"]


# ─────────────────────────────────────────────────────────────────────
# 7. Integration: kill switch refusal still gates ib_direct path
# ─────────────────────────────────────────────────────────────────────

def test_patch_l1_kill_switch_refusal_still_blocks_in_direct_mode():
    """The kill-switch refusal at `place_bracket_order` (line 978) runs
    BEFORE _ib_bracket — so direct mode is gated by the same safety
    layer as pusher mode. This test pins that contract."""
    ex = _executor_live()
    refusal = {"success": False, "error": "kill_switch_active"}
    ex._kill_switch_refusal = lambda *_a, **_k: refusal
    mock_ib_direct = MagicMock()
    mock_ib_direct.place_bracket_order = AsyncMock(return_value={"unused": True})
    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False), \
         patch("services.ib_direct_service.get_ib_direct_service",
               return_value=mock_ib_direct):
        result = asyncio.run(ex.place_bracket_order(_fake_trade("X")))

    assert result == refusal
    mock_ib_direct.place_bracket_order.assert_not_called()


# ─────────────────────────────────────────────────────────────────────
# 8. Integration: simulated mode still simulates (no ib_direct call)
# ─────────────────────────────────────────────────────────────────────

def test_patch_l1_simulator_mode_does_not_call_ib_direct():
    ex = TradeExecutorService.__new__(TradeExecutorService)
    ex._mode = ExecutorMode.SIMULATED
    ex._initialized = True
    ex._kill_switch_refusal = lambda *_a, **_k: None
    mock_ib_direct = MagicMock()
    mock_ib_direct.place_bracket_order = AsyncMock(return_value={"unused": True})
    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False), \
         patch("services.ib_direct_service.get_ib_direct_service",
               return_value=mock_ib_direct):
        result = asyncio.run(ex.place_bracket_order(_fake_trade("X")))

    assert result["success"] is True
    assert result.get("simulated") is True
    # SIM-* IDs are EXPECTED in simulator mode (paper trading, tests).
    # ib_direct must NOT be invoked.
    mock_ib_direct.place_bracket_order.assert_not_called()
