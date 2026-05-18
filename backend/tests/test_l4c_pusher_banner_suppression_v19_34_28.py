"""
v19.34.28 Patch L4c — Suppress the "Spark→pusher RPC blocked" banner
when BOT_ORDER_PATH=direct.

Under direct mode the pusher RPC channel is intentionally offline
(orders bypass the pusher via ib_direct). The orange warning banner
that was correct under pusher mode becomes operator noise. L4c
suppresses ONLY the `pusher_rpc_blocked` sub-case; `pusher_rpc_dead`
(push channel ALSO down) and `pusher_rpc_partial` remain alarmed
because those still represent real failures of the data lifeline.
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from routers import system_banner as sb


def _make_snapshot(*, pusher_status, push_fresh, consecutive_failures, push_age_s=2.0):
    """Build a minimal health snapshot for the banner logic."""
    return {
        "subsystems": [
            {
                "name": "pusher_rpc",
                "status": pusher_status,
                "metrics": {
                    "consecutive_failures": consecutive_failures,
                    "push_fresh": push_fresh,
                    "push_age_s": push_age_s,
                },
                "detail": "test snapshot",
            },
            {"name": "mongo", "status": "green", "metrics": {}, "detail": "ok"},
            {"name": "ib_gateway", "status": "green", "metrics": {}, "detail": "ok"},
        ],
        "as_of": "2026-05-18T16:00:00Z",
    }


def _seed_red_history(sub_key, seconds_red):
    """Pre-seed `_red_since_ts` so the 30s threshold is already passed."""
    sb._red_since_ts[sub_key] = time.time() - seconds_red


def _reset_red_history():
    """Wipe banner state between tests so they don't interfere."""
    for k in list(sb._red_since_ts.keys()):
        sb._red_since_ts[k] = None


@pytest.fixture(autouse=True)
def _wipe_state():
    _reset_red_history()
    yield
    _reset_red_history()


async def _call_banner_with_snapshot(snap):
    """Invoke the real `get_system_banner` handler with a patched
    `build_health` and `get_database` so we don't need Mongo."""
    with patch(
        "services.system_health_service.build_health",
        return_value=snap,
    ), patch(
        "database.get_database",
        return_value=object(),  # only needs to be truthy
    ):
        return await sb.get_system_banner()


# ─── 1. Default (pusher mode) — banner STILL fires ───────────────────


@pytest.mark.asyncio
async def test_rpc_blocked_banner_still_fires_under_pusher_mode(monkeypatch):
    monkeypatch.setenv("BOT_ORDER_PATH", "pusher")
    _seed_red_history("pusher_rpc_blocked", 120)

    snap = _make_snapshot(pusher_status="yellow", push_fresh=True, consecutive_failures=82)
    out = await _call_banner_with_snapshot(snap)

    assert out["level"] == "warning"
    assert "Spark→pusher RPC blocked" in (out["message"] or ""), (
        "Under pusher mode (the default), the rpc_blocked banner MUST still "
        "fire — that's the only signal the operator gets that the RPC channel "
        f"is dead. Got: {out!r}"
    )


# ─── 2. Direct mode — banner SUPPRESSED ──────────────────────────────


@pytest.mark.asyncio
async def test_rpc_blocked_banner_suppressed_under_direct_mode(monkeypatch):
    monkeypatch.setenv("BOT_ORDER_PATH", "direct")
    _seed_red_history("pusher_rpc_blocked", 120)

    snap = _make_snapshot(pusher_status="yellow", push_fresh=True, consecutive_failures=82)
    out = await _call_banner_with_snapshot(snap)

    assert out["level"] is None, (
        f"Expected suppressed banner under direct mode, got level={out.get('level')!r}, "
        f"message={out.get('message')!r}"
    )
    assert out["message"] is None
    # Tracker should be cleared so a future false-positive doesn't surface.
    assert sb._red_since_ts.get("pusher_rpc_blocked") is None


# ─── 3. Direct mode — dead-pusher banner STILL fires ─────────────────


@pytest.mark.asyncio
async def test_rpc_dead_banner_still_fires_under_direct_mode(monkeypatch):
    """Even under direct mode, if the PUSH channel ALSO dies, that's a real
    outage we must surface — the bot still depends on the pusher for live
    data fan-out, just not for orders."""
    monkeypatch.setenv("BOT_ORDER_PATH", "direct")
    _seed_red_history("pusher_rpc_dead", 120)

    # Pusher status red AND push stale = real dead-pusher
    snap = _make_snapshot(
        pusher_status="red",
        push_fresh=False,
        consecutive_failures=200,
        push_age_s=60.0,
    )
    out = await _call_banner_with_snapshot(snap)

    assert out["level"] == "critical", (
        f"Even under direct mode, a fully dead pusher (push channel ALSO out) "
        f"must still trigger the critical banner. Got: {out!r}"
    )
    msg = (out.get("message") or "").lower()
    assert "down" in msg or "dead" in msg, (
        f"Expected dead-pusher message under direct mode, got {out['message']!r}"
    )


# ─── 4. Source-marker present (regression breadcrumb) ────────────────


def test_l4c_marker_present_in_source():
    from pathlib import Path
    assert "L4c" in Path(sb.__file__).read_text(), (
        "Expected an `L4c` marker comment in routers/system_banner.py."
    )
