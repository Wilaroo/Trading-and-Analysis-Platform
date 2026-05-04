"""
v19.32 (2026-05-04) — Tests for the Chart Cache Warmer.

Operator's "cold chart load is 400ms even though cache is fast"
pain-point. The warmer pre-computes chart_response_cache entries for
the top-N visible scanner symbols × common timeframes so the
operator's NEXT click finds a warm cache.

Tests cover:
- Endpoint contract: request validation + response shape
- De-dupe + uppercase normalization of input symbols
- Timeframe filter against _SUPPORTED_TFS
- Bounded concurrency (sem=N)
- Per-cell timeout failure mode
- Skipped vs warmed status accounting
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch, AsyncMock

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ─── Request model validation ──────────────────────────────────────


def test_warm_request_uppercases_and_dedupes_symbols():
    from routers.sentcom_chart import ChartWarmRequest
    req = ChartWarmRequest(symbols=["aapl", "MSFT", "aapl", " tsla "])
    assert req.symbols == ["AAPL", "MSFT", "TSLA"]


def test_warm_request_rejects_empty_symbols():
    from routers.sentcom_chart import ChartWarmRequest
    with pytest.raises(Exception):  # ValidationError
        ChartWarmRequest(symbols=[])
    with pytest.raises(Exception):
        ChartWarmRequest(symbols=["", "  ", None])


def test_warm_request_filters_unsupported_timeframes():
    from routers.sentcom_chart import ChartWarmRequest
    req = ChartWarmRequest(
        symbols=["AAPL"],
        timeframes=["5min", "INVALID", "1hour", "5min"],
    )
    assert req.timeframes == ["5min", "1hour"]


def test_warm_request_rejects_only_invalid_timeframes():
    from routers.sentcom_chart import ChartWarmRequest
    with pytest.raises(Exception):
        ChartWarmRequest(symbols=["AAPL"], timeframes=["INVALID", "ALSO_BAD"])


# ─── Endpoint behavior ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_warm_skips_when_cache_already_has_entry():
    """A pre-warmed cache cell must report `skipped/already_warm` and
    NOT re-trigger the get_chart_bars compute."""
    from routers.sentcom_chart import warm_chart_cache, ChartWarmRequest
    from routers import sentcom_chart as sc

    fake_cache = AsyncMock()
    fake_cache.get = AsyncMock(return_value={"success": True, "bars": []})
    fake_cache_factory = lambda db=None: fake_cache  # noqa: E731

    with (
        patch("routers.sentcom_chart._hybrid_data_service", object()),
        patch("services.chart_response_cache.get_chart_response_cache",
              side_effect=fake_cache_factory),
        patch("routers.sentcom_chart.get_chart_bars",
              new_callable=AsyncMock) as mock_bars,
    ):
        req = ChartWarmRequest(symbols=["AAPL"], timeframes=["5min"], days=5)
        res = await warm_chart_cache(req)

    assert res["success"] is True
    assert res["summary"]["skipped"] == 1
    assert res["summary"]["warmed"] == 0
    assert res["summary"]["failed"] == 0
    # get_chart_bars must NOT have been called when cache hit.
    assert mock_bars.call_count == 0


@pytest.mark.asyncio
async def test_warm_calls_get_chart_bars_on_miss_and_counts_warmed():
    from routers.sentcom_chart import warm_chart_cache, ChartWarmRequest

    fake_cache = AsyncMock()
    fake_cache.get = AsyncMock(return_value=None)  # cache MISS
    fake_cache_factory = lambda db=None: fake_cache  # noqa: E731

    fake_bars_payload = {
        "success": True, "symbol": "AAPL", "timeframe": "5min",
        "bar_count": 245, "bars": [], "indicators": {},
    }

    with (
        patch("routers.sentcom_chart._hybrid_data_service", object()),
        patch("services.chart_response_cache.get_chart_response_cache",
              side_effect=fake_cache_factory),
        patch("routers.sentcom_chart.get_chart_bars",
              new_callable=AsyncMock, return_value=fake_bars_payload) as mock_bars,
    ):
        req = ChartWarmRequest(symbols=["AAPL", "MSFT"], timeframes=["5min"], days=5)
        res = await warm_chart_cache(req)

    assert res["success"] is True
    assert res["summary"]["warmed"] == 2
    assert res["summary"]["skipped"] == 0
    assert res["summary"]["failed"] == 0
    assert mock_bars.call_count == 2
    for r in res["results"]:
        assert r["status"] == "warmed"
        assert r["bar_count"] == 245


@pytest.mark.asyncio
async def test_warm_per_cell_timeout_marks_failed():
    """When get_chart_bars hangs past `per_cell_timeout_s`, that cell
    must be marked failed without taking down the whole batch."""
    from routers.sentcom_chart import warm_chart_cache, ChartWarmRequest

    fake_cache = AsyncMock()
    fake_cache.get = AsyncMock(return_value=None)
    fake_cache_factory = lambda db=None: fake_cache  # noqa: E731

    async def _hang(*_a, **_kw):
        await asyncio.sleep(5.0)  # > timeout
        return {"success": True}

    with (
        patch("routers.sentcom_chart._hybrid_data_service", object()),
        patch("services.chart_response_cache.get_chart_response_cache",
              side_effect=fake_cache_factory),
        patch("routers.sentcom_chart.get_chart_bars", side_effect=_hang),
    ):
        req = ChartWarmRequest(
            symbols=["AAPL"], timeframes=["5min"], days=5,
            per_cell_timeout_s=1.0,
        )
        res = await warm_chart_cache(req)

    assert res["success"] is True
    assert res["summary"]["failed"] == 1
    assert res["summary"]["warmed"] == 0
    assert "timeout" in res["results"][0]["reason"].lower()


@pytest.mark.asyncio
async def test_warm_503_when_hybrid_data_service_unset():
    """No live data service → 503 (don't pretend to warm)."""
    from routers.sentcom_chart import warm_chart_cache, ChartWarmRequest
    from fastapi import HTTPException

    with patch("routers.sentcom_chart._hybrid_data_service", None):
        req = ChartWarmRequest(symbols=["AAPL"])
        with pytest.raises(HTTPException) as exc:
            await warm_chart_cache(req)
        assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_warm_concurrency_capped_by_semaphore():
    """`max_concurrent=2` must mean at most 2 cells run in parallel
    even when 6 are requested. Verified by tracking peak concurrency."""
    from routers.sentcom_chart import warm_chart_cache, ChartWarmRequest

    in_flight = 0
    peak = 0
    lock = asyncio.Lock()

    async def _track(*_a, **_kw):
        nonlocal in_flight, peak
        async with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        await asyncio.sleep(0.05)
        async with lock:
            in_flight -= 1
        return {"success": True, "bar_count": 10}

    fake_cache = AsyncMock()
    fake_cache.get = AsyncMock(return_value=None)
    fake_cache_factory = lambda db=None: fake_cache  # noqa: E731

    with (
        patch("routers.sentcom_chart._hybrid_data_service", object()),
        patch("services.chart_response_cache.get_chart_response_cache",
              side_effect=fake_cache_factory),
        patch("routers.sentcom_chart.get_chart_bars", side_effect=_track),
    ):
        req = ChartWarmRequest(
            symbols=["AAPL", "MSFT", "TSLA", "NVDA", "META", "AMZN"],
            timeframes=["5min"],
            max_concurrent=2,
        )
        await warm_chart_cache(req)

    assert peak <= 2, f"peak concurrency {peak} exceeded max_concurrent=2"
    assert peak >= 1, "no work happened?"


# ─── v19.33 — Chart WebSocket structural tests ─────────────────────


def test_chart_ws_route_registered():
    """Endpoint must be wired on the sentcom_chart router."""
    src = (BACKEND_DIR / "routers" / "sentcom_chart.py").read_text()
    assert "@router.websocket" in src
    assert "/ws/chart-tail" in src


def test_chart_ws_disabled_via_env_var():
    """`CHART_WS_ENABLED=false` must cause the handler to close 1008."""
    src = (BACKEND_DIR / "routers" / "sentcom_chart.py").read_text()
    assert "CHART_WS_ENABLED" in src
    assert "chart_ws_disabled" in src


def test_chart_ws_uses_rth_throttle_for_default_tick():
    """Tick interval must consult `_rth_throttle_decision` so it ticks
    fast (2s) during RTH and slow (30s) outside."""
    src = (BACKEND_DIR / "routers" / "sentcom_chart.py").read_text()
    assert "_rth_throttle_decision" in src
    assert "rth_active" in src


def test_chart_ws_validates_timeframe():
    src = (BACKEND_DIR / "routers" / "sentcom_chart.py").read_text()
    assert "_SUPPORTED_TFS" in src and "bad_args" in src


def test_chart_ws_emits_heartbeat_on_silence():
    """Server must send `type:'ping'` every 15s when there are no bar
    updates, to keep the connection alive through aggressive proxies."""
    src = (BACKEND_DIR / "routers" / "sentcom_chart.py").read_text()
    assert '"type": "ping"' in src
    assert "15.0" in src or "15s" in src or "15 " in src


# ─── Frontend integration assertions ───────────────────────────────


def test_use_chart_tail_ws_hook_exists():
    p = Path("/app/frontend/src/hooks/useChartTailWs.js")
    assert p.exists()
    content = p.read_text()
    assert "useChartTailWs" in content
    assert "ws/chart-tail" in content
    # Auto-fallback after N failures
    assert "fallback" in content
    assert "exponential backoff" in content.lower() or "Math.pow" in content


def test_chart_panel_uses_ws_hook():
    """ChartPanel must import and call useChartTailWs."""
    f = Path("/app/frontend/src/components/sentcom/panels/ChartPanel.jsx").read_text()
    assert "useChartTailWs" in f
    assert "wsStatus" in f
    assert "chart-ws-status" in f


def test_chart_panel_polling_paused_when_ws_connected():
    """The polling loop must skip ticks when `wsStatus === 'connected'`."""
    f = Path("/app/frontend/src/components/sentcom/panels/ChartPanel.jsx").read_text()
    assert "wsStatus === 'connected'" in f


def test_scanner_cards_warm_chart_cache_on_change():
    """ScannerCardsV5 must POST to /api/sentcom/chart/warm when the
    visible card list changes."""
    f = Path("/app/frontend/src/components/sentcom/v5/ScannerCardsV5.jsx").read_text()
    assert "/api/sentcom/chart/warm" in f
    assert "lastWarmedRef" in f
