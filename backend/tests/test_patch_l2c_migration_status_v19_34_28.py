"""v19.34.28 Patch L2c — Migration-status endpoint regression tests.

Calls the endpoint handler directly (no httpx/TestClient) — keeps tests
fast and version-independent.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from unittest.mock import patch, MagicMock

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import pytest

from routers.ib_direct_router import ib_direct_migration_status


def _healthy_status():
    return {
        "success": True,
        "connected": True,
        "authorized_to_trade": True,
        "host": "x", "port": 4002, "client_id": 11, "read_only": False,
        "managed_accounts": ["DUN615665"],
        "stability": {
            "drop_count_total": 0,
            "reconnect_count_total": 0,
            "last_drop_at": None,
            "last_reconnect_at": None,
            "watchdog_running": True,
            "heartbeat_failures_total": 0,
            "last_heartbeat_ok_at": 9999999999.0,
            "last_heartbeat_failed_at": None,
        },
    }


def _stub_svc(status_payload):
    svc = MagicMock()
    svc.status.return_value = status_payload
    # Methods that the verdict logic introspects via callable(getattr(...)).
    for m in ("place_bracket_order", "place_entry", "place_stop",
              "place_oca_stop_target", "get_positions_fresh",
              "get_open_orders", "get_account_summary"):
        setattr(svc, m, lambda *a, **k: None)
    return svc


def test_l2c_migration_status_ready_when_all_green():
    svc = _stub_svc(_healthy_status())
    env = {k: v for k, v in os.environ.items() if k != "BOT_ORDER_PATH"}
    with patch.dict(os.environ, env, clear=True), \
         patch("routers.ib_direct_router.get_ib_direct_service", return_value=svc):
        body = asyncio.run(ib_direct_migration_status())
    assert body["success"] is True
    assert body["verdict"] == "ready"
    assert body["order_path"] == "pusher"
    assert body["checks"]["ib_direct_connected"] is True
    assert body["checks"]["ib_direct_authorized"] is True
    assert body["checks"]["watchdog_running"] is True
    assert body["checks"]["write_paths_scaffolded"] is True
    assert body["checks"]["read_paths_wired"] is True
    assert body["recommendations"] == []


def test_l2c_migration_status_blocked_when_socket_down():
    s = _healthy_status()
    s["connected"] = False
    s["authorized_to_trade"] = False
    svc = _stub_svc(s)
    with patch("routers.ib_direct_router.get_ib_direct_service", return_value=svc):
        body = asyncio.run(ib_direct_migration_status())
    assert body["verdict"] == "blocked"
    assert any("socket DOWN" in rec for rec in body["recommendations"])


def test_l2c_migration_status_degraded_when_recent_drop():
    s = _healthy_status()
    s["stability"]["drop_count_total"] = 1
    s["stability"]["last_drop_at"] = time.time() - 30   # 30s ago
    svc = _stub_svc(s)
    with patch("routers.ib_direct_router.get_ib_direct_service", return_value=svc):
        body = asyncio.run(ib_direct_migration_status())
    assert body["verdict"] == "degraded"
    assert body["checks"]["recent_drops_5m"] == 1
    assert any("drop" in rec.lower() for rec in body["recommendations"])


def test_l2c_migration_status_warns_when_direct_but_not_ready():
    """If BOT_ORDER_PATH=direct but verdict != ready, recommendation
    should suggest flipping back to pusher."""
    s = _healthy_status()
    s["connected"] = False
    svc = _stub_svc(s)
    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False), \
         patch("routers.ib_direct_router.get_ib_direct_service", return_value=svc):
        body = asyncio.run(ib_direct_migration_status())
    assert body["order_path"] == "direct"
    assert body["verdict"] != "ready"
    assert "flipping back to pusher" in body["recommendations"][0]


def test_l2c_migration_status_unauthorized_surface():
    s = _healthy_status()
    s["authorized_to_trade"] = False
    svc = _stub_svc(s)
    with patch("routers.ib_direct_router.get_ib_direct_service", return_value=svc):
        body = asyncio.run(ib_direct_migration_status())
    assert body["verdict"] == "blocked"
    assert any("managedAccounts empty" in rec for rec in body["recommendations"])
