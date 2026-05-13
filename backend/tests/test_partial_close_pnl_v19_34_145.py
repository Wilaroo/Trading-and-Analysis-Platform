"""v19.34.145 — Live-PnL math uses `remaining_shares`, not `shares`.

Bug found 2026-02-13 from operator's live KMB audit:

    bot.shares=144  bot.remaining_shares=55  ib.position=55

Bot fired squeeze entry of 144 KMB long → target-1 hit peeled 89
shares → 55 remain. The ledger was CORRECT (remaining=55 matches
IB) but `get_our_positions()` was computing
`pnl = (current - entry) * shares` = `(current - entry) * 144`,
overstating unrealized PnL by 89 / 55 ≈ 2.6× and triggering a false
NAKED-position alarm in the audit.

v19.34.145 switches the PnL math in `sentcom_service.py` to use
`remaining_shares` (with `shares` fallback for legacy rows that
never tracked partials).
"""

import pytest


def _live_pnl(*, entry, current, shares, remaining_shares, direction):
    """Mirror of the v19.34.145 inline math in sentcom_service.py
    (bot-row branch). Kept in lockstep with production code via the
    contract test below."""
    live_shares = (
        remaining_shares
        if remaining_shares is not None
        else shares
    )
    try:
        live_shares = abs(int(live_shares))
    except (TypeError, ValueError):
        live_shares = int(abs(shares or 0))
    if direction == "short":
        pnl = (entry - current) * live_shares if entry and current else 0
    else:
        pnl = (current - entry) * live_shares if entry and current else 0
    market_value = abs(live_shares * current) if current else 0
    cost_basis = abs(live_shares * entry) if entry else 0
    return {"pnl": pnl, "market_value": market_value,
            "cost_basis": cost_basis, "live_shares": live_shares}


class TestLivePnLUsesRemainingShares:
    """Classify the KMB scenario directly."""

    def test_kmb_partial_close_pnl_against_remaining(self):
        """144 entered, 89 peeled → remaining=55. PnL must reflect 55."""
        result = _live_pnl(
            entry=135.00, current=137.50,
            shares=144, remaining_shares=55,
            direction="long",
        )
        # (137.50 - 135.00) * 55 = 137.5
        assert result["pnl"] == pytest.approx(137.5, abs=0.01)
        assert result["live_shares"] == 55
        # Market value uses live shares too — cost_basis ditto.
        assert result["market_value"] == pytest.approx(55 * 137.5, abs=0.01)
        assert result["cost_basis"] == pytest.approx(55 * 135.00, abs=0.01)

    def test_kmb_pre_fix_would_overstate(self):
        """Documents the pre-v19.34.145 bug. If we (incorrectly)
        computed PnL against the original 144 shares, we'd get
        (137.50 - 135.00) * 144 = 360.0 — 2.6× the true live PnL."""
        # Same numbers but with `remaining_shares=None` so we fall
        # back to `shares` and reproduce the OLD behavior.
        result = _live_pnl(
            entry=135.00, current=137.50,
            shares=144, remaining_shares=None,
            direction="long",
        )
        assert result["pnl"] == pytest.approx(360.0, abs=0.01)
        assert result["live_shares"] == 144

    def test_onon_partial_close_short_direction(self):
        """ONON from operator's audit: bot entered 235, peeled 176,
        remaining=59. Sanity check via SHORT side."""
        result = _live_pnl(
            entry=38.0, current=37.0,
            shares=235, remaining_shares=59,
            direction="short",
        )
        # SHORT: (entry - current) * live
        # (38 - 37) * 59 = 59
        assert result["pnl"] == pytest.approx(59.0, abs=0.01)
        assert result["live_shares"] == 59

    def test_pre_partial_close_full_position_unaffected(self):
        """If no partial has fired (remaining_shares == shares), the
        math must produce the same answer as the original code."""
        result = _live_pnl(
            entry=100.0, current=105.0,
            shares=100, remaining_shares=100,
            direction="long",
        )
        assert result["pnl"] == pytest.approx(500.0, abs=0.01)
        assert result["live_shares"] == 100

    def test_legacy_row_without_remaining_falls_back_to_shares(self):
        """Pre-partial-tracking trades that emit `shares` but not
        `remaining_shares` must still produce correct PnL."""
        result = _live_pnl(
            entry=50.0, current=51.0,
            shares=200, remaining_shares=None,
            direction="long",
        )
        assert result["pnl"] == pytest.approx(200.0, abs=0.01)
        assert result["live_shares"] == 200

    def test_zero_remaining_yields_zero_pnl(self):
        """Edge: fully closed position (`remaining_shares=0`). PnL
        must be 0 — the row is on its way to becoming a zombie."""
        result = _live_pnl(
            entry=100.0, current=110.0,
            shares=100, remaining_shares=0,
            direction="long",
        )
        assert result["pnl"] == 0
        assert result["live_shares"] == 0

    def test_missing_entry_or_current_yields_zero(self):
        result = _live_pnl(
            entry=0, current=100.0,
            shares=10, remaining_shares=10,
            direction="long",
        )
        assert result["pnl"] == 0

    @pytest.mark.parametrize("entry,current,shares,remaining,direction,expected", [
        (135.00, 137.50, 144, 55, "long", 137.5),       # KMB
        (38.0,   37.0,   235, 59, "short", 59.0),       # ONON
        (100.0,  90.0,   50,  50, "long", -500.0),      # losing long
        (100.0,  110.0,  50,  50, "short", -500.0),     # losing short
        (200.0,  200.0,  10,  10, "long", 0.0),         # flat
    ])
    def test_table(self, entry, current, shares, remaining, direction, expected):
        result = _live_pnl(
            entry=entry, current=current,
            shares=shares, remaining_shares=remaining,
            direction=direction,
        )
        assert result["pnl"] == pytest.approx(expected, abs=0.01)


class TestSentcomServiceContract:
    """Pin the production code to keep using `remaining_shares` (with
    `shares` fallback). If a future refactor reverts the math, this
    fires."""

    def test_get_our_positions_uses_remaining_shares_for_live_pnl(self):
        import inspect
        from services.sentcom_service import get_sentcom_service
        svc = get_sentcom_service()
        src = inspect.getsource(svc.get_our_positions)
        # The v19.34.145 marker is in the production file.
        assert "live_shares" in src
        assert 'trade.get("remaining_shares")' in src
        # The PnL math uses live_shares, not the raw `shares`.
        assert "(entry - current) * live_shares" in src
        assert "(current - entry) * live_shares" in src
