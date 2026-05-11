"""
v19.34.73 — Health-monitor pusher-aware IB-gateway probe regression
=====================================================================

Background
----------
The DGX deploys backend without opening its own IB socket — all IB
traffic flows through the Windows pusher. `ib_service._connected` is
permanently False because the backend never authenticates with IB
directly. Pre-v19.34.73 this produced a permanent "IB Gateway not
connected" false-negative in `/api/risk/health/quick-status`.

Fix
---
The probe now consults `routers.ib.is_pusher_connected()` FIRST. A
fresh pusher heartbeat (≤ 90s) means IB Gateway is healthy on the
other end — the pusher only emits data after a successful IB auth +
subscribe. Direct-socket check remains as a fallback for legacy
deployments.

Assertions
----------
1. Pusher fresh → HEALTHY with `transport=pusher`, no error message.
2. Pusher stale + no direct → UNHEALTHY with a specific error message.
3. Pusher stale + direct connected → HEALTHY with `transport=direct`.
4. No pusher module + no direct service → UNKNOWN.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, "/app/backend")


def _make_comp():
    from services.health_monitor import ComponentHealth, ComponentCategory
    return ComponentHealth("ib_gateway", ComponentCategory.DATA_FEED)


def _make_monitor(ib_service=None):
    """Build a HealthMonitor instance with the IB service shim of our choosing.
    `_check_ib_gateway` is the only method we test so other state can be empty.
    """
    from services.health_monitor import HealthMonitorService
    mon = HealthMonitorService()
    mon._ib_service = ib_service
    return mon


def test_pusher_fresh_marks_healthy():
    from services.health_monitor import HealthStatus
    mon = _make_monitor(ib_service=None)
    comp = _make_comp()
    with patch("routers.ib.is_pusher_connected", return_value=True), \
         patch("routers.ib._pushed_ib_data", {"last_update": "2026-05-11T14:14:00+00:00"}):
        mon._check_ib_gateway(comp)
    assert comp.status == HealthStatus.HEALTHY
    assert comp.metrics.get("transport") == "pusher"
    assert comp.metrics.get("pusher_last_update") == "2026-05-11T14:14:00+00:00"
    assert comp.error_message is None


def test_pusher_stale_no_direct_marks_unhealthy():
    from services.health_monitor import HealthStatus
    mon = _make_monitor(ib_service=None)
    comp = _make_comp()
    with patch("routers.ib.is_pusher_connected", return_value=False), \
         patch("routers.ib._pushed_ib_data", {"last_update": "2026-05-11T12:00:00+00:00"}):
        mon._check_ib_gateway(comp)
    assert comp.status == HealthStatus.UNHEALTHY
    assert "Pusher stale" in (comp.error_message or "")


def test_pusher_stale_direct_connected_marks_healthy():
    from services.health_monitor import HealthStatus
    direct_svc = SimpleNamespace(_connected=True)
    mon = _make_monitor(ib_service=direct_svc)
    comp = _make_comp()
    with patch("routers.ib.is_pusher_connected", return_value=False), \
         patch("routers.ib._pushed_ib_data", {"last_update": None}):
        mon._check_ib_gateway(comp)
    assert comp.status == HealthStatus.HEALTHY
    assert comp.metrics.get("transport") == "direct"
    assert comp.error_message is None


def test_pusher_stale_direct_disconnected_marks_unhealthy():
    from services.health_monitor import HealthStatus
    direct_svc = SimpleNamespace(_connected=False)
    mon = _make_monitor(ib_service=direct_svc)
    comp = _make_comp()
    with patch("routers.ib.is_pusher_connected", return_value=False), \
         patch("routers.ib._pushed_ib_data", {"last_update": "2026-05-11T10:00:00+00:00"}):
        mon._check_ib_gateway(comp)
    assert comp.status == HealthStatus.UNHEALTHY
    assert "pusher stale" in (comp.error_message or "").lower()
    assert "direct socket disconnected" in (comp.error_message or "").lower()


def test_no_transport_no_history_marks_unknown():
    from services.health_monitor import HealthStatus
    mon = _make_monitor(ib_service=None)
    comp = _make_comp()
    with patch("routers.ib.is_pusher_connected", return_value=False), \
         patch("routers.ib._pushed_ib_data", {"last_update": None}):
        mon._check_ib_gateway(comp)
    # Never had pusher data + no direct service → UNKNOWN is correct.
    assert comp.status == HealthStatus.UNKNOWN
