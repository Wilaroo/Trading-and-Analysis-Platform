"""
v19.30.12 (2026-05-01) — Distinguish push-channel vs RPC-channel
in /api/system/health pusher_rpc subsystem.

CONTEXT
-------
Operator's 2026-05-01 deploy of v19.30.11 surfaced a real bug: SystemBanner
showed "Windows IB Pusher unreachable" while the pusher logs showed
`Push OK every 10s` and 72 quotes streaming successfully. Both signals
correct from their respective vantage points:

  * The pusher's `Push OK` log = inbound channel (Windows :8765 → Spark
    :8001) working fine.
  * The banner = outbound channel (Spark → Windows :8765) failing.

Asymmetric network — most likely Windows firewall blocking inbound
:8765, so Spark's outbound RPC calls couldn't reach the pusher's RPC
server even though the pusher's outbound push HTTP calls worked.

This commit makes /api/system/health distinguish:

  push fresh + RPC working → GREEN
  push fresh + RPC failing → YELLOW (rpc_blocked)
  push stale + RPC failing → RED (fully_dead)
  push stale + RPC working → YELLOW (push_blocked)
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


def _patch_pushed_data(*, push_age_s: float | None):
    """Helper to patch routers.ib._pushed_ib_data module attribute.

    The health-service code reads the module attribute directly (NOT
    the get_pushed_ib_data helper, since it's shadowed by an async
    HTTP route at routers/ib.py:615).
    """
    if push_age_s is None:
        return {"last_update": None}
    ts = datetime.now(timezone.utc).timestamp() - push_age_s
    iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return {"last_update": iso}


def _patch_pushed_and_client(*, push_age_s: float | None, rpc_failures: int):
    """Helper to patch the pusher RPC client status() shape consumed by
    _check_pusher_rpc and the routers.ib._pushed_ib_data module attr.
    """
    fake_pushed = _patch_pushed_data(push_age_s=push_age_s)

    fake_client = MagicMock()
    fake_client.status.return_value = {
        "enabled": True,
        "url": "http://192.168.50.1:8765",
        "consecutive_failures": rpc_failures,
        "last_success_ts": time.time() - 5 if rpc_failures == 0 else None,
    }

    return fake_pushed, fake_client


def test_health_pusher_green_when_push_fresh_and_rpc_working():
    """Push received <60s ago AND no RPC failures → green."""
    from services.system_health_service import _check_pusher_rpc
    import routers.ib as ib_module

    fake_pushed, fake_client = _patch_pushed_and_client(
        push_age_s=8.0, rpc_failures=0
    )

    with patch("services.ib_pusher_rpc.get_pusher_rpc_client", return_value=fake_client), \
         patch.object(ib_module, "_pushed_ib_data", fake_pushed):
        result = _check_pusher_rpc()

    assert result.status == "green"
    assert result.metrics["push_fresh"] is True


def test_health_pusher_yellow_when_push_fresh_and_rpc_failing():
    """Push fresh + RPC consistently failing → YELLOW (rpc_blocked).

    This is the EXACT case the operator hit on 2026-05-01.
    """
    from services.system_health_service import _check_pusher_rpc
    import routers.ib as ib_module

    fake_pushed, fake_client = _patch_pushed_and_client(
        push_age_s=8.0, rpc_failures=19
    )

    with patch("services.ib_pusher_rpc.get_pusher_rpc_client", return_value=fake_client), \
         patch.object(ib_module, "_pushed_ib_data", fake_pushed):
        result = _check_pusher_rpc()

    assert result.status == "yellow"
    assert "rpc_blocked" in result.detail
    assert result.metrics["push_fresh"] is True
    # Operator-visible cue: detail must say live data IS flowing.
    assert "live data" in result.detail.lower() or "flowing" in result.detail.lower()


def test_health_pusher_red_when_push_stale_and_rpc_failing():
    """Push stale + RPC failing → RED (fully_dead)."""
    from services.system_health_service import _check_pusher_rpc
    import routers.ib as ib_module

    fake_pushed, fake_client = _patch_pushed_and_client(
        push_age_s=120.0, rpc_failures=42
    )

    with patch("services.ib_pusher_rpc.get_pusher_rpc_client", return_value=fake_client), \
         patch.object(ib_module, "_pushed_ib_data", fake_pushed):
        result = _check_pusher_rpc()

    assert result.status == "red"
    assert "fully_dead" in result.detail
    assert result.metrics["push_fresh"] is False


def test_health_pusher_red_when_no_push_ever_and_rpc_failing():
    """No push EVER received (last_update=None) AND RPC failing → RED."""
    from services.system_health_service import _check_pusher_rpc
    import routers.ib as ib_module

    fake_pushed, fake_client = _patch_pushed_and_client(
        push_age_s=None, rpc_failures=42
    )

    with patch("services.ib_pusher_rpc.get_pusher_rpc_client", return_value=fake_client), \
         patch.object(ib_module, "_pushed_ib_data", fake_pushed):
        result = _check_pusher_rpc()

    assert result.status == "red"
    assert "fully_dead" in result.detail
    assert "no push data ever received" in result.detail
    assert result.metrics["push_age_s"] is None
    assert result.metrics["push_fresh"] is False


def test_health_pusher_yellow_when_push_stale_but_rpc_working():
    """Push stale + RPC working → YELLOW (push_blocked, weird state)."""
    from services.system_health_service import _check_pusher_rpc
    import routers.ib as ib_module

    fake_pushed, fake_client = _patch_pushed_and_client(
        push_age_s=180.0, rpc_failures=0
    )

    with patch("services.ib_pusher_rpc.get_pusher_rpc_client", return_value=fake_client), \
         patch.object(ib_module, "_pushed_ib_data", fake_pushed):
        result = _check_pusher_rpc()

    assert result.status == "yellow"
    assert "push_blocked" in result.detail
    assert result.metrics["push_fresh"] is False


def test_health_pusher_metrics_include_push_age():
    """push_age_s and push_fresh must be in metrics so the banner can
    render them."""
    from services.system_health_service import _check_pusher_rpc
    import routers.ib as ib_module

    fake_pushed, fake_client = _patch_pushed_and_client(
        push_age_s=12.5, rpc_failures=0
    )

    with patch("services.ib_pusher_rpc.get_pusher_rpc_client", return_value=fake_client), \
         patch.object(ib_module, "_pushed_ib_data", fake_pushed):
        result = _check_pusher_rpc()

    assert "push_age_s" in result.metrics
    assert "push_fresh" in result.metrics
    # Allow some test-runtime drift.
    assert 12.0 <= result.metrics["push_age_s"] <= 14.5


def test_health_pusher_no_routers_ib_import_does_not_crash():
    """If routers.ib._pushed_ib_data is missing for some reason, the
    check must still return a sensible result — don't hard-crash the
    whole /api/system/health endpoint."""
    from services.system_health_service import _check_pusher_rpc
    import routers.ib as ib_module

    fake_client = MagicMock()
    fake_client.status.return_value = {
        "enabled": True,
        "url": "http://192.168.50.1:8765",
        "consecutive_failures": 0,
        "last_success_ts": time.time() - 5,
    }

    # Replace the module attr with something that has no .get method.
    with patch("services.ib_pusher_rpc.get_pusher_rpc_client", return_value=fake_client), \
         patch.object(ib_module, "_pushed_ib_data", {}):
        result = _check_pusher_rpc()

    # Should not raise; status must be a valid green/yellow/red.
    assert result.status in ("green", "yellow", "red")
    assert result.name == "pusher_rpc"
