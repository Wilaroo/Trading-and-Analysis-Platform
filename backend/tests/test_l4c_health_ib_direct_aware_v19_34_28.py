"""
Regression test — v19.34.28 L4c.1
=================================
Verifies `services.system_health_service._check_ib_gateway()` is aware of
`ib_direct_service` under `BOT_ORDER_PATH=direct`.

Before the patch: any deployment with no legacy `ib_service` registration
would fall through to the pusher-reachability branch. If the pusher_rpc
channel had >=5 consecutive failures (very common on a fresh boot or when
Windows firewall blocks inbound on :8765), the health check would emit:

    ib_gateway → yellow · no IB path: ib_service not registered and pusher unreachable

…even though `ib_direct_service` was connected and orders/positions were
flowing fine.

After the patch:
  * BOT_ORDER_PATH=direct AND ib_direct connected     → GREEN
  * BOT_ORDER_PATH=direct AND ib_direct disconnected  → YELLOW (legitimate)
  * BOT_ORDER_PATH=pusher AND pusher reachable        → GREEN (unchanged)
  * BOT_ORDER_PATH=pusher AND pusher unreachable      → YELLOW (unchanged)

Run:
    cd ~/Trading-and-Analysis-Platform/backend
    python -m pytest tests/test_l4c_health_ib_direct_aware_v19_34_28.py -v
"""

from __future__ import annotations

import os
import sys
import types
from unittest.mock import patch, MagicMock

import pytest

# Make `services.*` importable when run from backend/ root
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


def _import_health():
    from services import system_health_service as mod  # noqa: WPS433
    return mod


# ─────────────────────────────────────────────────────────────────────────
# Helpers — build fake ib_direct & pusher_rpc clients we can swap in.
# ─────────────────────────────────────────────────────────────────────────

def _fake_ib_direct(connected: bool):
    fake = MagicMock()
    fake.is_connected = MagicMock(return_value=connected)
    return fake


def _fake_pusher_status(*, enabled=True, url="http://x:8765",
                       last_success_ts=None, consecutive_failures=0):
    return {
        "enabled": enabled,
        "url": url,
        "last_success_ts": last_success_ts,
        "consecutive_failures": consecutive_failures,
    }


def _install_ib_direct_module(connected: bool):
    """Inject a fake `services.ib_direct_service` module so the
    `from services.ib_direct_service import get_ib_direct_service`
    inside the health check resolves."""
    mod = types.ModuleType("services.ib_direct_service")
    mod.get_ib_direct_service = lambda: _fake_ib_direct(connected)
    sys.modules["services.ib_direct_service"] = mod


def _install_pusher_rpc_module(status_dict):
    mod = types.ModuleType("services.ib_pusher_rpc")
    fake_client = MagicMock()
    fake_client.status = MagicMock(return_value=status_dict)
    mod.get_pusher_rpc_client = lambda: fake_client
    sys.modules["services.ib_pusher_rpc"] = mod


# ─────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────

def test_ib_direct_connected_under_direct_mode_returns_green():
    """The bug scenario: no legacy `ib_service`, BOT_ORDER_PATH=direct,
    `ib_direct_service.is_connected()` = True. Pusher RPC is failing
    (rpc_blocked). Pre-patch this returned yellow ("no IB path"). Post-patch
    it MUST return green because the bot has a direct IB path."""
    health = _import_health()
    _install_ib_direct_module(connected=True)
    _install_pusher_rpc_module(_fake_pusher_status(consecutive_failures=58))

    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False), \
         patch("services.service_registry.get_service_optional",
               return_value=None):
        result = health._check_ib_gateway()

    assert result.status == "green", (
        f"Expected green under direct mode with ib_direct connected, "
        f"got {result.status}: {result.detail}"
    )
    assert "ib-direct" in result.detail.lower()
    assert result.metrics.get("via_ib_direct") is True


def test_ib_direct_disconnected_under_direct_mode_returns_yellow():
    """Legitimate degradation: operator chose direct mode but the service
    isn't connected. Must be yellow, NOT silently green."""
    health = _import_health()
    _install_ib_direct_module(connected=False)
    _install_pusher_rpc_module(_fake_pusher_status(consecutive_failures=58))

    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False), \
         patch("services.service_registry.get_service_optional",
               return_value=None):
        result = health._check_ib_gateway()

    assert result.status == "yellow"
    assert "ib-direct" in result.detail.lower()
    assert result.metrics.get("via_ib_direct") is False


def test_pusher_mode_with_healthy_pusher_returns_green():
    """Regression: don't break the pusher-only deployment shape."""
    health = _import_health()
    _install_pusher_rpc_module(
        _fake_pusher_status(last_success_ts=9999999999.0, consecutive_failures=0)
    )

    with patch.dict(os.environ, {"BOT_ORDER_PATH": "pusher"}, clear=False), \
         patch("services.service_registry.get_service_optional",
               return_value=None):
        result = health._check_ib_gateway()

    assert result.status == "green"
    assert result.metrics.get("via_pusher") is True


def test_pusher_mode_with_dead_pusher_still_yellows():
    """Regression: the genuine 'no IB path' case under pusher mode must
    still surface as yellow."""
    health = _import_health()
    _install_pusher_rpc_module(
        _fake_pusher_status(last_success_ts=None, consecutive_failures=58)
    )

    with patch.dict(os.environ, {"BOT_ORDER_PATH": "pusher"}, clear=False), \
         patch("services.service_registry.get_service_optional",
               return_value=None):
        result = health._check_ib_gateway()

    assert result.status == "yellow"
    assert "no IB path" in result.detail


def test_direct_mode_with_unimportable_ib_direct_falls_back_to_pusher_branch():
    """Defensive: if BOT_ORDER_PATH=direct but `services.ib_direct_service`
    blows up on import, we must NOT raise — we fall through to the pusher
    branch."""
    health = _import_health()
    # Remove any cached ib_direct_service module so the import inside
    # the health check fails.
    sys.modules.pop("services.ib_direct_service", None)
    _install_pusher_rpc_module(
        _fake_pusher_status(last_success_ts=9999999999.0, consecutive_failures=0)
    )

    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False), \
         patch("services.service_registry.get_service_optional",
               return_value=None), \
         patch.dict(sys.modules, {"services.ib_direct_service": None}):
        # The import-on-demand inside _check_ib_gateway() should hit
        # ImportError, be swallowed, and we fall through to the pusher branch.
        result = health._check_ib_gateway()

    # Pusher is reachable in this scenario → green via pusher branch.
    assert result.status == "green"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
