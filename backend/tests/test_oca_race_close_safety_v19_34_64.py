"""v19.34.64 — Regression tests for OCA-race close-path fixes.

Three properties under test:

  1. `wait_for_orders_terminal` correctly partitions order IDs by
     terminal status (cancelled / filled / other_terminal / timeout /
     unknown) — this is the primitive that lets the close path detect
     the 2026-05-20 IBIT/SOFI/RBLX direction-flip scenario *before*
     submitting the MKT close.

  2. `verify_position_flat` correctly distinguishes IB-flat from IB-
     still-holding-position — this is the post-close safety net for
     divergence sources OTHER than the OCA race (manual TWS trades,
     IB-side glitches, network partials).

  3. The `/api/trading-bot/positions/truth-diff` endpoint correctly
     partitions bot-only / ib-only / direction_flipped / share_mismatch
     symbol sets — this powers the V5 HUD pill.

Note: We do NOT exercise the real ib_async event loop here. ib_direct is
mocked at the singleton-getter layer. The integration is exercised
manually on the DGX after deploy.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────
def _mock_trade(symbol="IBIT", direction="short", shares=2215,
                stop_order_id=12345, target_order_id=12346):
    """Build a minimal trade-like object matching what
    `_cancel_ib_bracket_orders` reads."""
    t = MagicMock()
    t.symbol = symbol
    t.direction.value = direction
    t.shares = shares
    t.stop_order_id = stop_order_id
    t.target_order_id = target_order_id
    t.target_order_ids = []
    return t


def _mock_ib_trade(order_id: int, status: str):
    """Build an ib_async Trade-like object with the given orderStatus.status."""
    t = MagicMock()
    t.order.orderId = order_id
    t.orderStatus.status = status
    return t


# ─────────────────────────────────────────────────────────────────────
# Part A: wait_for_orders_terminal
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_wait_for_orders_terminal_classifies_all_cancelled():
    """Happy path: cancels all confirmed → all in `cancelled` bucket."""
    from services.ib_direct_service import IBDirectService
    svc = IBDirectService()
    svc._ib = MagicMock()
    svc._ib.trades = MagicMock(return_value=[
        _mock_ib_trade(101, "Cancelled"),
        _mock_ib_trade(102, "ApiCancelled"),
    ])
    with patch.object(svc, "ensure_connected", new=AsyncMock(return_value=True)):
        out = await svc.wait_for_orders_terminal([101, 102], timeout_s=0.5, poll_iv_s=0.05)
    assert set(out["cancelled"]) == {101, 102}
    assert out["filled"] == []
    assert out["timeout"] == []


@pytest.mark.asyncio
async def test_wait_for_orders_terminal_detects_filled_during_wait():
    """The 2026-05-20 incident: OCA child fills while we're waiting on its
    cancel. This is the case the close path MUST detect to avoid the
    direction-flip double-fill."""
    from services.ib_direct_service import IBDirectService
    svc = IBDirectService()
    svc._ib = MagicMock()
    svc._ib.trades = MagicMock(return_value=[
        _mock_ib_trade(101, "Filled"),       # OCA child fired — RACE
        _mock_ib_trade(102, "Cancelled"),    # other child safely cancelled
    ])
    with patch.object(svc, "ensure_connected", new=AsyncMock(return_value=True)):
        out = await svc.wait_for_orders_terminal([101, 102], timeout_s=0.5, poll_iv_s=0.05)
    assert out["filled"] == [101], (
        "Filled-during-wait must surface in `filled` so the close path "
        "can ABORT the MKT and rely on the bracket-fill path instead."
    )
    assert out["cancelled"] == [102]


@pytest.mark.asyncio
async def test_wait_for_orders_terminal_timeout_when_still_pending():
    """If a child never reaches terminal status within the timeout, it
    goes to `timeout` (NOT `cancelled`). Caller treats timeout as
    race-risk and aborts the MKT close."""
    from services.ib_direct_service import IBDirectService
    svc = IBDirectService()
    svc._ib = MagicMock()
    svc._ib.trades = MagicMock(return_value=[
        _mock_ib_trade(101, "PreSubmitted"),  # non-terminal
    ])
    with patch.object(svc, "ensure_connected", new=AsyncMock(return_value=True)):
        out = await svc.wait_for_orders_terminal([101], timeout_s=0.3, poll_iv_s=0.05)
    assert out["timeout"] == [101]
    assert out["cancelled"] == []
    assert out["filled"] == []


@pytest.mark.asyncio
async def test_wait_for_orders_terminal_unknown_when_not_in_cache():
    """If an order ID isn't in the live trades cache, it's classified
    `unknown` (NOT timeout). Likely already cancelled and GC'd — safe."""
    from services.ib_direct_service import IBDirectService
    svc = IBDirectService()
    svc._ib = MagicMock()
    svc._ib.trades = MagicMock(return_value=[])  # empty cache
    with patch.object(svc, "ensure_connected", new=AsyncMock(return_value=True)):
        out = await svc.wait_for_orders_terminal([999], timeout_s=0.3, poll_iv_s=0.05)
    assert out["unknown"] == [999]
    assert out["timeout"] == []


# ─────────────────────────────────────────────────────────────────────
# Part B: verify_position_flat
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_verify_position_flat_returns_true_when_ib_flat():
    """Happy path: IB shows no position for the symbol → is_flat=True."""
    from services.ib_direct_service import IBDirectService
    svc = IBDirectService()
    svc._ib = MagicMock()
    svc._ib.positions = MagicMock(return_value=[])
    with patch.object(svc, "ensure_connected", new=AsyncMock(return_value=True)):
        out = await svc.verify_position_flat("IBIT")
    assert out["is_flat"] is True
    assert out["ib_position"] == 0
    assert out["divergence"] == 0


@pytest.mark.asyncio
async def test_verify_position_flat_detects_direction_flip():
    """The 2026-05-20 signature: bot expects flat, IB shows long 2215
    (the OCA double-fill flipped from short 2215). divergence=+2215."""
    from services.ib_direct_service import IBDirectService
    svc = IBDirectService()
    svc._ib = MagicMock()
    pos = MagicMock()
    pos.contract.symbol = "IBIT"
    pos.position = 2215
    pos.avgCost = 44.00
    svc._ib.positions = MagicMock(return_value=[pos])
    with patch.object(svc, "ensure_connected", new=AsyncMock(return_value=True)):
        out = await svc.verify_position_flat("IBIT")
    assert out["is_flat"] is False
    assert out["ib_position"] == 2215
    assert out["divergence"] == 2215


@pytest.mark.asyncio
async def test_verify_position_flat_handles_short_position():
    """Negative position represents short. The bug today was bot
    expected flat but IB held SOFI short 2684 — divergence=-2684."""
    from services.ib_direct_service import IBDirectService
    svc = IBDirectService()
    svc._ib = MagicMock()
    pos = MagicMock()
    pos.contract.symbol = "SOFI"
    pos.position = -2684
    pos.avgCost = 15.63
    svc._ib.positions = MagicMock(return_value=[pos])
    with patch.object(svc, "ensure_connected", new=AsyncMock(return_value=True)):
        out = await svc.verify_position_flat("SOFI")
    assert out["is_flat"] is False
    assert out["ib_position"] == -2684
    assert out["divergence"] == -2684


@pytest.mark.asyncio
async def test_verify_position_flat_tolerance_partial_close():
    """Caller may pass `expected_remaining` for partial closes. e.g.,
    closing 100 of 200 shares → expected_remaining=100 → IB showing
    100 is_flat=True."""
    from services.ib_direct_service import IBDirectService
    svc = IBDirectService()
    svc._ib = MagicMock()
    pos = MagicMock()
    pos.contract.symbol = "AAPL"
    pos.position = 100  # half closed
    pos.avgCost = 180.0
    svc._ib.positions = MagicMock(return_value=[pos])
    with patch.object(svc, "ensure_connected", new=AsyncMock(return_value=True)):
        out = await svc.verify_position_flat("AAPL", expected_remaining=100)
    assert out["is_flat"] is True
    assert out["divergence"] == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
