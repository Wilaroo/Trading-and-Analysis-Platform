"""
v19.34.27 — Phantom-share-aware close path tests.

Pre-fix `position_manager.close_trade` fired a market close blindly using
the bot's tracked share count. Post-fix it queries the IB direct service
for the live position and caps `shares_to_close` at
`min(internal_remaining, ib_actual_abs)`. Direction-mismatch refuses
entirely.

These tests pin the clamp helper directly (no full bot harness needed)
so the regression catches any future refactor that drops the cross-check.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.position_manager import PositionManager


def _mk_trade(symbol="BMNR", direction="long", remaining=5472, trade_id="t1"):
    """Minimal duck-typed trade for the clamp helper."""
    from services.trading_bot_service import TradeDirection
    t = MagicMock()
    t.id = trade_id
    t.symbol = symbol
    t.remaining_shares = remaining
    t.shares = remaining
    t.direction = TradeDirection.LONG if direction == "long" else TradeDirection.SHORT
    return t


@pytest.mark.asyncio
async def test_clamp_returns_intended_when_socket_down():
    pm = PositionManager()
    trade = _mk_trade()
    fake_svc = MagicMock()
    fake_svc.is_available.return_value = True
    fake_svc.is_connected.return_value = False
    with patch("services.ib_direct_service.get_ib_direct_service", return_value=fake_svc):
        result = await pm._clamp_shares_to_ib_position(trade, 5472, reason="manual")
    assert result == 5472, "socket-down path must return intended count"


@pytest.mark.asyncio
async def test_clamp_returns_intended_when_ib_async_unavailable():
    pm = PositionManager()
    trade = _mk_trade()
    fake_svc = MagicMock()
    fake_svc.is_available.return_value = False
    fake_svc.is_connected.return_value = False
    with patch("services.ib_direct_service.get_ib_direct_service", return_value=fake_svc):
        result = await pm._clamp_shares_to_ib_position(trade, 100, reason="manual")
    assert result == 100


@pytest.mark.asyncio
async def test_clamp_returns_zero_when_ib_position_empty():
    """The "entire position is phantom" case — IB has no position for this symbol."""
    pm = PositionManager()
    trade = _mk_trade(symbol="BMNR", remaining=5472)
    fake_svc = MagicMock()
    fake_svc.is_available.return_value = True
    fake_svc.is_connected.return_value = True
    fake_svc.get_positions = AsyncMock(return_value=[
        {"symbol": "AAPL", "position": 100.0},  # no BMNR
    ])
    with patch("services.ib_direct_service.get_ib_direct_service", return_value=fake_svc):
        result = await pm._clamp_shares_to_ib_position(trade, 5472, reason="manual")
    assert result == 0, "no-IB-position must clamp to 0 (whole trade is phantom)"


@pytest.mark.asyncio
async def test_clamp_caps_at_actual_when_ib_has_fewer():
    """The BMNR scenario: bot tracks 5472, IB has 1905 → close 1905 only."""
    pm = PositionManager()
    trade = _mk_trade(symbol="BMNR", direction="long", remaining=5472)
    fake_svc = MagicMock()
    fake_svc.is_available.return_value = True
    fake_svc.is_connected.return_value = True
    fake_svc.get_positions = AsyncMock(return_value=[
        {"symbol": "BMNR", "position": 1905.0},
    ])
    with patch("services.ib_direct_service.get_ib_direct_service", return_value=fake_svc):
        result = await pm._clamp_shares_to_ib_position(trade, 5472, reason="manual")
    assert result == 1905


@pytest.mark.asyncio
async def test_clamp_passes_intended_when_ib_has_more_or_equal():
    pm = PositionManager()
    trade = _mk_trade(remaining=100)
    fake_svc = MagicMock()
    fake_svc.is_available.return_value = True
    fake_svc.is_connected.return_value = True
    fake_svc.get_positions = AsyncMock(return_value=[
        {"symbol": "BMNR", "position": 500.0},
    ])
    with patch("services.ib_direct_service.get_ib_direct_service", return_value=fake_svc):
        result = await pm._clamp_shares_to_ib_position(trade, 100, reason="manual")
    assert result == 100, "no clamp when IB has enough shares"


@pytest.mark.asyncio
async def test_clamp_refuses_on_direction_mismatch():
    """Bot tracks LONG, IB shows SHORT (or vice versa) → refuse close."""
    pm = PositionManager()
    trade = _mk_trade(symbol="BMNR", direction="long", remaining=5472)
    fake_svc = MagicMock()
    fake_svc.is_available.return_value = True
    fake_svc.is_connected.return_value = True
    # Negative position = short at IB
    fake_svc.get_positions = AsyncMock(return_value=[
        {"symbol": "BMNR", "position": -1905.0},
    ])
    with patch("services.ib_direct_service.get_ib_direct_service", return_value=fake_svc):
        result = await pm._clamp_shares_to_ib_position(trade, 5472, reason="manual")
    assert result == 0, "direction mismatch must refuse the close (return 0)"


@pytest.mark.asyncio
async def test_clamp_short_bot_long_ib_also_refuses():
    pm = PositionManager()
    trade = _mk_trade(symbol="BMNR", direction="short", remaining=1000)
    fake_svc = MagicMock()
    fake_svc.is_available.return_value = True
    fake_svc.is_connected.return_value = True
    fake_svc.get_positions = AsyncMock(return_value=[
        {"symbol": "BMNR", "position": 500.0},  # long at IB
    ])
    with patch("services.ib_direct_service.get_ib_direct_service", return_value=fake_svc):
        result = await pm._clamp_shares_to_ib_position(trade, 1000, reason="manual")
    assert result == 0


@pytest.mark.asyncio
async def test_clamp_handles_get_positions_exception():
    pm = PositionManager()
    trade = _mk_trade(remaining=100)
    fake_svc = MagicMock()
    fake_svc.is_available.return_value = True
    fake_svc.is_connected.return_value = True
    fake_svc.get_positions = AsyncMock(side_effect=RuntimeError("socket reset"))
    with patch("services.ib_direct_service.get_ib_direct_service", return_value=fake_svc):
        result = await pm._clamp_shares_to_ib_position(trade, 100, reason="manual")
    assert result == 100, "exception in get_positions falls back to intended count"


@pytest.mark.asyncio
async def test_clamp_case_insensitive_symbol_match():
    pm = PositionManager()
    trade = _mk_trade(symbol="bmnr", remaining=200)  # lowercase
    fake_svc = MagicMock()
    fake_svc.is_available.return_value = True
    fake_svc.is_connected.return_value = True
    fake_svc.get_positions = AsyncMock(return_value=[
        {"symbol": "BMNR", "position": 100.0},  # uppercase
    ])
    with patch("services.ib_direct_service.get_ib_direct_service", return_value=fake_svc):
        result = await pm._clamp_shares_to_ib_position(trade, 200, reason="manual")
    assert result == 100, "symbol comparison must be case-insensitive"
