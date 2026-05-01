"""
v19.30.11 (2026-05-01) — Pusher RPC throttle / circuit breaker / dedup
+ skip-restart-if-healthy guards + system banner endpoint.

CONTEXT
-------
Operator reported 2026-05-01 afternoon: "running well yesterday but won't
start up today". Diagnostic data proved:

  1. Spark backend itself was healthy (PID 4125861, 5min uptime, /api/health
     returning 200, event loop lag 0ms).
  2. Windows IB Pusher was dead (`pusher_rpc: red, 42 consecutive failures`
     in /api/system/health). Probable cause: overload — multiple Spark
     services concurrently hitting pusher's /rpc/latest-bars triggered an
     IB Gateway pacing violation (≥6 concurrent reqHistoricalData → IB
     closes the socket).
  3. Operator misread "dashboard empty" as "backend broken" and ran
     `./start_backend.sh`, which UNCONDITIONALLY killed port 8001 — wiping
     the perfectly healthy backend AND adding 60-90s of cold-boot wait on
     top of the existing pusher outage.

THIS COMMIT
-----------
Three independent fixes that together prevent recurrence:

  Fix 1: bounded concurrency + circuit breaker + dedup on Spark→pusher
         (so Spark can't overload pusher; if pusher dies, we stop spamming
         it and let it recover instead of prolonging the outage).

  Fix 2: skip-restart-if-healthy guard on both `start_backend.sh` and
         `scripts/spark_start.sh` (so the operator can't accidentally
         kill a healthy backend; --force flag if they really want to).

  Fix 3: GET /api/system/banner — operator-facing alert endpoint that
         drives a giant red SystemBanner.jsx strip on the V5 HUD.
         Tells operator EXACTLY what's broken AND what to do, AND what
         NOT to do (don't restart Spark when pusher is the problem).

These tests pin all three at source/behaviour level.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import threading
import time
from collections import deque
from unittest.mock import MagicMock, patch

import pytest


# ─── Fix 1: pusher RPC circuit breaker + semaphore + dedup ───────────────────


def _fresh_client():
    """Spin a fresh _PusherRPCClient with an in-process URL set."""
    os.environ["IB_PUSHER_RPC_URL"] = "http://localhost:9999"
    os.environ.pop("IB_PUSHER_RPC_MAX_CONCURRENT", None)
    os.environ.pop("IB_PUSHER_RPC_CIRCUIT_THRESHOLD", None)
    os.environ.pop("IB_PUSHER_RPC_CIRCUIT_OPEN_S", None)

    # Force module reload so env-var-driven module-level constants
    # pick up the test values.
    import importlib
    import services.ib_pusher_rpc as mod
    importlib.reload(mod)
    return mod._PusherRPCClient(), mod


def test_circuit_breaker_opens_after_threshold_failures():
    """5 failures within the rolling 10s window must flip the circuit OPEN.

    Once OPEN, subsequent calls short-circuit (return None immediately
    without hitting the network) for `_CIRCUIT_OPEN_DURATION_S` seconds.
    """
    client, mod = _fresh_client()

    # Simulate 5 connection errors back-to-back.
    fake_session = MagicMock()
    fake_session.request.side_effect = mod.requests.ConnectionError("conn refused")
    client._session = fake_session

    for _ in range(5):
        result = client._request("GET", "/rpc/health", timeout=1.0)
        assert result is None  # fail-open

    # Circuit should now be OPEN.
    assert client._circuit_state == mod._CIRCUIT_OPEN

    # Next call must NOT hit fake_session — it short-circuits.
    fake_session.request.reset_mock()
    result = client._request("GET", "/rpc/health", timeout=1.0)
    assert result is None
    assert fake_session.request.call_count == 0
    assert client._circuit_short_circuit_total >= 1


def test_circuit_breaker_half_open_recovery():
    """After `_CIRCUIT_OPEN_DURATION_S` expires, the next request goes
    through (HALF_OPEN). On success the circuit closes; on failure the
    circuit re-opens for another full interval.
    """
    client, mod = _fresh_client()

    # Force the circuit OPEN by direct manipulation (faster than 5 failures).
    client._circuit_state = mod._CIRCUIT_OPEN
    client._circuit_opened_at = time.time() - (mod._CIRCUIT_OPEN_DURATION_S + 1)

    fake_session = MagicMock()
    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.json.return_value = {"success": True}
    fake_session.request.return_value = ok_resp
    client._session = fake_session

    # First call after expiry → HALF_OPEN test → succeeds → CLOSED.
    result = client._request("GET", "/rpc/health", timeout=1.0)
    assert result == {"success": True}
    assert client._circuit_state == mod._CIRCUIT_CLOSED
    assert len(client._failure_window) == 0


def test_circuit_breaker_half_open_failure_reopens():
    """If the half-open test request fails, circuit re-opens."""
    client, mod = _fresh_client()

    client._circuit_state = mod._CIRCUIT_OPEN
    client._circuit_opened_at = time.time() - (mod._CIRCUIT_OPEN_DURATION_S + 1)

    fake_session = MagicMock()
    fake_session.request.side_effect = mod.requests.ConnectionError("still down")
    client._session = fake_session

    result = client._request("GET", "/rpc/health", timeout=1.0)
    assert result is None
    assert client._circuit_state == mod._CIRCUIT_OPEN
    # opened_at must be REFRESHED (not still ≥30s ago)
    assert (time.time() - client._circuit_opened_at) < 1.0


def test_semaphore_caps_concurrent_in_flight():
    """The bounded-concurrency semaphore must allow ≤N parallel calls.

    Source-level check: the size is configurable via env var and the
    semaphore replaces the previous threading.Lock (which capped at 1).
    """
    _, mod = _fresh_client()

    # The previous code used `self._lock = threading.Lock()`. The new
    # code uses `self._request_semaphore = threading.Semaphore(N)`.
    src = inspect.getsource(mod._PusherRPCClient.__init__)
    assert "Semaphore(" in src, (
        "Pusher RPC client must use a bounded Semaphore for concurrent "
        "request control (replaces the prior threading.Lock)."
    )
    assert "self._request_semaphore" in src

    # And the request handler must acquire/release it.
    request_src = inspect.getsource(mod._PusherRPCClient._request)
    assert "self._request_semaphore.acquire(" in request_src
    assert "self._request_semaphore.release()" in request_src


def test_semaphore_timeout_increments_counter():
    """If the semaphore can't be acquired within the timeout, the call
    fails fast (returns None) and bumps the timeout counter.
    """
    client, _ = _fresh_client()

    # Saturate the semaphore by acquiring all slots.
    sem = client._request_semaphore
    held = []
    while sem.acquire(blocking=False):
        held.append(True)

    try:
        # With env-default IB_PUSHER_RPC_ACQUIRE_TIMEOUT_S=2.0 a real
        # call would block 2s. Patch it down to instant for the test.
        with patch("services.ib_pusher_rpc._SEMAPHORE_ACQUIRE_TIMEOUT_S", 0.05):
            start = time.time()
            result = client._request("GET", "/rpc/health", timeout=1.0)
            elapsed = time.time() - start
        assert result is None
        assert elapsed < 0.5  # fast-fail, not a 6s round-trip
        assert client._semaphore_timeout_total >= 1
    finally:
        # Release everything we held so the test fixture is clean.
        for _ in held:
            sem.release()


def test_dedup_coalesces_concurrent_identical_requests():
    """Multiple threads asking for the same idempotent payload at the
    same time must coalesce into a SINGLE HTTP request.
    """
    client, _ = _fresh_client()

    call_count = {"n": 0}
    barrier = threading.Event()

    def slow_response(*args, **kwargs):
        call_count["n"] += 1
        barrier.wait(timeout=1.0)
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"success": True, "bars": [{"close": 100.0}]}
        return resp

    fake_session = MagicMock()
    fake_session.request.side_effect = slow_response
    client._session = fake_session

    results = []
    threads = []
    body = {"symbol": "SPY", "bar_size": "5 mins"}
    for _ in range(5):
        t = threading.Thread(
            target=lambda: results.append(
                client._request_with_dedup(
                    "POST", "/rpc/latest-bars", json_body=body, timeout=2.0
                )
            )
        )
        threads.append(t)
        t.start()

    # Give threads time to pile onto the dedup leader before unblocking it.
    time.sleep(0.05)
    barrier.set()
    for t in threads:
        t.join(timeout=3.0)

    # Exactly ONE actual HTTP request — the other 4 callers got the
    # leader's result via the dedup event.
    assert call_count["n"] == 1, (
        f"Dedup should have coalesced 5 concurrent identical calls into "
        f"1 HTTP request; observed {call_count['n']}."
    )
    # All 5 callers must have received the same response.
    assert len(results) == 5
    assert all(r == {"success": True, "bars": [{"close": 100.0}]} for r in results)
    assert client._dedup_coalesced_total == 4  # 1 leader, 4 followers


def test_dedup_does_not_coalesce_different_requests():
    """Different symbols / different bodies must NOT coalesce — they
    represent independent IB queries.
    """
    client, _ = _fresh_client()

    fake_session = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"success": True}
    fake_session.request.return_value = resp
    client._session = fake_session

    client._request_with_dedup("POST", "/rpc/latest-bars",
                                json_body={"symbol": "SPY"}, timeout=1.0)
    client._request_with_dedup("POST", "/rpc/latest-bars",
                                json_body={"symbol": "QQQ"}, timeout=1.0)

    assert fake_session.request.call_count == 2


def test_latency_stats_surfaces_circuit_state():
    """The /api/ib/pusher-health heartbeat tile reads `latency_stats()`.
    All the new throttle/circuit/dedup metrics must be present.
    """
    client, mod = _fresh_client()
    stats = client.latency_stats()

    required_keys = {
        "rpc_max_concurrent",
        "rpc_circuit_state",
        "rpc_circuit_open_remaining_s",
        "rpc_circuit_recent_failures",
        "rpc_circuit_short_circuit_total",
        "rpc_semaphore_timeout_total",
        "rpc_dedup_coalesced_total",
    }
    missing = required_keys - set(stats.keys())
    assert not missing, f"latency_stats() missing throttle metrics: {missing}"

    # Initial state: closed circuit, no failures.
    assert stats["rpc_circuit_state"] == mod._CIRCUIT_CLOSED
    assert stats["rpc_circuit_recent_failures"] == 0
    assert stats["rpc_circuit_open_remaining_s"] is None


def test_pusher_rpc_fail_open_contract():
    """All failure paths must return None (NOT raise) — chart panels and
    scanners depend on this fail-open contract to fall back to Mongo
    cache without crashing the page.
    """
    client, _ = _fresh_client()

    fake_session = MagicMock()
    client._session = fake_session

    # Every failure mode → None
    for exc in (
        Exception("generic"),
        ValueError("bad json"),
    ):
        fake_session.request.side_effect = exc
        result = client._request("GET", "/rpc/health", timeout=0.5)
        assert result is None


# ─── Fix 2: skip-restart-if-healthy guard pins ───────────────────────────────


def test_start_backend_sh_has_skip_if_healthy_guard():
    """The `start_backend.sh` script MUST short-circuit when /api/health
    returns 200, so the operator can't accidentally kill a healthy backend.
    """
    with open("/app/start_backend.sh") as f:
        src = f.read()
    # Must check /api/health BEFORE the fuser kill step.
    assert "curl -sf -m 5 http://127.0.0.1:8001/api/health" in src
    assert "Backend already healthy" in src
    # Must support a --force override.
    assert "--force" in src
    # Healthy-check must come BEFORE the fuser kill COMMAND (not the
    # comment that mentions it).
    healthy_idx = src.find("Backend already healthy")
    # The actual command is `fuser -k 8001/tcp 2>/dev/null`; comments
    # also reference `fuser -k 8001/tcp` so we anchor on the redirect.
    fuser_idx = src.find("fuser -k 8001/tcp 2>/dev/null")
    assert healthy_idx > 0 and fuser_idx > 0
    assert healthy_idx < fuser_idx, (
        "Skip-if-healthy guard must come BEFORE the fuser kill — "
        "otherwise we kill the healthy backend before checking."
    )


def test_spark_start_sh_has_skip_if_healthy_guard():
    """Same guard on the orchestrator-called script."""
    with open("/app/scripts/spark_start.sh") as f:
        src = f.read()
    assert "Backend already healthy" in src
    assert "--force" in src
    # The Spark version should print the alternative for forced restart.
    assert "scripts/spark_stop.sh" in src


def test_start_backend_sh_cold_boot_wait_is_120s():
    """Cold-boot wait bumped 60s → 120s. The deferred-init storm
    legitimately takes 60-90s; the watchdog catches genuine wedges.
    """
    with open("/app/start_backend.sh") as f:
        src = f.read()
    # The startup wait loop bound — was {1..60}, now {1..120}.
    assert "for i in {1..120}" in src
    assert "up to 120s" in src


def test_spark_start_sh_cold_boot_wait_is_120s():
    """Same bump in the orchestrator path."""
    with open("/app/scripts/spark_start.sh") as f:
        src = f.read()
    assert "for i in $(seq 1 120)" in src
    assert "120s" in src


# ─── Fix 3: /api/system/banner endpoint ──────────────────────────────────────


def test_banner_endpoint_exists():
    """The endpoint must be importable and registered."""
    from routers.system_banner import router, get_system_banner
    assert router.prefix == "/api/system"
    assert callable(get_system_banner)


def test_banner_returns_critical_when_pusher_fully_dead_30s():
    """Pusher fully dead (push stale + RPC fail) for ≥30s → critical
    banner with explicit operator action telling them NOT to restart
    Spark backend.

    v19.30.12 (2026-05-01) — banner now distinguishes fully-dead from
    rpc-blocked. Push channel must ALSO be stale to fire critical.
    """
    from routers import system_banner as bm

    fake_health = {
        "overall": "red",
        "subsystems": [
            {
                "name": "pusher_rpc",
                "status": "red",
                "detail": "fully_dead · 42 consecutive RPC failures · "
                          "no push data ever received",
                "metrics": {
                    "consecutive_failures": 42,
                    "push_age_s": None,
                    "push_fresh": False,
                },
            },
            {"name": "mongo", "status": "green"},
        ],
        "as_of": "2026-05-01T19:00:00Z",
    }

    bm._red_since_ts.clear()
    bm._red_since_ts["pusher_rpc_dead"] = bm._now_ts() - 35

    with patch("services.system_health_service.build_health", return_value=fake_health):
        result = asyncio.run(bm.get_system_banner())

    assert result["level"] == "critical"
    assert result["subsystem"] == "pusher_rpc"
    assert "DOWN" in result["message"] or "Down" in result["message"]
    assert "42" in result["detail"]
    # Action MUST tell the operator NOT to restart Spark.
    assert "Do NOT" in result["action"]


def test_banner_returns_warning_when_pusher_rpc_blocked_only():
    """Push channel fresh + RPC failing → YELLOW banner with firewall
    diagnosis (asymmetric network, e.g. Windows firewall blocking :8765).

    This is the EXACT case the operator hit on 2026-05-01: pusher was
    pushing fine to Spark (so live quotes/positions flowed) but Spark
    couldn't reach the pusher's RPC server inbound.
    """
    from routers import system_banner as bm

    fake_health = {
        "overall": "yellow",
        "subsystems": [
            {
                "name": "pusher_rpc",
                "status": "yellow",
                "detail": "rpc_blocked · 19 consecutive RPC failures · "
                          "push fresh (8.2s ago) — live data IS flowing",
                "metrics": {
                    "consecutive_failures": 19,
                    "push_age_s": 8.2,
                    "push_fresh": True,
                },
            },
            {"name": "mongo", "status": "green"},
        ],
        "as_of": "2026-05-01T19:00:00Z",
    }

    bm._red_since_ts.clear()
    bm._red_since_ts["pusher_rpc_blocked"] = bm._now_ts() - 35

    with patch("services.system_health_service.build_health", return_value=fake_health):
        result = asyncio.run(bm.get_system_banner())

    assert result["level"] == "warning"
    assert result["subsystem"] == "pusher_rpc"
    detail_lower = result["detail"].lower()
    assert (
        "live quotes" in detail_lower
        or "live data" in detail_lower
        or "flowing" in detail_lower
        or "healthy" in detail_lower
    ), f"banner detail must reassure operator that push is healthy: {result['detail']}"
    # Action must mention the firewall fix command.
    assert "8765" in result["action"]
    assert "netsh advfirewall" in result["action"] or "firewall" in result["action"].lower()


def test_banner_does_not_double_fire_when_pusher_yellow_and_overall_yellow():
    """If pusher_rpc is yellow AND that's the only degradation, the
    dedicated rpc_blocked banner fires. Don't ALSO fire the generic
    "Some subsystems are degraded" banner.
    """
    from routers import system_banner as bm

    fake_health = {
        "overall": "yellow",
        "subsystems": [
            {
                "name": "pusher_rpc",
                "status": "yellow",
                "detail": "rpc_blocked · 5 consecutive RPC failures",
                "metrics": {
                    "consecutive_failures": 5,
                    "push_age_s": 8.0,
                    "push_fresh": True,
                },
            },
            {"name": "mongo", "status": "green"},
        ],
        "as_of": "2026-05-01T19:00:00Z",
    }

    # Less than 30s — dedicated banner won't fire YET.
    bm._red_since_ts.clear()
    bm._red_since_ts["pusher_rpc_blocked"] = bm._now_ts() - 5

    with patch("services.system_health_service.build_health", return_value=fake_health):
        result = asyncio.run(bm.get_system_banner())

    # During the <30s grace, NO banner — not even the generic one.
    # Otherwise we'd flash "Some subsystems are degraded" then switch
    # to the specific message at 30s, which is jarring.
    assert result["level"] is None


def test_banner_returns_null_when_all_green():
    """No banner when everything is healthy."""
    from routers import system_banner as bm

    fake_health = {
        "overall": "green",
        "subsystems": [
            {"name": "pusher_rpc", "status": "green"},
            {"name": "mongo", "status": "green", "detail": "ping 0.87 ms"},
            {"name": "ib_gateway", "status": "green"},
        ],
        "as_of": "2026-05-01T19:00:00Z",
    }

    # Reset trackers
    bm._red_since_ts.clear()

    with patch("services.system_health_service.build_health", return_value=fake_health):
        result = asyncio.run(bm.get_system_banner())

    assert result["level"] is None
    assert result["message"] is None
    assert result["subsystem"] is None


def test_banner_does_not_fire_for_pusher_red_under_30s():
    """Pusher fully_dead <30s → no banner yet (avoid flashing on transient blips)."""
    from routers import system_banner as bm

    fake_health = {
        "overall": "red",
        "subsystems": [
            {"name": "pusher_rpc", "status": "red",
             "detail": "fully_dead · 3 consecutive RPC failures",
             "metrics": {"consecutive_failures": 3, "push_age_s": None,
                         "push_fresh": False}},
            {"name": "mongo", "status": "green"},
        ],
        "as_of": "2026-05-01T19:00:00Z",
    }

    bm._red_since_ts.clear()
    bm._red_since_ts["pusher_rpc_dead"] = bm._now_ts() - 3

    with patch("services.system_health_service.build_health", return_value=fake_health):
        result = asyncio.run(bm.get_system_banner())

    assert result["level"] is None


def test_banner_returns_critical_when_mongo_red():
    """Mongo down for ≥10s is also critical (everything depends on it)."""
    from routers import system_banner as bm

    fake_health = {
        "overall": "red",
        "subsystems": [
            {"name": "pusher_rpc", "status": "green"},
            {"name": "mongo", "status": "red", "detail": "ping failed: refused"},
        ],
        "as_of": "2026-05-01T19:00:00Z",
    }
    bm._red_since_ts.clear()
    bm._red_since_ts["mongo"] = bm._now_ts() - 15

    with patch("services.system_health_service.build_health", return_value=fake_health):
        result = asyncio.run(bm.get_system_banner())

    assert result["level"] == "critical"
    assert result["subsystem"] == "mongo"
    assert "MongoDB" in result["message"]


def test_banner_handles_health_snapshot_failure_gracefully():
    """If the health snapshot itself fails, return null banner — never
    raise. The chart UI would dim a banner if the call returned 5xx.
    """
    from routers import system_banner as bm
    bm._red_since_ts.clear()

    with patch("services.system_health_service.build_health",
               side_effect=Exception("db unreachable")):
        result = asyncio.run(bm.get_system_banner())

    assert result["level"] is None
