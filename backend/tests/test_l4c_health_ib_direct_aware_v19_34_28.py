"""Regression — v19.34.28 L4c.1: _check_ib_gateway() is ib-direct-aware."""
from __future__ import annotations
import os, sys, types
from unittest.mock import patch, MagicMock
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


def _import_health():
    from services import system_health_service as mod
    return mod


def _fake_ib_direct(connected: bool):
    fake = MagicMock()
    fake.is_connected = MagicMock(return_value=connected)
    return fake


def _fake_pusher_status(*, enabled=True, url="http://x:8765",
                       last_success_ts=None, consecutive_failures=0):
    return {"enabled": enabled, "url": url,
            "last_success_ts": last_success_ts,
            "consecutive_failures": consecutive_failures}


def _install_ib_direct_module(connected: bool):
    mod = types.ModuleType("services.ib_direct_service")
    mod.get_ib_direct_service = lambda: _fake_ib_direct(connected)
    sys.modules["services.ib_direct_service"] = mod


def _install_pusher_rpc_module(status_dict):
    mod = types.ModuleType("services.ib_pusher_rpc")
    fake_client = MagicMock()
    fake_client.status = MagicMock(return_value=status_dict)
    mod.get_pusher_rpc_client = lambda: fake_client
    sys.modules["services.ib_pusher_rpc"] = mod


def test_ib_direct_connected_under_direct_mode_returns_green():
    health = _import_health()
    _install_ib_direct_module(connected=True)
    _install_pusher_rpc_module(_fake_pusher_status(consecutive_failures=58))
    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False), \
         patch("services.service_registry.get_service_optional", return_value=None):
        result = health._check_ib_gateway()
    assert result.status == "green", f"got {result.status}: {result.detail}"
    assert "ib-direct" in result.detail.lower()
    assert result.metrics.get("via_ib_direct") is True


def test_ib_direct_disconnected_under_direct_mode_returns_yellow():
    health = _import_health()
    _install_ib_direct_module(connected=False)
    _install_pusher_rpc_module(_fake_pusher_status(consecutive_failures=58))
    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False), \
         patch("services.service_registry.get_service_optional", return_value=None):
        result = health._check_ib_gateway()
    assert result.status == "yellow"
    assert "ib-direct" in result.detail.lower()


def test_pusher_mode_with_healthy_pusher_returns_green():
    health = _import_health()
    _install_pusher_rpc_module(
        _fake_pusher_status(last_success_ts=9999999999.0, consecutive_failures=0))
    with patch.dict(os.environ, {"BOT_ORDER_PATH": "pusher"}, clear=False), \
         patch("services.service_registry.get_service_optional", return_value=None):
        result = health._check_ib_gateway()
    assert result.status == "green"
    assert result.metrics.get("via_pusher") is True


def test_pusher_mode_with_dead_pusher_still_yellows():
    health = _import_health()
    _install_pusher_rpc_module(
        _fake_pusher_status(last_success_ts=None, consecutive_failures=58))
    with patch.dict(os.environ, {"BOT_ORDER_PATH": "pusher"}, clear=False), \
         patch("services.service_registry.get_service_optional", return_value=None):
        result = health._check_ib_gateway()
    assert result.status == "yellow"
    assert "no IB path" in result.detail


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
