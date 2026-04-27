"""
Pusher Heartbeat Endpoint Tests
================================
Covers Feb-2026 additions to /api/ib/pusher-health:
  • `heartbeat.pushes_per_min` — rolling 60s push rate
  • `heartbeat.push_count_total` — session counter
  • `heartbeat.push_rate_health` — healthy / degraded / stalled / no_pushes
  • `heartbeat.rpc_latency_ms_avg` / `_p95` / `_last`
  • `heartbeat.rpc_call_count_total`

The intent: give the V5 PusherHeartbeatTile positive proof-of-life so a
degrading pusher shows up before the dead-banner threshold trips.
"""
from __future__ import annotations

import time
from collections import deque

import pytest


def test_pusher_rpc_client_latency_stats_empty_window():
    """Fresh client returns None placeholders (no calls yet)."""
    from services import ib_pusher_rpc

    # Fresh instance to avoid pollution from the singleton.
    client = ib_pusher_rpc._PusherRPCClient()
    stats = client.latency_stats()
    assert stats["rpc_latency_ms_avg"] is None
    assert stats["rpc_latency_ms_p95"] is None
    assert stats["rpc_latency_ms_last"] is None
    assert stats["rpc_sample_size"] == 0
    assert stats["rpc_call_count_total"] == 0
    assert stats["rpc_success_count_total"] == 0


def test_pusher_rpc_client_latency_stats_after_recorded_calls():
    """Latency window is honored: avg / p95 / last computed correctly."""
    from services import ib_pusher_rpc

    client = ib_pusher_rpc._PusherRPCClient()
    # Inject 10 sample latencies in ms
    samples = [10, 12, 15, 18, 20, 22, 30, 40, 50, 200]
    for s in samples:
        client._latency_ms_window.append(float(s))
    client._success_count_total = 10
    client._call_count_total = 10

    stats = client.latency_stats()
    assert stats["rpc_sample_size"] == 10
    # avg = mean(samples) = 41.7
    assert stats["rpc_latency_ms_avg"] == pytest.approx(41.7, abs=0.1)
    # last = last appended = 200
    assert stats["rpc_latency_ms_last"] == pytest.approx(200.0, abs=0.1)
    # p95 on 10 samples → index = max(0, int(10*0.95)-1) = 8 → sorted[8] = 50
    assert stats["rpc_latency_ms_p95"] == pytest.approx(50.0, abs=0.1)


def test_pusher_rpc_client_window_caps_at_50():
    """Older latencies should fall off as the deque hits maxlen."""
    from services import ib_pusher_rpc

    client = ib_pusher_rpc._PusherRPCClient()
    for i in range(200):
        client._latency_ms_window.append(float(i))
    stats = client.latency_stats()
    assert stats["rpc_sample_size"] == 50, "deque must cap at 50"
    # The last 50 are 150..199, so avg = mean(150..199) = 174.5
    assert stats["rpc_latency_ms_avg"] == pytest.approx(174.5, abs=0.1)


def test_pusher_health_response_includes_heartbeat_block():
    """Smoke: GET /api/ib/pusher-health returns a `heartbeat` dict with the
    new fields, even before any pushes have happened (graceful zero values)."""
    import asyncio
    from routers import ib as ib_router

    # Reset the in-proc state for this test
    ib_router._pushed_ib_data["last_update"] = None
    ib_router._push_timestamps.clear()
    ib_router._push_count_total = 0

    payload = asyncio.run(ib_router.get_pusher_health())
    assert payload["success"] is True
    assert "heartbeat" in payload
    hb = payload["heartbeat"]
    assert hb["pushes_per_min"] == 0
    assert hb["push_count_total"] == 0
    assert hb["push_rate_health"] == "no_pushes"
    # RPC latency keys present even if no calls yet
    for key in (
        "rpc_latency_ms_avg",
        "rpc_latency_ms_p95",
        "rpc_latency_ms_last",
        "rpc_call_count_total",
        "rpc_sample_size",
    ):
        assert key in hb, f"heartbeat must surface {key}"


def test_pushes_per_min_count_60s_window():
    """Pushes within last 60s are counted; older ones are excluded."""
    import asyncio
    from routers import ib as ib_router

    ib_router._pushed_ib_data["last_update"] = None
    ib_router._push_timestamps.clear()
    ib_router._push_count_total = 0

    now = time.time()
    # 5 pushes in the last 60s, 3 older than 60s (must be excluded)
    for offset in (5, 10, 20, 40, 55):
        ib_router._push_timestamps.append(now - offset)
    for offset in (61, 90, 200):
        ib_router._push_timestamps.append(now - offset)
    ib_router._push_count_total = 8

    payload = asyncio.run(ib_router.get_pusher_health())
    hb = payload["heartbeat"]
    assert hb["pushes_per_min"] == 5
    assert hb["push_count_total"] == 8


def test_push_rate_health_thresholds():
    """healthy ≥ 4, degraded ≥ 2, stalled > 0, else no_pushes.
    Calibrated against the pusher's default 10s push interval
    (= 6 pushes/min when fully healthy)."""
    import asyncio
    from routers import ib as ib_router

    ib_router._pushed_ib_data["last_update"] = None

    cases = [
        (8, "healthy"),    # well above 4/min
        (3, "degraded"),   # 2..3/min
        (1, "stalled"),    # one push in window
        (0, "no_pushes"),
    ]
    for n_pushes, expected in cases:
        ib_router._push_timestamps.clear()
        now = time.time()
        for i in range(n_pushes):
            ib_router._push_timestamps.append(now - (i + 1))  # all within 60s
        payload = asyncio.run(ib_router.get_pusher_health())
        assert payload["heartbeat"]["push_rate_health"] == expected, (
            f"with {n_pushes} pushes/min expected {expected}, "
            f"got {payload['heartbeat']['push_rate_health']}"
        )


def test_receive_pushed_ib_data_appends_timestamp_and_increments_counter():
    """The `/push-data` POST handler must update the heartbeat state."""
    from routers import ib as ib_router
    from routers.ib import IBPushDataRequest

    # Reset
    ib_router._push_timestamps.clear()
    ib_router._push_count_total = 0

    # Fire 3 push events
    req = IBPushDataRequest(
        timestamp="2026-02-19T15:30:00Z",
        quotes={"AAPL": {"price": 100, "volume": 1000, "timestamp": "2026-02-19T15:30:00Z"}},
        positions=[],
        account={},
    )
    for _ in range(3):
        ib_router.receive_pushed_ib_data(req)

    assert ib_router._push_count_total == 3
    assert len(ib_router._push_timestamps) == 3
