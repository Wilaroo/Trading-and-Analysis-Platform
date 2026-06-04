"""Regression — v19.34.28 L4d: /api/system/pusher-rpc/expected-state."""
from __future__ import annotations
import os, sys, time, types
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


def _import_handler():
    from routers import system_router as mod
    return mod.pusher_rpc_expected_state


def _install_pusher_rpc_module(*, consecutive_failures, last_success_ts=None,
                               enabled=True, url="http://x:8765"):
    mod = types.ModuleType("services.ib_pusher_rpc")
    fake_client = MagicMock()
    fake_client.status = MagicMock(return_value={
        "enabled": enabled, "url": url,
        "last_success_ts": last_success_ts,
        "consecutive_failures": consecutive_failures,
    })
    mod.get_pusher_rpc_client = lambda: fake_client
    sys.modules["services.ib_pusher_rpc"] = mod


def _install_ib_module(*, push_age_s):
    mod = types.ModuleType("routers.ib")
    if push_age_s is None:
        mod._pushed_ib_data = {}
    else:
        ts = datetime.now(timezone.utc) - timedelta(seconds=push_age_s)
        mod._pushed_ib_data = {"last_update": ts.isoformat()}
    sys.modules["routers.ib"] = mod


def test_direct_mode_rpc_blocked_is_intentional():
    handler = _import_handler()
    _install_pusher_rpc_module(consecutive_failures=58)
    _install_ib_module(push_age_s=2.0)
    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False):
        out = handler()
    assert out["order_path"] == "direct"
    assert out["expected_state"] == "offline_ok"
    assert out["actual_state"] == "rpc_blocked"
    assert out["intentional"] is True


def test_direct_mode_fully_healthy_is_intentional():
    handler = _import_handler()
    _install_pusher_rpc_module(consecutive_failures=0, last_success_ts=time.time())
    _install_ib_module(push_age_s=2.0)
    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False):
        out = handler()
    assert out["expected_state"] == "offline_ok"
    assert out["actual_state"] == "healthy"
    assert out["intentional"] is True


def test_direct_mode_fully_dead_is_not_intentional():
    handler = _import_handler()
    _install_pusher_rpc_module(consecutive_failures=58)
    _install_ib_module(push_age_s=None)
    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False):
        out = handler()
    assert out["expected_state"] == "offline_ok"
    assert out["actual_state"] == "fully_dead"
    assert out["intentional"] is False


def test_pusher_mode_healthy_is_intentional():
    handler = _import_handler()
    _install_pusher_rpc_module(consecutive_failures=0, last_success_ts=time.time())
    _install_ib_module(push_age_s=2.0)
    with patch.dict(os.environ, {"BOT_ORDER_PATH": "pusher"}, clear=False):
        out = handler()
    assert out["expected_state"] == "online_required"
    assert out["actual_state"] == "healthy"
    assert out["intentional"] is True


def test_pusher_mode_rpc_blocked_triggers_alert():
    handler = _import_handler()
    _install_pusher_rpc_module(consecutive_failures=58)
    _install_ib_module(push_age_s=2.0)
    with patch.dict(os.environ, {"BOT_ORDER_PATH": "pusher"}, clear=False):
        out = handler()
    assert out["expected_state"] == "online_required"
    assert out["actual_state"] == "rpc_blocked"
    assert out["intentional"] is False


def test_response_shape_is_stable():
    handler = _import_handler()
    _install_pusher_rpc_module(consecutive_failures=0, last_success_ts=time.time())
    _install_ib_module(push_age_s=2.0)
    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False):
        out = handler()
    for k in ("order_path","expected_state","expected_label","actual_state",
              "intentional","rpc","push","as_of"):
        assert k in out
    assert isinstance(out["intentional"], bool)
