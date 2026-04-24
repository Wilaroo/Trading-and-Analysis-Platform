"""
Phase 1 — Live Data Architecture contracts.

These tests lock in the structural invariants of the pusher RPC path + the
live_bar_cache + the DGX HTTP client without hitting an actual IB Gateway
or Windows pusher. All tests are deterministic and run in < 200 ms.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

BACKEND = Path("/app/backend")
PUSHER_PATH = Path("/app/documents/scripts/ib_data_pusher.py")


# ----------------------- live_bar_cache contracts -----------------------

def test_classify_market_state_weekend():
    from services.live_bar_cache import classify_market_state
    # Sat 15:00 UTC ≈ Sat 10:00 ET → weekend
    sat = datetime(2026, 1, 3, 15, 0, tzinfo=timezone.utc)  # Saturday
    assert classify_market_state(sat) == "weekend"


def test_classify_market_state_rth_vs_extended():
    from services.live_bar_cache import classify_market_state
    # Weekday 15:00 UTC ≈ 10:00 ET → RTH
    rth = datetime(2026, 1, 7, 15, 0, tzinfo=timezone.utc)  # Wednesday 10:00 ET
    assert classify_market_state(rth) == "rth"
    # Weekday 13:00 UTC ≈ 08:00 ET → extended (pre-market 04:00-09:30)
    ext = datetime(2026, 1, 7, 13, 0, tzinfo=timezone.utc)
    assert classify_market_state(ext) == "extended"
    # Weekday 03:00 UTC ≈ 22:00 ET prior day → overnight
    night = datetime(2026, 1, 7, 3, 0, tzinfo=timezone.utc)
    assert classify_market_state(night) == "overnight"


def test_ttl_for_state_hierarchy():
    """Active view always wins; RTH tightest; weekend loosest."""
    from services.live_bar_cache import ttl_for_state, TTL_ACTIVE_VIEW
    assert ttl_for_state("rth", active_view=False) == 30
    assert ttl_for_state("extended", active_view=False) == 120
    assert ttl_for_state("overnight", active_view=False) == 900
    assert ttl_for_state("weekend", active_view=False) == 3600
    # Active view collapses all states to 30s
    for state in ("rth", "extended", "overnight", "weekend"):
        assert ttl_for_state(state, active_view=True) == TTL_ACTIVE_VIEW == 30


# ----------------------- ib_pusher_rpc (DGX client) --------------------

def test_pusher_rpc_disabled_when_url_missing(monkeypatch):
    from services import ib_pusher_rpc
    # Force-reset singleton so fresh env is read
    ib_pusher_rpc._client_instance = None
    monkeypatch.delenv("IB_PUSHER_RPC_URL", raising=False)
    monkeypatch.setenv("ENABLE_LIVE_BAR_RPC", "true")
    client = ib_pusher_rpc.get_pusher_rpc_client()
    assert client.is_configured() is False
    # Even if callers invoke latest_bars, we must return None (not raise)
    assert client.latest_bars("SPY", "5 mins") is None
    assert client.quote_snapshot("SPY") is None


def test_pusher_rpc_feature_flag_off(monkeypatch):
    from services import ib_pusher_rpc
    ib_pusher_rpc._client_instance = None
    monkeypatch.setenv("IB_PUSHER_RPC_URL", "http://192.168.50.1:8765")
    monkeypatch.setenv("ENABLE_LIVE_BAR_RPC", "false")
    client = ib_pusher_rpc.get_pusher_rpc_client()
    assert client.is_configured() is False


def test_pusher_rpc_client_returns_none_on_network_error(monkeypatch):
    """Client must swallow all network errors and return None — never raise."""
    from services import ib_pusher_rpc
    ib_pusher_rpc._client_instance = None
    # Non-routable address → connect refused / timeout quickly
    monkeypatch.setenv("IB_PUSHER_RPC_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ENABLE_LIVE_BAR_RPC", "true")
    client = ib_pusher_rpc.get_pusher_rpc_client()
    assert client.is_configured() is True
    result = client.latest_bars("SPY", "5 mins")
    assert result is None
    # Status should reflect the failure
    assert client.status()["consecutive_failures"] >= 1


# ----------------------- HybridDataService integration ------------------

@pytest.mark.asyncio
async def test_fetch_latest_session_bars_falls_back_when_disabled(monkeypatch):
    """When pusher RPC is disabled, fetch_latest_session_bars returns
    success=False with source='none' (never raises, never crashes the chart)."""
    from services import ib_pusher_rpc
    from services.hybrid_data_service import get_hybrid_data_service

    ib_pusher_rpc._client_instance = None
    monkeypatch.delenv("IB_PUSHER_RPC_URL", raising=False)

    svc = get_hybrid_data_service()
    res = await svc.fetch_latest_session_bars("SPY", "5 mins")
    assert res["success"] is False
    assert res["source"] == "none"
    assert res["bars"] == []
    assert "error" in res


# ----------------------- Windows pusher RPC source contracts ------------

def _pusher_src() -> str:
    return PUSHER_PATH.read_text(encoding="utf-8")


def test_pusher_exports_start_rpc_server():
    """start_rpc_server must exist + be called from run() and run_auto_mode()."""
    src = _pusher_src()
    assert "def start_rpc_server(" in src, (
        "Phase 1: start_rpc_server helper must be defined in ib_data_pusher.py"
    )
    # Must be invoked after connect() succeeds — we look for the call
    # appearing at least twice (run + run_auto_mode).
    assert src.count("start_rpc_server(self, rpc_host, rpc_port)") >= 2, (
        "start_rpc_server must be called from BOTH run() and run_auto_mode()"
    )


def test_pusher_rpc_endpoints_declared():
    """The three RPC endpoints must be registered on the FastAPI app."""
    src = _pusher_src()
    for route in ('"/rpc/health"', '"/rpc/latest-bars"', '"/rpc/quote-snapshot"'):
        assert route in src, f"Phase 1 RPC endpoint {route} missing from pusher"


def test_pusher_rpc_uses_threadsafe_coroutine_dispatch():
    """Critical safety: RPC handler must NOT call ib_insync from a FastAPI
    thread directly. It must dispatch to the IB event loop via
    asyncio.run_coroutine_threadsafe — otherwise ib_insync races and crashes."""
    src = _pusher_src()
    assert "asyncio.run_coroutine_threadsafe" in src, (
        "RPC handler must use run_coroutine_threadsafe to dispatch IB calls"
    )
    assert "reqHistoricalDataAsync" in src, (
        "RPC handler must use reqHistoricalDataAsync (async) — not the sync version"
    )


def test_pusher_rpc_port_is_env_configurable():
    """Port must be read from IB_PUSHER_RPC_PORT env var (default 8765) so
    operator can move it without editing code on Windows."""
    src = _pusher_src()
    assert "IB_PUSHER_RPC_PORT" in src, (
        "Pusher must read IB_PUSHER_RPC_PORT env var for port selection"
    )
    assert '"8765"' in src or "8765" in src, (
        "Pusher must default RPC port to 8765 when env var not set"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
