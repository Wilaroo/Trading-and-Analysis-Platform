"""
v19.34.49 — Phantom-recovery multi-source confirmation regression
======================================================================

Pins the fix that prevents `_clamp_shares_to_ib_position` from
returning 0 (= phantom-recover, no broker call) when direct IB's
positions snapshot is unreliable.

Operator-discovered 2026-05-07: bot reported "FLATTEN COMPLETE 20/20"
while IB still had 4,436 BMNR + 555 PG. Root cause: direct IB
clientId=11 had just connected and `get_positions()` returned `[]`
(no events received yet). The clamp interpreted the empty list as
"position is 0 for this symbol" and phantom-recovered every trade
locally without sending real close MKTs. EBAY had the same divergence
(276 sh of 901 falsely phantom-recovered).

Asserts:
  1. Direct IB returns EMPTY positions list → clamp returns intended
     (don't phantom-recover, let the close MKT fire for real).
  2. Direct IB returns positions for OTHER symbols (non-empty) but our
     symbol absent → clamp returns 0 (legitimate phantom recovery).
  3. Direct returns 0 for our symbol BUT pusher alive and shows shares
     → clamp returns intended (pusher disagrees, fall back to real close).
  4. Direct returns 0 AND pusher confirms 0 (or pusher dead) → clamp
     returns 0 (phantom recovery confirmed).
  5. Direct returns smaller qty than intended AND pusher shows MORE →
     clamp uses min(intended, pusher_abs), not direct's smaller number.
  6. Direction mismatch path still works (refuse close, return 0).
"""
from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, "/app/backend")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _mk_trade(symbol="BMNR", direction="long", id="t1"):
    from services.trading_bot_service import TradeDirection
    d = TradeDirection.LONG if direction == "long" else TradeDirection.SHORT
    return SimpleNamespace(symbol=symbol, id=id, direction=d)


def _mk_pm():
    """Construct PositionManager with minimal stubs."""
    from services.position_manager import PositionManager
    pm = PositionManager.__new__(PositionManager)
    pm._trade_executor = MagicMock()
    pm._db = MagicMock()
    return pm


def _mk_direct_svc(positions_list):
    svc = MagicMock()
    svc.is_available = MagicMock(return_value=True)
    svc.is_connected = MagicMock(return_value=True)
    svc.get_positions = AsyncMock(return_value=positions_list)
    return svc


def test_empty_direct_positions_does_not_phantom_recover():
    """Headline regression: empty direct list ≠ confirmed zero."""
    from services import position_manager as pm_mod

    pm = _mk_pm()
    trade = _mk_trade("BMNR", "long")
    direct_svc = _mk_direct_svc([])  # empty list — direct IB stale

    with patch("services.ib_direct_service.get_ib_direct_service",
               return_value=direct_svc, create=True), \
         patch.object(pm_mod, "logger") as _:
        result = _run(pm._clamp_shares_to_ib_position(
            trade, intended_shares=4443, reason="emergency_flatten"
        ))
    # Did NOT phantom-recover; returned intended for real close.
    assert result == 4443


def test_direct_has_other_symbols_but_not_ours_phantom_recovers():
    """When direct IB is responsive (has rows) but doesn't show our
    symbol, that's positive confirmation we don't hold it."""
    from services import position_manager as pm_mod

    pm = _mk_pm()
    trade = _mk_trade("BMNR", "long")
    # Non-empty list, but BMNR not in it.
    direct_svc = _mk_direct_svc([
        {"symbol": "AAPL", "position": 100},
        {"symbol": "TSLA", "position": -50},
    ])

    with patch("services.ib_direct_service.get_ib_direct_service",
               return_value=direct_svc, create=True), \
         patch.object(pm_mod, "logger") as _, \
         patch("routers.ib._pushed_ib_data",
               {"positions": [{"symbol": "AAPL", "position": 100}]}, create=True), \
         patch("routers.ib.is_pusher_connected",
               return_value=True, create=True):
        result = _run(pm._clamp_shares_to_ib_position(
            trade, intended_shares=100, reason="manual"
        ))
    # Phantom-recovered (returns 0).
    assert result == 0


def test_direct_zero_pusher_disagrees_does_not_phantom_recover():
    """Direct says 0 but pusher shows shares → trust pusher, refuse phantom."""
    from services import position_manager as pm_mod

    pm = _mk_pm()
    trade = _mk_trade("EBAY", "long")
    # Direct list non-empty (responsive) but no EBAY row.
    direct_svc = _mk_direct_svc([
        {"symbol": "AAPL", "position": 100},
    ])

    with patch("services.ib_direct_service.get_ib_direct_service",
               return_value=direct_svc, create=True), \
         patch.object(pm_mod, "logger") as _, \
         patch("routers.ib._pushed_ib_data",
               {"positions": [{"symbol": "EBAY", "position": 901}]}, create=True), \
         patch("routers.ib.is_pusher_connected",
               return_value=True, create=True):
        result = _run(pm._clamp_shares_to_ib_position(
            trade, intended_shares=625, reason="manual"
        ))
    # Pusher disagrees → refuse phantom, send real close.
    assert result == 625


def test_direct_zero_pusher_confirms_zero_phantom_recovers():
    from services import position_manager as pm_mod

    pm = _mk_pm()
    trade = _mk_trade("EBAY", "long")
    direct_svc = _mk_direct_svc([
        {"symbol": "AAPL", "position": 100},
    ])

    with patch("services.ib_direct_service.get_ib_direct_service",
               return_value=direct_svc, create=True), \
         patch.object(pm_mod, "logger") as _, \
         patch("routers.ib._pushed_ib_data",
               {"positions": [{"symbol": "AAPL", "position": 100}]}, create=True), \
         patch("routers.ib.is_pusher_connected",
               return_value=True, create=True):
        result = _run(pm._clamp_shares_to_ib_position(
            trade, intended_shares=100, reason="manual"
        ))
    # Both sources agree on zero → phantom-recover.
    assert result == 0


def test_direct_smaller_than_pusher_uses_pusher_count():
    """Direct says 100 sh, pusher says 901 sh. We trust pusher (direct
    is mid-update). Return min(intended, pusher_abs)."""
    from services import position_manager as pm_mod

    pm = _mk_pm()
    trade = _mk_trade("EBAY", "long")
    direct_svc = _mk_direct_svc([
        {"symbol": "EBAY", "position": 100},
    ])

    with patch("services.ib_direct_service.get_ib_direct_service",
               return_value=direct_svc, create=True), \
         patch.object(pm_mod, "logger") as _, \
         patch("routers.ib._pushed_ib_data",
               {"positions": [{"symbol": "EBAY", "position": 901}]}, create=True), \
         patch("routers.ib.is_pusher_connected",
               return_value=True, create=True):
        result = _run(pm._clamp_shares_to_ib_position(
            trade, intended_shares=901, reason="manual"
        ))
    # Pusher shows 901 > direct's 100 — use pusher.
    assert result == 901


def test_direction_mismatch_still_refuses():
    """Bot thinks long, IB shows short → refuse close (return 0)."""
    from services import position_manager as pm_mod

    pm = _mk_pm()
    trade = _mk_trade("BMNR", "long")
    # IB has SHORT 100 BMNR while bot tracks long.
    direct_svc = _mk_direct_svc([
        {"symbol": "BMNR", "position": -100},
    ])

    with patch("services.ib_direct_service.get_ib_direct_service",
               return_value=direct_svc, create=True), \
         patch.object(pm_mod, "logger") as _:
        result = _run(pm._clamp_shares_to_ib_position(
            trade, intended_shares=100, reason="manual"
        ))
    # Refused (direction mismatch).
    assert result == 0


def test_direct_unavailable_returns_intended():
    """Pre-v19.34.27 fallback: when direct IB isn't up, return intended."""
    from services import position_manager as pm_mod

    pm = _mk_pm()
    trade = _mk_trade("BMNR", "long")
    svc = MagicMock()
    svc.is_available = MagicMock(return_value=False)
    svc.is_connected = MagicMock(return_value=False)

    with patch("services.ib_direct_service.get_ib_direct_service",
               return_value=svc, create=True), \
         patch.object(pm_mod, "logger") as _:
        result = _run(pm._clamp_shares_to_ib_position(
            trade, intended_shares=4443, reason="manual"
        ))
    assert result == 4443
