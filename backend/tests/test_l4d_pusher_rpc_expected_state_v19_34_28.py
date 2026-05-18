"""
Regression — v19.34.28 L4d
==========================
Tests the new `/api/system/pusher-rpc/expected-state` endpoint logic
(`pusher_rpc_expected_state` in `routers/system_router.py`).

We don't spin a TestClient — we import the handler directly and exercise
all four state-matrix cells:

  | order_path | rpc_failing | push_fresh | expected_state    | actual_state | intentional |
  |------------|-------------|------------|-------------------|--------------|-------------|
  | direct     | True        | True       | offline_ok        | rpc_blocked  | True        |  ← the L3 norm
  | direct     | False       | True       | offline_ok        | healthy      | True        |
  | direct     | True        | False      | offline_ok        | fully_dead   | False       |  ← real outage
  | pusher     | False       | True       | online_required   | healthy      | True        |
  | pusher     | True        | True       | online_required   | rpc_blocked  | False       |  ← alert
"""

from __future__ import annotations

import os
import sys
import time
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


def _import_handler():
    from routers import system_router as mod  # noqa: WPS433
    return mod.pusher_rpc_expected_state


def _install_pusher_rpc_module(*, consecutive_failures: int,
                               last_success_ts=None,
                               enabled: bool = True,
                               url: str = "http://x:8765"):
    mod = types.ModuleType("services.ib_pusher_rpc")
    fake_client = MagicMock()
    fake_client.status = MagicMock(return_value={
        "enabled": enabled,
        "url": url,
        "last_success_ts": last_success_ts,
        "consecutive_failures": consecutive_failures,
    })
    mod.get_pusher_rpc_client = lambda: fake_client
    sys.modules["services.ib_pusher_rpc"] = mod


def _install_ib_module(*, push_age_s):
    """Install a fake `routers.ib` module with _pushed_ib_data.last_update."""
    mod = types.ModuleType("routers.ib")
    if push_age_s is None:
        mod._pushed_ib_data = {}
    else:
        ts = datetime.now(timezone.utc) - timedelta(seconds=push_age_s)
        mod._pushed_ib_data = {"last_update": ts.isoformat()}
    sys.modules["routers.ib"] = mod


# ─── direct mode tests ────────────────────────────────────────────────────

def test_direct_mode_rpc_blocked_is_intentional():
    """The exact L3 steady state: direct mode, RPC blocked, push fresh.
    Must be flagged as intentional so monitoring does not alert."""
    handler = _import_handler()
    _install_pusher_rpc_module(consecutive_failures=58)
    _install_ib_module(push_age_s=2.0)

    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False):
        out = handler()

    assert out["order_path"] == "direct"
    assert out["expected_state"] == "offline_ok"
    assert out["actual_state"] == "rpc_blocked"
    assert out["intentional"] is True
    assert "ib_direct_service" in out["expected_label"]


def test_direct_mode_fully_healthy_is_intentional():
    handler = _import_handler()
    _install_pusher_rpc_module(consecutive_failures=0,
                               last_success_ts=time.time())
    _install_ib_module(push_age_s=2.0)

    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False):
        out = handler()

    assert out["expected_state"] == "offline_ok"
    assert out["actual_state"] == "healthy"
    assert out["intentional"] is True


def test_direct_mode_fully_dead_is_not_intentional():
    """Even under direct mode, if BOTH push channel AND rpc are dead,
    something real is broken — operator should know."""
    handler = _import_handler()
    _install_pusher_rpc_module(consecutive_failures=58)
    _install_ib_module(push_age_s=None)  # no push data ever

    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False):
        out = handler()

    assert out["expected_state"] == "offline_ok"
    assert out["actual_state"] == "fully_dead"
    assert out["intentional"] is False


# ─── pusher mode tests ────────────────────────────────────────────────────

def test_pusher_mode_healthy_is_intentional():
    handler = _import_handler()
    _install_pusher_rpc_module(consecutive_failures=0,
                               last_success_ts=time.time())
    _install_ib_module(push_age_s=2.0)

    with patch.dict(os.environ, {"BOT_ORDER_PATH": "pusher"}, clear=False):
        out = handler()

    assert out["expected_state"] == "online_required"
    assert out["actual_state"] == "healthy"
    assert out["intentional"] is True


def test_pusher_mode_rpc_blocked_triggers_alert():
    """Under pusher mode RPC is the order path — failures are real."""
    handler = _import_handler()
    _install_pusher_rpc_module(consecutive_failures=58)
    _install_ib_module(push_age_s=2.0)

    with patch.dict(os.environ, {"BOT_ORDER_PATH": "pusher"}, clear=False):
        out = handler()

    assert out["expected_state"] == "online_required"
    assert out["actual_state"] == "rpc_blocked"
    assert out["intentional"] is False  # ← should fire an alert


# ─── shape tests ──────────────────────────────────────────────────────────

def test_response_shape_is_stable():
    handler = _import_handler()
    _install_pusher_rpc_module(consecutive_failures=0,
                               last_success_ts=time.time())
    _install_ib_module(push_age_s=2.0)

    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False):
        out = handler()

    for key in ("order_path", "expected_state", "expected_label",
                "actual_state", "intentional", "rpc", "push", "as_of"):
        assert key in out, f"missing key {key} in response"
    for key in ("enabled", "url", "consecutive_failures", "last_success_age_s"):
        assert key in out["rpc"]
    for key in ("age_s", "fresh"):
        assert key in out["push"]
    assert isinstance(out["intentional"], bool)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
