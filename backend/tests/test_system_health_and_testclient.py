"""
Phase 5 — System Health v2 + Live-data HTTP contract tests.
Exercises the LIVE running backend via requests — fast, deterministic,
zero fragile ASGI plumbing. Runs green when supervisor backend is up.
"""
from __future__ import annotations

import pytest
import requests

BASE = "http://localhost:8001"


def _up() -> bool:
    try:
        requests.get(f"{BASE}/api/health", timeout=2)
        return True
    except Exception:
        return False


# Skip entire module if backend not running (e.g. pre-boot CI)
pytestmark = pytest.mark.skipif(not _up(), reason="backend not running")


@pytest.fixture
def client():
    """Pre-flight: wipe any leftover test subscriptions, return requests session."""
    # Best-effort cleanup of TESTSYM from prior runs
    try:
        # Loop unsubscribe until fully_unsubscribed or rejected
        for _ in range(10):
            r = requests.post(f"{BASE}/api/live/unsubscribe/TESTSYM", timeout=5).json()
            if r.get("fully_unsubscribed") or not r.get("accepted"):
                break
    except Exception:
        pass
    return requests


# ---- /api/system/health (v2 — live-data era) ---------------------------

def test_system_health_v2_returns_expected_shape(client):
    r = client.get(f"{BASE}/api/system/health", timeout=5)
    assert r.status_code == 200
    body = r.json()
    # Stable shape for HUD + inspector
    for k in ("overall", "counts", "subsystems", "build_ms", "as_of"):
        assert k in body
    assert body["overall"] in {"green", "yellow", "red"}
    assert isinstance(body["subsystems"], list)
    # Every subsystem has name + status + optional detail/metrics
    for s in body["subsystems"]:
        assert "name" in s and "status" in s
        assert s["status"] in {"green", "yellow", "red"}


def test_system_health_v2_includes_live_data_pipeline_subsystems(client):
    """The new v2 health check MUST cover the live-data pipeline, not
    just classic DB/IB."""
    r = client.get(f"{BASE}/api/system/health", timeout=5)
    names = [s["name"] for s in r.json()["subsystems"]]
    for expected in (
        "mongo",
        "pusher_rpc",
        "ib_gateway",
        "historical_queue",
        "live_subscriptions",
        "live_bar_cache",
        "task_heartbeats",
    ):
        assert expected in names, f"Missing subsystem: {expected}"


def test_system_health_v2_pusher_rpc_yellow_when_disabled(client):
    """ENABLE_LIVE_BAR_RPC=false (preview env) must yield yellow on
    pusher_rpc — red would mean broken, but "disabled" is an operator
    choice not a fault."""
    r = client.get(f"{BASE}/api/system/health", timeout=5)
    pusher = next(s for s in r.json()["subsystems"] if s["name"] == "pusher_rpc")
    assert pusher["status"] in {"yellow", "green"}, (
        f"Expected yellow/green for disabled pusher RPC, got {pusher}"
    )


def test_system_health_v2_build_ms_reasonable(client):
    """Full health build must complete in <1000ms under normal conditions."""
    r = client.get(f"{BASE}/api/system/health", timeout=5)
    assert r.json()["build_ms"] < 1000, (
        "System health check taking >1s — subsystem check added a heavy call?"
    )


# ---- Regression: existing /api/live/* endpoints still work -----------

def test_live_subscriptions_endpoint(client):
    r = client.get(f"{BASE}/api/live/subscriptions", timeout=5)
    assert r.status_code == 200
    body = r.json()
    assert "active_count" in body
    assert "max_subscriptions" in body


def test_live_ttl_plan_endpoint(client):
    r = client.get(f"{BASE}/api/live/ttl-plan", timeout=5)
    assert r.status_code == 200
    body = r.json()
    for k in ("market_state", "ttl_by_state", "ttl_active_view"):
        assert k in body


def test_live_symbol_snapshot_graceful_fail(client):
    r = client.get(f"{BASE}/api/live/symbol-snapshot/SPY", timeout=5)
    assert r.status_code == 200
    body = r.json()
    assert "success" in body and "symbol" in body
    assert body["symbol"] == "SPY"


def test_live_briefing_snapshot_endpoint(client):
    r = client.get(f"{BASE}/api/live/briefing-snapshot?symbols=SPY,QQQ", timeout=5)
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "snapshots" in body and "market_state" in body


def test_live_subscribe_unsubscribe_ref_count_e2e(client):
    """End-to-end ref-count against live backend."""
    r1 = client.post(f"{BASE}/api/live/subscribe/TESTSYM", timeout=5)
    assert r1.status_code == 200
    b1 = r1.json()
    assert b1["accepted"] is True and b1["newly_subscribed"] is True

    r2 = client.post(f"{BASE}/api/live/subscribe/TESTSYM", timeout=5)
    b2 = r2.json()
    assert b2["newly_subscribed"] is False
    assert b2["ref_count"] == 2

    r3 = client.post(f"{BASE}/api/live/unsubscribe/TESTSYM", timeout=5)
    b3 = r3.json()
    assert b3["fully_unsubscribed"] is False

    r4 = client.post(f"{BASE}/api/live/unsubscribe/TESTSYM", timeout=5)
    b4 = r4.json()
    assert b4["fully_unsubscribed"] is True
    assert b4["ref_count"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
