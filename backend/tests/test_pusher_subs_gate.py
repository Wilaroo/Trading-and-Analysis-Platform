"""
Regression tests for the un-subscribed-symbol RPC gate added 2026-04-29
(afternoon-7) to `HybridDataService.fetch_latest_session_bars`.

Background: the pusher RPC `/rpc/latest-bars` was being called for
symbols not in the pusher's 14-symbol subscription list (e.g. XLE, GLD,
NFLX during scanner runs). Each miss forced the pusher to qualify a
contract on-demand and request bars synchronously — slow (5-10s),
flaky, and clogged the RPC queue. RPC p95 latency hit 4848ms in the
operator's afternoon screenshot.

The gate now skips the RPC entirely for un-subscribed symbols. Caller
(`realtime_technical_service._get_live_intraday_bars`) already handles
the `success: False` return → falls back to the Mongo `ib_historical_data`
cache, which is exactly what the scanner's tiered architecture wants
for the 1500-4000+ symbol universe.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def hds():
    """Fresh HybridDataService instance with the live_bar_cache disabled."""
    from services.hybrid_data_service import HybridDataService
    svc = HybridDataService()
    return svc


def test_skips_rpc_when_symbol_not_in_pusher_subscriptions(hds):
    """Operator's screenshot bug: scanner calls fetch_latest_session_bars
    for XLE; pusher only subscribes to 14 symbols (none XLE). Must
    short-circuit with `not_in_pusher_subscriptions` instead of hitting
    the RPC."""
    from services import hybrid_data_service as mod
    fake_rpc = MagicMock()
    fake_rpc.is_configured.return_value = True
    fake_rpc.subscriptions.return_value = {"SPY", "QQQ", "NVDA", "AAPL"}
    fake_rpc.latest_bars = MagicMock(side_effect=AssertionError(
        "latest_bars must NOT be called for un-subscribed symbol"
    ))

    fake_cache = MagicMock()
    fake_cache.get.return_value = None  # cache miss

    with patch("services.ib_pusher_rpc.get_pusher_rpc_client", return_value=fake_rpc), \
         patch("services.live_bar_cache.get_live_bar_cache",
               return_value=fake_cache):
        res = _run(hds.fetch_latest_session_bars("XLE", "5 mins"))

    assert res["success"] is False
    assert res["error"] == "not_in_pusher_subscriptions"
    assert res["pusher_subs_count"] == 4
    assert res["bars"] == []
    fake_rpc.latest_bars.assert_not_called()


def test_calls_rpc_when_symbol_is_subscribed(hds):
    """Symbols on the pusher's list still go through the RPC path."""
    fake_rpc = MagicMock()
    fake_rpc.is_configured.return_value = True
    fake_rpc.subscriptions.return_value = {"SPY", "QQQ", "NVDA", "AAPL"}
    fake_rpc.latest_bars = MagicMock(return_value=[
        {"date": "2026-04-29T13:30:00Z", "open": 503, "high": 504,
         "low": 502.5, "close": 503.20, "volume": 100000},
    ])

    fake_cache = MagicMock()
    fake_cache.get.return_value = None
    fake_cache.put.return_value = {"fetched_at": "2026-04-29T13:30:00Z"}

    with patch("services.ib_pusher_rpc.get_pusher_rpc_client", return_value=fake_rpc), \
         patch("services.live_bar_cache.get_live_bar_cache",
               return_value=fake_cache):
        res = _run(hds.fetch_latest_session_bars("SPY", "5 mins"))

    assert res["success"] is True
    assert res["source"] == "pusher_rpc"
    assert len(res["bars"]) == 1
    fake_rpc.latest_bars.assert_called_once()


def test_falls_back_to_rpc_when_subscriptions_unknown(hds):
    """If the pusher's subscription list query returns None/empty
    (RPC unreachable, race during startup), the gate must NOT block —
    falls through to the existing RPC path so we don't lose all live
    bars when the pusher is briefly slow to respond."""
    fake_rpc = MagicMock()
    fake_rpc.is_configured.return_value = True
    fake_rpc.subscriptions.return_value = None  # subs query failed
    fake_rpc.latest_bars = MagicMock(return_value=[
        {"date": "2026-04-29T13:30:00Z", "close": 503.20},
    ])

    fake_cache = MagicMock()
    fake_cache.get.return_value = None
    fake_cache.put.return_value = {}

    with patch("services.ib_pusher_rpc.get_pusher_rpc_client", return_value=fake_rpc), \
         patch("services.live_bar_cache.get_live_bar_cache",
               return_value=fake_cache):
        res = _run(hds.fetch_latest_session_bars("XLE", "5 mins"))

    assert res["success"] is True
    fake_rpc.latest_bars.assert_called_once()


def test_cache_hit_short_circuits_before_subs_check(hds):
    """When live_bar_cache has a fresh entry, we never even reach the
    subscriptions check — fastest path stays fastest."""
    fake_rpc = MagicMock()
    fake_rpc.subscriptions = MagicMock(side_effect=AssertionError(
        "subs check must NOT run on cache hit"
    ))

    fake_cache = MagicMock()
    fake_cache.get.return_value = {
        "bars": [{"date": "2026-04-29T13:30:00Z", "close": 503.20}],
        "market_state": "rth",
        "fetched_at": "2026-04-29T13:30:00Z",
    }

    with patch("services.ib_pusher_rpc.get_pusher_rpc_client", return_value=fake_rpc), \
         patch("services.live_bar_cache.get_live_bar_cache",
               return_value=fake_cache):
        res = _run(hds.fetch_latest_session_bars("XLE", "5 mins"))

    assert res["success"] is True
    assert res["source"] == "cache"
    fake_rpc.subscriptions.assert_not_called()
