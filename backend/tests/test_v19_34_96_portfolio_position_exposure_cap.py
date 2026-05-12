"""
Tests for v19.34.96 portfolio-level position-style exposure cap (30% default).

Validates:
  - compute_exposure correctly sums dollar value of POSITION-style open trades
  - non-position styles are ignored
  - cap defaults to 30%, override via kwarg works
  - position_sizer.calculate_size enforces remaining_value as final cap
  - cap exhausted → final shares = 0 + warning
  - non-position styles unaffected by the cap
  - max_additional_shares helper
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

import pytest

from services.portfolio_exposure_guard import (
    DEFAULT_LONG_HORIZON_EXPOSURE_CAP_PCT,
    DEFAULT_POSITION_EXPOSURE_CAP_PCT,
    LONG_HORIZON_STYLES,
    POSITION_STYLES,
    compute_exposure,
    max_additional_shares,
)
from services.position_sizer import PositionSizerService, SizingMode


# Simple fake trade for testing
@dataclass
class FakeTrade:
    symbol: str = "AAPL"
    trade_style: str = "position"
    remaining_shares: int = 100
    shares: int = 100
    current_price: float = 50.0
    entry_price: float = 49.0
    setup_type: str = "stage_2_breakout"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if not asyncio.iscoroutine(coro) else asyncio.new_event_loop().run_until_complete(coro)


# ─────────────────────────────────────────────────────────────────
# compute_exposure
# ─────────────────────────────────────────────────────────────────
class TestComputeExposure:
    def test_empty_open_trades(self):
        snap = compute_exposure([], account_value=100_000)
        assert snap.current_value == 0
        assert snap.open_trades_count == 0
        assert snap.cap_breached is False
        assert snap.remaining_value == 30_000  # 30% of 100K default

    def test_default_cap_is_30_percent(self):
        assert DEFAULT_POSITION_EXPOSURE_CAP_PCT == 30.0

    def test_only_position_styles_counted_by_default(self):
        trades = [
            FakeTrade(symbol="AAA", trade_style="position", remaining_shares=100, current_price=50),  # $5K
            FakeTrade(symbol="BBB", trade_style="scalp", remaining_shares=200, current_price=100),   # ignored
            FakeTrade(symbol="CCC", trade_style="intraday", remaining_shares=50, current_price=80),  # ignored
            FakeTrade(symbol="DDD", trade_style="swing", remaining_shares=50, current_price=80),     # ignored (not in default set)
        ]
        snap = compute_exposure(trades, account_value=100_000)
        assert snap.current_value == 5000.0
        assert snap.open_trades_count == 1
        assert snap.breakdown[0]["symbol"] == "AAA"

    def test_cap_breach_detected(self):
        trades = [
            FakeTrade(symbol="X", trade_style="position", remaining_shares=600, current_price=50),
        ]
        # 600 * 50 = 30000 = 30% of 100K → at cap (breach inclusive)
        snap = compute_exposure(trades, account_value=100_000)
        assert snap.current_value == 30_000
        assert snap.cap_breached is True
        assert snap.remaining_value == 0

    def test_custom_cap_pct(self):
        trades = [FakeTrade(remaining_shares=100, current_price=50)]  # $5K
        snap = compute_exposure(trades, account_value=100_000, cap_pct=10.0)
        assert snap.cap_pct == 10.0
        assert snap.cap_value == 10_000
        assert snap.remaining_value == 5_000

    def test_zero_account_value(self):
        snap = compute_exposure([FakeTrade()], account_value=0)
        assert snap.current_value == 0
        assert snap.cap_breached is False

    def test_handles_dict_trades(self):
        trades = [
            {"symbol": "DICT", "trade_style": "position", "remaining_shares": 100, "current_price": 75},
        ]
        snap = compute_exposure(trades, account_value=100_000)
        assert snap.current_value == 7_500
        assert snap.breakdown[0]["symbol"] == "DICT"

    def test_fallback_to_entry_price(self):
        # current_price missing → falls back to entry_price
        trades = [
            FakeTrade(remaining_shares=100, current_price=0, entry_price=42.0),
        ]
        snap = compute_exposure(trades, account_value=100_000)
        assert snap.current_value == 4_200

    def test_styles_override(self):
        # Including SWING by passing custom styles set
        trades = [
            FakeTrade(symbol="SW", trade_style="swing", remaining_shares=100, current_price=50),
            FakeTrade(symbol="PO", trade_style="position", remaining_shares=100, current_price=50),
        ]
        snap = compute_exposure(trades, account_value=100_000, styles={"swing", "position"})
        assert snap.current_value == 10_000
        assert snap.open_trades_count == 2

    def test_max_additional_shares_helper(self):
        trades = [FakeTrade(remaining_shares=400, current_price=50)]  # $20K, room $10K
        snap = compute_exposure(trades, account_value=100_000)
        assert snap.remaining_value == 10_000
        # At entry $100 → 100 shares fit; at entry $150 → 66 shares
        assert max_additional_shares(snap, 100.0) == 100
        assert max_additional_shares(snap, 150.0) == 66

    def test_max_additional_shares_when_capped(self):
        trades = [FakeTrade(remaining_shares=600, current_price=50)]  # $30K = cap
        snap = compute_exposure(trades, account_value=100_000)
        assert max_additional_shares(snap, 100.0) == 0


# ─────────────────────────────────────────────────────────────────
# position_sizer integration
# ─────────────────────────────────────────────────────────────────
class TestPositionSizerCapIntegration:
    def setup_method(self):
        self.svc = PositionSizerService()
        self.svc.configure({"mode": "fixed_percent", "max_risk_per_trade_pct": 1.0, "max_position_pct": 100.0})

    def test_position_style_capped_to_remaining_value(self):
        loop = asyncio.new_event_loop()
        try:
            # Account $100K, room $10K remaining under cap
            result = loop.run_until_complete(self.svc.calculate_size(
                entry_price=50.0,
                stop_price=48.0,
                account_value=100_000,
                tqs_score=70.0,
                trade_style="position",
                position_style_exposure_remaining_value=10_000.0,
            ))
            # 10K / 50 = max 200 shares regardless of risk math
            assert result.shares <= 200
            assert any("cap" in w.lower() for w in result.warnings)
        finally:
            loop.close()

    def test_position_style_cap_exhausted_blocks_entry(self):
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(self.svc.calculate_size(
                entry_price=50.0,
                stop_price=48.0,
                account_value=100_000,
                trade_style="position",
                position_style_exposure_remaining_value=0.0,
            ))
            assert result.shares == 0
            assert any("blocked" in w.lower() or "exhausted" in w.lower() for w in result.warnings)
        finally:
            loop.close()

    def test_non_position_style_unaffected_by_cap(self):
        loop = asyncio.new_event_loop()
        try:
            # Scalp trade should NOT be capped by position-style exposure
            result = loop.run_until_complete(self.svc.calculate_size(
                entry_price=50.0,
                stop_price=48.0,
                account_value=100_000,
                trade_style="scalp",
                position_style_exposure_remaining_value=0.0,  # exhausted
            ))
            assert result.shares > 0  # not blocked
        finally:
            loop.close()

    def test_no_trade_style_means_no_cap_applied(self):
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(self.svc.calculate_size(
                entry_price=50.0,
                stop_price=48.0,
                account_value=100_000,
                # Note: trade_style="" and remaining=None → legacy behavior preserved
            ))
            assert result.shares > 0
        finally:
            loop.close()

    def test_cap_config_reflected_in_config_dict(self):
        cfg = self.svc.get_config()
        assert "max_position_style_exposure_pct" in cfg
        assert cfg["max_position_style_exposure_pct"] == 30.0

    def test_cap_config_can_be_overridden(self):
        self.svc.configure({"max_position_style_exposure_pct": 25.0})
        cfg = self.svc.get_config()
        assert cfg["max_position_style_exposure_pct"] == 25.0


# ─────────────────────────────────────────────────────────────────
# Realistic scenarios
# ─────────────────────────────────────────────────────────────────
class TestRealisticScenarios:
    def test_six_open_positions_at_5pct_each_breaches_cap(self):
        # 6 positions × 5% = 30% (right at cap)
        trades = [
            FakeTrade(symbol=f"P{i}", trade_style="position",
                      remaining_shares=100, current_price=50.0)  # $5K each
            for i in range(6)
        ]
        snap = compute_exposure(trades, account_value=100_000)
        assert snap.current_value == 30_000
        assert snap.cap_breached is True
        assert snap.remaining_value == 0

    def test_four_open_positions_at_5pct_each_allows_more(self):
        trades = [
            FakeTrade(symbol=f"P{i}", trade_style="position",
                      remaining_shares=100, current_price=50.0)
            for i in range(4)
        ]
        snap = compute_exposure(trades, account_value=100_000)
        assert snap.current_value == 20_000
        assert snap.cap_breached is False
        assert snap.remaining_value == 10_000  # room for one more 5-10% trade

    def test_mixed_styles_only_position_counted(self):
        trades = [
            FakeTrade(symbol="A", trade_style="position", remaining_shares=100, current_price=100),   # $10K
            FakeTrade(symbol="B", trade_style="scalp", remaining_shares=500, current_price=200),      # $100K (ignored)
            FakeTrade(symbol="C", trade_style="intraday", remaining_shares=300, current_price=150),   # $45K (ignored)
        ]
        snap = compute_exposure(trades, account_value=100_000)
        assert snap.current_value == 10_000   # only A counted
        assert snap.open_trades_count == 1

    def test_position_styles_constant_default(self):
        assert "position" in POSITION_STYLES
        assert "scalp" not in POSITION_STYLES
        assert "intraday" not in POSITION_STYLES


# ─────────────────────────────────────────────────────────────────
# v19.34.97 — combined long-horizon cap (55%)
# ─────────────────────────────────────────────────────────────────
class TestLongHorizonCap:
    def test_default_long_horizon_cap_55(self):
        assert DEFAULT_LONG_HORIZON_EXPOSURE_CAP_PCT == 55.0

    def test_long_horizon_styles_constant(self):
        assert "multi_day" in LONG_HORIZON_STYLES
        assert "swing" in LONG_HORIZON_STYLES
        assert "investment" in LONG_HORIZON_STYLES
        assert "position" in LONG_HORIZON_STYLES
        assert "scalp" not in LONG_HORIZON_STYLES
        assert "intraday" not in LONG_HORIZON_STYLES

    def test_long_horizon_combined_aggregation(self):
        # 20% in swing + 15% in investment + 10% in position = 45% combined
        trades = [
            FakeTrade(symbol="SW", trade_style="swing", remaining_shares=400, current_price=50),     # $20K
            FakeTrade(symbol="IV", trade_style="investment", remaining_shares=300, current_price=50), # $15K
            FakeTrade(symbol="PO", trade_style="position", remaining_shares=200, current_price=50),  # $10K
            FakeTrade(symbol="SC", trade_style="scalp", remaining_shares=500, current_price=100),    # ignored
        ]
        snap = compute_exposure(trades, account_value=100_000, styles=LONG_HORIZON_STYLES)
        assert snap.current_value == 45_000
        assert snap.open_trades_count == 3
        # Cap 55% → 55K cap → 10K remaining
        snap55 = compute_exposure(trades, account_value=100_000, cap_pct=55.0, styles=LONG_HORIZON_STYLES)
        assert snap55.cap_value == 55_000
        assert snap55.remaining_value == 10_000

    def test_combined_cap_breach(self):
        # Push combined to 55% exactly
        trades = [
            FakeTrade(symbol="A", trade_style="swing", remaining_shares=600, current_price=50),     # $30K
            FakeTrade(symbol="B", trade_style="position", remaining_shares=500, current_price=50),  # $25K
        ]
        snap = compute_exposure(trades, account_value=100_000, cap_pct=55.0, styles=LONG_HORIZON_STYLES)
        assert snap.current_value == 55_000
        assert snap.cap_breached is True
        assert snap.remaining_value == 0


class TestStackedCaps:
    """Both 30% position AND 55% long-horizon caps must be honored —
    whichever is more restrictive wins."""

    def setup_method(self):
        self.svc = PositionSizerService()
        self.svc.configure({
            "mode": "fixed_percent",
            "max_risk_per_trade_pct": 1.0,
            "max_position_pct": 100.0,
        })

    def _calc(self, **kw):
        defaults = {
            "entry_price": 50.0,
            "stop_price": 48.0,
            "account_value": 100_000,
            "tqs_score": 70.0,
        }
        defaults.update(kw)
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.svc.calculate_size(**defaults))
        finally:
            loop.close()

    def test_long_horizon_cap_applies_to_swing(self):
        # 0 position used, $10K long-horizon remaining (e.g., 45% already in
        # swing+investment, so only 10K to go before 55% cap).
        result = self._calc(
            trade_style="swing",
            long_horizon_exposure_remaining_value=10_000.0,
        )
        assert result.shares <= 200  # $10K / $50 = 200
        assert any("long-horizon" in w.lower() for w in result.warnings)

    def test_long_horizon_cap_exhausted_blocks_swing(self):
        result = self._calc(
            trade_style="swing",
            long_horizon_exposure_remaining_value=0.0,
        )
        assert result.shares == 0
        assert any("exhausted" in w.lower() for w in result.warnings)

    def test_position_uses_more_restrictive_of_two_caps(self):
        # Position cap has $20K room, long-horizon has $5K room.
        # More restrictive ($5K) should win.
        result = self._calc(
            trade_style="position",
            position_style_exposure_remaining_value=20_000.0,
            long_horizon_exposure_remaining_value=5_000.0,
        )
        assert result.shares <= 100  # $5K / $50
        warning_text = " ".join(result.warnings).lower()
        assert "long-horizon" in warning_text

    def test_position_uses_more_restrictive_when_position_tighter(self):
        # Position cap has $3K room, long-horizon $40K room.
        # Position cap wins.
        result = self._calc(
            trade_style="position",
            position_style_exposure_remaining_value=3_000.0,
            long_horizon_exposure_remaining_value=40_000.0,
        )
        assert result.shares <= 60  # $3K / $50
        warning_text = " ".join(result.warnings).lower()
        assert "position-style" in warning_text

    def test_scalp_immune_to_both_caps(self):
        result = self._calc(
            trade_style="scalp",
            position_style_exposure_remaining_value=0.0,
            long_horizon_exposure_remaining_value=0.0,
        )
        assert result.shares > 0

    def test_intraday_immune_to_both_caps(self):
        result = self._calc(
            trade_style="intraday",
            position_style_exposure_remaining_value=0.0,
            long_horizon_exposure_remaining_value=0.0,
        )
        assert result.shares > 0

    def test_config_exposes_both_cap_pcts(self):
        cfg = self.svc.get_config()
        assert cfg["max_position_style_exposure_pct"] == 30.0
        assert cfg["max_long_horizon_exposure_pct"] == 55.0

    def test_long_horizon_cap_config_override(self):
        self.svc.configure({"max_long_horizon_exposure_pct": 50.0})
        cfg = self.svc.get_config()
        assert cfg["max_long_horizon_exposure_pct"] == 50.0
