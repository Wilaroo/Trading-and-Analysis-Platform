"""
Regression tests for Phase 3 — Predictive Scanner IB-only path.

Locks in:
  * `_alpaca_service` instance var + `alpaca_service` lazy-init property
    are GONE from PredictiveScannerService (strict IB-only).
  * `_get_market_data` falls back to
    `services.live_symbol_snapshot.get_latest_snapshot` (pusher RPC + cache)
    when the enhanced scanner has no tape data — NOT to Alpaca.
  * The fallback shape returned to the scanner contains the keys the
    rest of the scanner pipeline expects (`current_price`, `bid`, `ask`,
    `technicals.*`, `scores.*`, etc.).
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, patch

import pytest

from services.predictive_scanner import PredictiveScannerService


# ----------------------------------------------------------------------
# Surface invariants — these are the structural guarantees Phase 3 made.
# ----------------------------------------------------------------------

def test_no_alpaca_service_instance_var():
    s = PredictiveScannerService(db=None)
    assert not hasattr(s, "_alpaca_service"), (
        "PredictiveScannerService still carries _alpaca_service. "
        "Phase 3 removed it for strict IB-only architecture."
    )


def test_no_alpaca_service_property():
    assert "alpaca_service" not in dir(PredictiveScannerService), (
        "PredictiveScannerService.alpaca_service property must be removed. "
        "Live data flows through services.live_symbol_snapshot now."
    )


def test_get_market_data_imports_live_symbol_snapshot():
    src = inspect.getsource(PredictiveScannerService._get_market_data)
    assert "from services.live_symbol_snapshot import get_latest_snapshot" in src, (
        "_get_market_data fallback must import get_latest_snapshot. "
        "If you re-introduce another data source, update this guard."
    )


def test_get_market_data_no_alpaca_get_quote_call():
    src = inspect.getsource(PredictiveScannerService._get_market_data)
    assert "alpaca_service.get_quote" not in src, (
        "Phase 3 removed alpaca_service.get_quote from the scanner. "
        "Use get_latest_snapshot instead."
    )


# ----------------------------------------------------------------------
# Behaviour test — fallback path returns the shape the scanner needs.
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_market_data_falls_back_to_live_snapshot():
    """When the enhanced scanner has no tape, _get_market_data must call
    `get_latest_snapshot` and translate the response into the scanner's
    market_data dict."""
    s = PredictiveScannerService(db=None)
    # No enhanced scanner → forces the fallback path
    s._enhanced_scanner = None

    fake_snapshot = {
        "success": True,
        "symbol": "SPY",
        "latest_price": 452.37,
        "latest_bar_time": "2026-04-26T15:30:00Z",
        "prev_close": 451.90,
        "change_abs": 0.47,
        "change_pct": 0.104,
        "bar_size": "5 mins",
        "bar_count": 78,
        "market_state": "rth",
        "source": "pusher_rpc",
        "fetched_at": "2026-04-26T15:30:05Z",
        "error": None,
    }

    with patch(
        "services.live_symbol_snapshot.get_latest_snapshot",
        new=AsyncMock(return_value=fake_snapshot),
    ):
        md = await s._get_market_data("SPY")

    assert md is not None
    assert md["symbol"] == "SPY"
    assert md["current_price"] == pytest.approx(452.37)
    # Bid/ask spread should bracket the mid
    assert md["bid"] < md["current_price"] < md["ask"]
    # Required downstream keys for setup checking
    for k in (
        "vwap", "ema_9", "ema_20", "rsi_14", "rvol", "atr",
        "high", "low", "resistance", "support",
    ):
        assert k in md["technicals"], f"missing technical key {k}"
    for k in ("overall", "technical", "fundamental", "catalyst"):
        assert k in md["scores"], f"missing scores key {k}"


@pytest.mark.asyncio
async def test_market_data_returns_none_on_snapshot_failure():
    """If the live snapshot service fails (pusher down, weekend, etc.)
    _get_market_data should return None — no synthetic data."""
    s = PredictiveScannerService(db=None)
    s._enhanced_scanner = None

    fail_snapshot = {
        "success": False,
        "symbol": "SPY",
        "latest_price": None,
        "error": "pusher_rpc_unreachable",
    }

    with patch(
        "services.live_symbol_snapshot.get_latest_snapshot",
        new=AsyncMock(return_value=fail_snapshot),
    ):
        md = await s._get_market_data("SPY")

    assert md is None, (
        "On snapshot failure the scanner must return None so the symbol "
        "is silently skipped (no Alpaca fallback, no synthetic data)."
    )
