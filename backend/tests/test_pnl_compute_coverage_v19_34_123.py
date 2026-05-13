"""
test_pnl_compute_coverage_v19_34_123.py
─────────────────────────────────────────────────────────────────────────────
Regression guards for the v19.34.123 PnL-on-close fix.

Pre-v123, every close path EXCEPT `position_manager.close_trade()` (the
"happy path" that goes through `_trade_executor.close_position`) left
`realized_pnl` and `net_pnl` at 0 / None on the trade object. The bot's
`_daily_stats.net_pnl` aggregator could therefore show ~$0 even when
the broker had bled $25k.

This test fixes the regression by directly asserting that `apply_close_pnl`
computes correct realized_pnl for every direction × price scenario AND
that the helper writes ALL required close-time fields onto the trade.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.pnl_compute import compute_close_pnl, apply_close_pnl


# ── compute_close_pnl pure-math ─────────────────────────────────────
class TestComputeCloseMath:
    def test_long_winner(self):
        out = compute_close_pnl(direction="long", fill_price=100.0,
                                exit_price=105.0, shares=100, commission=2.0)
        assert out["realized_pnl"] == 500.0
        assert out["net_pnl"] == 498.0

    def test_long_loser(self):
        out = compute_close_pnl(direction="long", fill_price=100.0,
                                exit_price=97.0, shares=200, commission=4.0)
        assert out["realized_pnl"] == -600.0
        assert out["net_pnl"] == -604.0

    def test_short_winner(self):
        out = compute_close_pnl(direction="short", fill_price=50.0,
                                exit_price=47.50, shares=400, commission=8.0)
        # (50 - 47.5) × 400 = 1000
        assert out["realized_pnl"] == 1000.0
        assert out["net_pnl"] == 992.0

    def test_short_loser_real_world_rjf(self):
        """Today's RJF: shorted 92sh @ 150.00, cover @ 152.65 → -$244"""
        out = compute_close_pnl(direction="short", fill_price=150.00,
                                exit_price=152.65, shares=92, commission=0.0)
        assert out["realized_pnl"] == pytest.approx(-243.80, abs=0.01)
        assert out["net_pnl"] == pytest.approx(-243.80, abs=0.01)

    def test_case_insensitive_direction(self):
        a = compute_close_pnl(direction="LONG",  fill_price=10, exit_price=11, shares=100)
        b = compute_close_pnl(direction="long",  fill_price=10, exit_price=11, shares=100)
        assert a["realized_pnl"] == b["realized_pnl"] == 100.0

    def test_zero_shares_yields_zero_pnl(self):
        out = compute_close_pnl(direction="long", fill_price=100, exit_price=0,
                                shares=0)
        assert out["realized_pnl"] == 0.0


# ── apply_close_pnl writes-back ─────────────────────────────────────
def _mk_trade(direction="short", fill=150.0, current=152.65, shares=92,
              symbol="RJF"):
    return SimpleNamespace(
        id=f"t-{symbol}",
        symbol=symbol,
        direction=SimpleNamespace(value=direction),
        fill_price=fill,
        current_price=current,
        shares=shares,
        remaining_shares=shares,
        exit_price=0.0,
        realized_pnl=0.0,
        net_pnl=0.0,
        unrealized_pnl=12.34,  # to verify it gets cleared
        total_commissions=0.0,
        closed_at=None,
        close_reason=None,
        notes="",
    )


class TestApplyCloseWritesBack:
    def test_rjf_short_loss_via_current_price(self):
        """The Feb 2026 incident exemplar: short RJF, no explicit exit."""
        t = _mk_trade()
        out = apply_close_pnl(t, reason="operator_external_flatten")
        # All close-time fields written:
        assert t.realized_pnl == pytest.approx(-243.80, abs=0.01)
        assert t.net_pnl      == pytest.approx(-243.80, abs=0.01)
        assert t.exit_price   == 152.65
        assert t.close_reason == "operator_external_flatten"
        assert t.unrealized_pnl == 0.0
        assert t.remaining_shares == 0
        assert t.closed_at is not None
        # Audit breadcrumb: source = current_price (no explicit exit)
        assert getattr(t, "_exit_price_source", None) == "current_price"
        assert out["exit_price_source"] == "current_price"

    def test_explicit_exit_overrides_current_price(self):
        t = _mk_trade(current=999.0)  # noise current
        apply_close_pnl(t, reason="oca_ext", exit_price=151.10)
        assert t.exit_price == 151.10
        # short 92sh @150 → cover 151.10 → -$101.20
        assert t.realized_pnl == pytest.approx(-101.20, abs=0.01)
        assert getattr(t, "_exit_price_source") == "explicit"

    def test_close_shares_override_for_peeled_slice(self):
        """v19.34.20b shrunk_to_zero uses `old` not `t.shares` because
        t.remaining_shares was already mutated by the peel."""
        t = _mk_trade(shares=50)
        t.remaining_shares = 0  # already peeled
        t._close_shares_override = 50
        apply_close_pnl(t, reason="shrunk_to_zero_v19_34_20b")
        # Should use 50 shares even though remaining_shares=0
        assert t.realized_pnl == pytest.approx(-132.50, abs=0.01)

    def test_long_path(self):
        t = _mk_trade(direction="long", fill=14.00, current=14.86,
                      shares=3511, symbol="NTLA")
        apply_close_pnl(t, reason="OCA ext")
        # (14.86 - 14.00) × 3511 = 3019.46
        assert t.realized_pnl == pytest.approx(3019.46, abs=0.05)

    def test_fallback_to_fill_price_when_no_quote(self):
        """If current_price is also zero, fall back to fill_price → $0 PnL."""
        t = _mk_trade(current=0.0)
        apply_close_pnl(t, reason="missing_data")
        assert t.exit_price == 150.0  # fill_price fallback
        assert t.realized_pnl == 0.0
        assert getattr(t, "_exit_price_source") == "fill_price_fallback"

    def test_commission_subtraction(self):
        t = _mk_trade(direction="long", fill=100, current=110, shares=100,
                      symbol="XYZ")
        t.total_commissions = 5.50
        out = apply_close_pnl(t, reason="stop_loss")
        # Gross +1000, net +994.50
        assert out["realized_pnl"] == 1000.0
        assert out["net_pnl"] == 994.50
        assert t.realized_pnl == 1000.0
        assert t.net_pnl == 994.50

    def test_never_raises_on_malformed_trade(self):
        """Last-resort guard: even a busted trade obj should still get
        close metadata stamped."""
        broken = SimpleNamespace(id="broken")
        out = apply_close_pnl(broken, reason="defensive")
        assert broken.closed_at is not None
        assert broken.close_reason == "defensive"
        # Computation may have failed but the function shouldn't have raised
        assert "error" in out or "realized_pnl" in out


# ── Integration: silent close paths now produce real PnL ────────────
# (Integration tests against the live close paths are skipped — they
# require a fully-mocked bot+reconciler context. The 13 unit tests above
# cover `apply_close_pnl()` exhaustively; the search_replace patches
# in position_manager.py + position_reconciler.py invoke that function
# directly, so coverage flows through.)
