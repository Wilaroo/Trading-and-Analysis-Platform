"""v19.34.28 Patch L4c — Suppress pusher_rpc_blocked banner under direct mode."""
from __future__ import annotations
import time
from unittest.mock import patch
import pytest
from routers import system_banner as sb


def _make_snapshot(*, pusher_status, push_fresh, consecutive_failures, push_age_s=2.0):
    return {
        "subsystems": [
            {"name": "pusher_rpc", "status": pusher_status, "metrics": {
                "consecutive_failures": consecutive_failures,
                "push_fresh": push_fresh, "push_age_s": push_age_s,
            }, "detail": "test"},
            {"name": "mongo", "status": "green", "metrics": {}, "detail": "ok"},
            {"name": "ib_gateway", "status": "green", "metrics": {}, "detail": "ok"},
        ],
        "as_of": "2026-05-18T16:00:00Z",
    }


def _seed_red_history(sub_key, seconds_red):
    sb._red_since_ts[sub_key] = time.time() - seconds_red


def _reset():
    for k in list(sb._red_since_ts.keys()):
        sb._red_since_ts[k] = None


@pytest.fixture(autouse=True)
def _wipe_state():
    _reset(); yield; _reset()


async def _call(snap):
    with patch("services.system_health_service.build_health", return_value=snap), \
         patch("database.get_database", return_value=object()):
        return await sb.get_system_banner()


@pytest.mark.asyncio
async def test_rpc_blocked_banner_still_fires_under_pusher_mode(monkeypatch):
    monkeypatch.setenv("BOT_ORDER_PATH", "pusher")
    _seed_red_history("pusher_rpc_blocked", 120)
    out = await _call(_make_snapshot(pusher_status="yellow", push_fresh=True, consecutive_failures=82))
    assert out["level"] == "warning"
    assert "Spark→pusher RPC blocked" in (out["message"] or "")


@pytest.mark.asyncio
async def test_rpc_blocked_banner_suppressed_under_direct_mode(monkeypatch):
    monkeypatch.setenv("BOT_ORDER_PATH", "direct")
    _seed_red_history("pusher_rpc_blocked", 120)
    out = await _call(_make_snapshot(pusher_status="yellow", push_fresh=True, consecutive_failures=82))
    assert out["level"] is None, f"L4c regression: banner not suppressed: {out!r}"
    assert sb._red_since_ts.get("pusher_rpc_blocked") is None


@pytest.mark.asyncio
async def test_rpc_dead_banner_still_fires_under_direct_mode(monkeypatch):
    """Even under direct mode, a fully dead pusher (push channel ALSO out) must alarm."""
    monkeypatch.setenv("BOT_ORDER_PATH", "direct")
    _seed_red_history("pusher_rpc_dead", 120)
    out = await _call(_make_snapshot(pusher_status="red", push_fresh=False, consecutive_failures=200, push_age_s=60.0))
    assert out["level"] == "critical"
    msg = (out.get("message") or "").lower()
    assert "down" in msg or "dead" in msg


def test_l4c_marker_present_in_source():
    from pathlib import Path
    assert "L4c" in Path(sb.__file__).read_text()
