"""
test_ib_direct_service_v19_34_25.py — pins the v19.34.25 direct IB
service contract.

Phase 1 scope: standalone connection lifecycle + diagnostic methods.
The service is NOT wired into trade_executor yet — that's Phase 2 next
session. These tests verify the Phase 1 surface using a mocked `IB()`
instance so they run without any IB Gateway.

Tests below cover:
  - Singleton accessor returns the same instance across calls.
  - `is_available()` reports ib_async install state honestly.
  - `connect()` — happy path: socket up + managedAccounts non-empty
    → connected=True, authorized_to_trade=True.
  - `connect()` — "logged in on another platform": socket up but
    managedAccounts empty → connected=True, authorized_to_trade=False.
    THIS IS THE EXACT FAILURE MODE FROM TODAY'S SESSION.
  - `connect()` — connect failure (refused / timeout) → success=False
    + last_connect_error populated.
  - `connect()` is idempotent — second call no-ops if already connected.
  - `disconnect()` flips state cleanly.
  - `get_positions()` returns the IB API position objects flattened to
    a JSON-serializable shape (no ObjectId-style nasties).
  - `place_market_order()` blocked in read_only mode.
  - `place_market_order()` blocked when not authorized_to_trade (the
    "logged in on another platform" guard, defense in depth).
  - `status()` payload contract (UI keys off these field names).
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_fake_ib(connected=True, managed_accounts=("DU615665",)):
    """Build a mock that quacks like ib_async.IB()."""
    ib = MagicMock()
    ib.isConnected.return_value = connected
    ib.managedAccounts.return_value = list(managed_accounts)
    ib.connectAsync = AsyncMock(return_value=None)
    ib.positions.return_value = []
    ib.trades.return_value = []
    ib.disconnect.return_value = None
    ib.placeOrder.return_value = SimpleNamespace(
        order=SimpleNamespace(orderId=42, permId=99),
        orderStatus=SimpleNamespace(status="Submitted"),
    )
    ib.qualifyContracts = MagicMock(return_value=None)
    return ib


# ─────────────────────────────────────────────────────────────────────
# 1. Singleton accessor.
# ─────────────────────────────────────────────────────────────────────
def test_singleton_accessor_returns_same_instance():
    import services.ib_direct_service as mod
    mod._singleton = None  # reset for the test
    a = mod.get_ib_direct_service()
    b = mod.get_ib_direct_service()
    assert a is b


# ─────────────────────────────────────────────────────────────────────
# 2. ib_async availability flag mirrors the import.
# ─────────────────────────────────────────────────────────────────────
def test_is_available_reflects_module_state():
    from services.ib_direct_service import IBDirectService, IB_ASYNC_AVAILABLE
    svc = IBDirectService()
    assert svc.is_available() is IB_ASYNC_AVAILABLE


# ─────────────────────────────────────────────────────────────────────
# 3. Happy path connect: socket up + managedAccounts populated →
#    authorized_to_trade=True.
# ─────────────────────────────────────────────────────────────────────
def test_connect_happy_path_authorizes_to_trade():
    from services.ib_direct_service import IBDirectService, IBDirectConfig
    svc = IBDirectService(IBDirectConfig(host="x", port=4002, client_id=11))

    fake_ib = _make_fake_ib(connected=True, managed_accounts=("DU615665",))
    with patch("services.ib_direct_service.IB", return_value=fake_ib):
        result = _run(svc.connect())

    assert result.get("success") is not False, result
    assert svc.is_connected() is True
    assert svc.is_authorized_to_trade() is True
    fake_ib.connectAsync.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────────
# 4. CRITICAL: socket up but managedAccounts EMPTY →
#    authorized_to_trade=False. This is today's "logged in on another
#    platform" silent-failure mode and the whole reason this service
#    exists. Catching it here at connect time is the defense in depth.
# ─────────────────────────────────────────────────────────────────────
def test_connect_socket_up_but_no_brokerage_perms():
    from services.ib_direct_service import IBDirectService
    svc = IBDirectService()

    fake_ib = _make_fake_ib(connected=True, managed_accounts=())
    with patch("services.ib_direct_service.IB", return_value=fake_ib):
        result = _run(svc.connect())

    assert svc.is_connected() is True       # socket layer is fine
    assert svc.is_authorized_to_trade() is False  # but trade layer ISN'T
    # The status payload must surface this so the UI / curl can see it.
    status = svc.status()
    assert status["connected"] is True
    assert status["authorized_to_trade"] is False
    assert status["managed_accounts"] == []


# ─────────────────────────────────────────────────────────────────────
# 5. Connect failure (refused / timeout) → success=False + error
#    captured for the operator to see in the status payload.
# ─────────────────────────────────────────────────────────────────────
def test_connect_failure_records_error():
    from services.ib_direct_service import IBDirectService
    svc = IBDirectService()

    fake_ib = _make_fake_ib()
    fake_ib.connectAsync.side_effect = ConnectionRefusedError("ECONNREFUSED 192.168.50.1:4002")
    with patch("services.ib_direct_service.IB", return_value=fake_ib):
        result = _run(svc.connect())

    assert result.get("success") is False
    assert "ECONNREFUSED" in result.get("error", "")
    assert svc.is_connected() is False
    assert svc.status()["last_connect_error"] is not None


# ─────────────────────────────────────────────────────────────────────
# 6. connect() is idempotent — second call when already connected
#    returns immediately without re-running connectAsync.
# ─────────────────────────────────────────────────────────────────────
def test_connect_is_idempotent():
    from services.ib_direct_service import IBDirectService
    svc = IBDirectService()

    fake_ib = _make_fake_ib(connected=True, managed_accounts=("DU615665",))
    with patch("services.ib_direct_service.IB", return_value=fake_ib):
        _run(svc.connect())
        _run(svc.connect())   # second call should bail at is_connected()

    fake_ib.connectAsync.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────────
# 7. disconnect() flips state to clean.
# ─────────────────────────────────────────────────────────────────────
def test_disconnect_clears_state():
    from services.ib_direct_service import IBDirectService
    svc = IBDirectService()

    fake_ib = _make_fake_ib(connected=True, managed_accounts=("DU615665",))
    with patch("services.ib_direct_service.IB", return_value=fake_ib):
        _run(svc.connect())
        assert svc.is_connected() is True

        # After disconnect, the fake should also flip to disconnected.
        fake_ib.isConnected.return_value = False
        _run(svc.disconnect())

    assert svc.is_connected() is False
    assert svc.is_authorized_to_trade() is False


# ─────────────────────────────────────────────────────────────────────
# 8. get_positions() flattens IB position objects to JSON-safe dicts.
# ─────────────────────────────────────────────────────────────────────
def test_get_positions_returns_json_safe_dicts():
    from services.ib_direct_service import IBDirectService
    svc = IBDirectService()

    fake_contract = SimpleNamespace(symbol="FDX", secType="STK", exchange="SMART")
    fake_pos = SimpleNamespace(account="DU615665", contract=fake_contract,
                               position=369.0, avgCost=360.73)
    fake_ib = _make_fake_ib(connected=True, managed_accounts=("DU615665",))
    fake_ib.positions.return_value = [fake_pos]

    with patch("services.ib_direct_service.IB", return_value=fake_ib):
        _run(svc.connect())
        positions = _run(svc.get_positions())

    assert len(positions) == 1
    p = positions[0]
    assert p["symbol"] == "FDX"
    assert p["position"] == 369.0
    assert p["avg_cost"] == 360.73
    assert p["account"] == "DU615665"
    # Make sure no contract object snuck through unflattened.
    assert isinstance(p["symbol"], str)


# ─────────────────────────────────────────────────────────────────────
# 9. place_market_order blocked in read_only mode (defense for the
#    "first dry run on a new install" config).
# ─────────────────────────────────────────────────────────────────────
def test_place_market_order_blocked_in_read_only_mode():
    from services.ib_direct_service import IBDirectService, IBDirectConfig
    svc = IBDirectService(IBDirectConfig(read_only=True))

    fake_ib = _make_fake_ib(connected=True, managed_accounts=("DU615665",))
    with patch("services.ib_direct_service.IB", return_value=fake_ib):
        _run(svc.connect())
        result = _run(svc.place_market_order("FDX", "BUY", 100))

    assert result["success"] is False
    assert "read_only" in result["error"]
    fake_ib.placeOrder.assert_not_called()


# ─────────────────────────────────────────────────────────────────────
# 10. place_market_order blocked when authorized_to_trade=False (the
#     "logged in on another platform" guard — defense in depth).
# ─────────────────────────────────────────────────────────────────────
def test_place_market_order_blocked_when_not_authorized():
    from services.ib_direct_service import IBDirectService
    svc = IBDirectService()

    fake_ib = _make_fake_ib(connected=True, managed_accounts=())  # KICKED
    with patch("services.ib_direct_service.IB", return_value=fake_ib):
        _run(svc.connect())
        result = _run(svc.place_market_order("FDX", "SELL", 369))

    assert result["success"] is False
    assert "authorized" in result["error"].lower()
    fake_ib.placeOrder.assert_not_called()


# ─────────────────────────────────────────────────────────────────────
# 11. status() payload — UI/curl keys off these field names.
# ─────────────────────────────────────────────────────────────────────
def test_status_payload_contract():
    from services.ib_direct_service import IBDirectService
    svc = IBDirectService()
    s = svc.status()
    for key in ("success", "connected", "authorized_to_trade",
                "host", "port", "client_id", "read_only",
                "managed_accounts", "ib_async_available"):
        assert key in s, f"missing key {key} in status payload"
