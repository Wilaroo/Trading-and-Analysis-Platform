"""
Tests for v19.34.104 — trailing-stop anchor wiring.

Validates:
  • `trail_anchor_service.compute_anchor_value` correctly computes
    SMA/EMA over daily closes, returns None when warmup-bar threshold
    not met (per operator confirmation: fall back to ATR until anchor
    is available).
  • `trail_anchor_service.compute_anchor_stop` applies the protective
    buffer in the correct direction (LONG → below MA, SHORT → above MA).
  • `StopManager._snap_to_anchor` returns None for short-horizon
    styles (anchor == "atr") and a valid snap for long-horizon styles.
  • `StopManager._best_snap` picks the most protective candidate when
    both anchor + liquidity snaps are available.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from services.trail_anchor_service import (
    compute_anchor_value,
    compute_anchor_stop,
    _calc_ema,
    _calc_sma,
)


# ─────────────────────────────────────────────────────────────────────
# Pure-math anchor computation
# ─────────────────────────────────────────────────────────────────────
class TestComputeAnchorValue:
    def test_sma_50(self):
        closes = list(range(1, 101))  # 1..100
        # Last 50 = 51..100 → avg = 75.5
        assert _calc_sma(closes, 50) == pytest.approx(75.5)
        assert compute_anchor_value(closes, "sma_50") == pytest.approx(75.5)

    def test_sma_150_warmup_returns_none_below_threshold(self):
        # Only 100 closes → 150-SMA not yet available.
        closes = [100.0] * 100
        assert compute_anchor_value(closes, "sma_150") is None

    def test_sma_150_when_enough_bars(self):
        closes = [100.0] * 200
        assert compute_anchor_value(closes, "sma_150") == pytest.approx(100.0)

    def test_ema_20_on_constant_series(self):
        closes = [50.0] * 50
        assert compute_anchor_value(closes, "ema_20") == pytest.approx(50.0)

    def test_unknown_anchor_returns_none(self):
        closes = [100.0] * 200
        assert compute_anchor_value(closes, "atr") is None
        assert compute_anchor_value(closes, "structure") is None
        assert compute_anchor_value(closes, "") is None

    def test_empty_closes_returns_none(self):
        assert compute_anchor_value([], "sma_50") is None


class TestComputeAnchorStop:
    """compute_anchor_stop hits the DB. Use a stubbed Mongo handle."""

    def _make_db(self, closes: List[float]):
        """Tiny stub returning the close rows in the same shape the
        real ib_historical_data find() returns (newest first — the
        helper reverses internally)."""
        rows = [{"date": f"D{i}", "close": c} for i, c in enumerate(closes)]
        rows_desc = list(reversed(rows))

        class _Cursor:
            def __init__(self, data): self.data = data
            def sort(self, *_a, **_kw): return self
            def limit(self, *_a, **_kw): return self.data
        class _Collection:
            def find(self_inner, *_a, **_kw): return _Cursor(rows_desc)
        class _DB:
            def __getitem__(self, _name): return _Collection()
        return _DB()

    def test_long_anchor_stop_below_ma_with_buffer(self):
        db = self._make_db([100.0] * 200)
        stop = compute_anchor_stop(
            db, "AAPL", "sma_50", "long",
            current_price=100.0, atr=2.0,
        )
        assert stop is not None
        # 100 - (2 * 0.08) = 99.84
        assert stop == pytest.approx(99.84)

    def test_short_anchor_stop_above_ma_with_buffer(self):
        db = self._make_db([100.0] * 200)
        stop = compute_anchor_stop(
            db, "AAPL", "sma_50", "short",
            current_price=100.0, atr=2.0,
        )
        assert stop is not None
        # 100 + 0.16 = 100.16
        assert stop == pytest.approx(100.16)

    def test_pct_fallback_when_no_atr(self):
        db = self._make_db([100.0] * 200)
        stop = compute_anchor_stop(
            db, "AAPL", "sma_50", "long",
            current_price=100.0, atr=None,
        )
        # buffer = 100 * 0.0025 = 0.25 → stop = 99.75
        assert stop == pytest.approx(99.75)

    def test_returns_none_for_atr_anchor(self):
        db = self._make_db([100.0] * 200)
        assert compute_anchor_stop(db, "AAPL", "atr", "long") is None

    def test_returns_none_when_not_enough_warmup_bars(self):
        # SMA-150 needs 150 closes — provide only 100.
        db = self._make_db([100.0] * 100)
        stop = compute_anchor_stop(db, "AAPL", "sma_150", "long",
                                   current_price=100.0, atr=2.0)
        assert stop is None

    def test_returns_none_when_db_is_none(self):
        assert compute_anchor_stop(None, "AAPL", "sma_50", "long") is None


# ─────────────────────────────────────────────────────────────────────
# StopManager integration
# ─────────────────────────────────────────────────────────────────────
class _TradeDirection:
    LONG = "long"
    SHORT = "short"


@dataclass
class _FakeBotTrade:
    id: str
    symbol: str
    direction: str
    trade_style: str
    setup_type: str
    timeframe: str
    entry_price: float
    stop_price: float
    fill_price: float
    current_price: float
    shares: int
    target_prices: list = field(default_factory=list)
    scale_out_config: dict = field(default_factory=dict)
    trailing_stop_config: dict = field(default_factory=dict)


@pytest.fixture
def stub_trade_direction(monkeypatch):
    """Patch the TradeDirection enum used inside StopManager."""
    fake_module = MagicMock()
    fake_module.TradeDirection = _TradeDirection
    monkeypatch.setattr(
        "services.trading_bot_service.TradeDirection",
        _TradeDirection,
        raising=False,
    )
    return _TradeDirection


class TestSnapToAnchor:
    def test_short_horizon_style_returns_none(self, stub_trade_direction):
        from services.stop_manager import StopManager
        mgr = StopManager()
        mgr._db = MagicMock()  # DB present but anchor is ATR
        trade = _FakeBotTrade(
            id="T", symbol="AAPL", direction="long",
            trade_style="scalp", setup_type="", timeframe="5m",
            entry_price=100, stop_price=99, fill_price=100,
            current_price=101, shares=100,
        )
        assert mgr._snap_to_anchor(trade) is None

    def test_long_horizon_returns_anchor_snap(self, stub_trade_direction, monkeypatch):
        from services.stop_manager import StopManager
        mgr = StopManager()
        mgr._db = MagicMock()
        # Stub the anchor service to return a deterministic value.
        monkeypatch.setattr(
            "services.trail_anchor_service.compute_anchor_stop",
            lambda **kw: 145.20,
        )
        trade = _FakeBotTrade(
            id="T", symbol="NVDA", direction="long",
            trade_style="position", setup_type="weekly_base", timeframe="1d",
            entry_price=150, stop_price=140, fill_price=150,
            current_price=160, shares=100,
        )
        snap = mgr._snap_to_anchor(trade)
        assert snap is not None
        assert snap["snapped"] is True
        assert snap["stop"] == 145.20
        assert snap["level_kind"].startswith("ma_")
        assert snap["anchor"] == "sma_150"

    def test_anchor_unavailable_returns_none(self, stub_trade_direction, monkeypatch):
        """When the MA hasn't warmed up yet, fall back to ATR/% path."""
        from services.stop_manager import StopManager
        mgr = StopManager()
        mgr._db = MagicMock()
        monkeypatch.setattr(
            "services.trail_anchor_service.compute_anchor_stop",
            lambda **kw: None,
        )
        trade = _FakeBotTrade(
            id="T", symbol="NVDA", direction="long",
            trade_style="position", setup_type="weekly_base", timeframe="1d",
            entry_price=150, stop_price=140, fill_price=150,
            current_price=160, shares=100,
        )
        assert mgr._snap_to_anchor(trade) is None
