"""
test_drift_phantom_close_guard_v19_34_52.py — pins the v19.34.52 fix
that prevents the share-drift reconciler from phantom-closing real
positions when pusher's snapshot lags entry fills.

Bug timeline (2026-05-08 open):
  9:30:36 — bot evaluates MA squeeze SHORT, fires entry.
  9:31:25 — pusher's `_pushed_ib_data["positions"]` hasn't picked up
            the fill yet, ib_q for MA == 0.
            position_reconciler.reconcile_share_drift hits Case 3:
              `if abs(ib_q) < 0.01: _close_drift_trades_zero(...)`
            Bot's MA trade is marked `external_close_v19_34_15b`.
            But MA WAS active at IB.
  9:31:26 — bot's `pending_trade_exists` gate releases.
  9:33:46 — bot fires MA short AGAIN (no protection from pending check).
  9:34:55 — same loop closes it again. Repeat for EWY, RKT.
  Damage: GOOG 116L, COIN 626L, AAPL 1L phantom-closed locally while
          alive at IB; MA/EWY/RKT loop produced -$1,461 realized P&L.

The v19.34.52 fix gates Case 3 (zero_external_close) and Case 2
(partial_external_close) behind `_ib_qty_authoritative()` which:
  1. Reads pusher's signed qty for the symbol.
  2. Reads direct IB clientId=11 signed qty for the symbol.
  3. Returns confidence="high" only if both agree within 0.5sh AND
     direct returned a non-empty positions list.
  4. Otherwise returns confidence="unreliable" → reconciler SKIPs
     the drift (logs to report.skipped) and waits for next cycle.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _make_open_trade(sym, *, direction="long", remaining=100, trade_id="t1"):
    from services.trading_bot_service import TradeDirection, TradeStatus
    t = MagicMock()
    t.id = trade_id
    t.symbol = sym
    t.status = TradeStatus.OPEN
    t.direction = TradeDirection.LONG if direction == "long" else TradeDirection.SHORT
    t.remaining_shares = remaining
    t.original_shares = remaining
    t.shares = remaining
    t.fill_price = 100.0
    t.entered_by = "bot_fired"
    t.notes = ""
    t.target_prices = []
    return t


def _make_bot(open_trades):
    from services.trading_bot_service import RiskParameters
    bot = MagicMock()
    bot._open_trades = {t.id: t for t in open_trades}
    bot._save_trade = MagicMock()
    bot.risk_params = RiskParameters()
    return bot


def _patch_pusher(positions):
    import routers.ib as ib_mod
    ib_mod._pushed_ib_data["positions"] = positions
    ib_mod._pushed_ib_data["quotes"] = {}


def _patch_direct(positions, *, available=True, connected=True, raise_on_get=None):
    """Patch services.ib_direct_service.get_ib_direct_service."""
    svc = MagicMock()
    svc.is_available.return_value = available
    svc.is_connected.return_value = connected
    if raise_on_get is not None:
        svc.get_positions = AsyncMock(side_effect=raise_on_get)
    else:
        svc.get_positions = AsyncMock(return_value=positions)
    return patch(
        "services.ib_direct_service.get_ib_direct_service",
        return_value=svc,
    )


class TestDriftPhantomCloseGuard:

    @pytest.mark.asyncio
    async def test_pusher_says_zero_but_direct_disagrees_skips(self):
        """THE BUG: pusher lags fill, ib_q=0, but direct IB shows the
        position is real. v19.34.52 must SKIP, not close."""
        from services.position_reconciler import PositionReconciler
        live = _make_open_trade("MA", direction="short", remaining=27, trade_id="ma1")
        recon = PositionReconciler(db=MagicMock())
        bot = _make_bot([live])
        _patch_pusher([])  # pusher hasn't seen the fill yet

        with patch("routers.ib.is_pusher_connected", return_value=True), \
             _patch_direct([
                 {"symbol": "MA", "position": -27, "avgCost": 498.93}
             ]):
            result = await recon.reconcile_share_drift(bot, auto_resolve=True)

        # Trade must NOT be closed.
        from services.trading_bot_service import TradeStatus
        assert live.status == TradeStatus.OPEN
        assert "ma1" in bot._open_trades
        # Drift must be reported as skipped, not resolved.
        skipped_kinds = [s.get("kind") for s in result.get("skipped", [])]
        # Either reported as the new v19.34.52 skip OR no drift at all
        # (since after v19.34.52, ib_q gets re-read from direct so MA
        # won't trigger the case in the first place — also acceptable).
        # Hard assert: it was NOT phantom-closed.
        resolved_kinds = [r.get("kind") for r in result.get("drifts_resolved", [])]
        assert "zero_external_close" not in resolved_kinds, (
            f"v19.34.52 must NOT close MA when direct shows it active. "
            f"Resolved kinds: {resolved_kinds}, Skipped: {result.get('skipped')}"
        )

    @pytest.mark.asyncio
    async def test_pusher_and_direct_both_zero_proceeds_to_close(self):
        """Legit external close: both sources agree on 0. v19.34.52
        allows the close to proceed."""
        from services.position_reconciler import PositionReconciler
        live = _make_open_trade("MA", direction="short", remaining=27, trade_id="ma1")
        recon = PositionReconciler(db=MagicMock())
        bot = _make_bot([live])
        _patch_pusher([])  # zero at pusher

        # Direct shows non-empty list (e.g. some other symbols) but no MA.
        # That's positive confirmation MA truly flat at IB.
        with patch("routers.ib.is_pusher_connected", return_value=True), \
             _patch_direct([{"symbol": "AAPL", "position": 1}]):
            result = await recon.reconcile_share_drift(bot, auto_resolve=True)

        # Trade SHOULD be closed (legitimate external close).
        from services.trading_bot_service import TradeStatus
        assert live.status == TradeStatus.CLOSED
        assert "ma1" not in bot._open_trades
        resolved_kinds = [r.get("kind") for r in result.get("drifts_resolved", [])]
        assert "zero_external_close" in resolved_kinds

    @pytest.mark.asyncio
    async def test_direct_disconnected_skips_close(self):
        """Direct IB unavailable — refuse to act on pusher alone."""
        from services.position_reconciler import PositionReconciler
        live = _make_open_trade("MA", direction="short", remaining=27, trade_id="ma1")
        recon = PositionReconciler(db=MagicMock())
        bot = _make_bot([live])
        _patch_pusher([])

        # Direct returns False on is_connected.
        with patch("routers.ib.is_pusher_connected", return_value=True), \
             _patch_direct([], connected=False):
            result = await recon.reconcile_share_drift(bot, auto_resolve=True)

        from services.trading_bot_service import TradeStatus
        assert live.status == TradeStatus.OPEN
        assert "ma1" in bot._open_trades
        resolved_kinds = [r.get("kind") for r in result.get("drifts_resolved", [])]
        assert "zero_external_close" not in resolved_kinds

    @pytest.mark.asyncio
    async def test_direct_returns_empty_list_skips_close(self):
        """Direct returned [] — could mean mid-update, not truly flat."""
        from services.position_reconciler import PositionReconciler
        live = _make_open_trade("MA", direction="short", remaining=27, trade_id="ma1")
        recon = PositionReconciler(db=MagicMock())
        bot = _make_bot([live])
        _patch_pusher([])

        with patch("routers.ib.is_pusher_connected", return_value=True), \
             _patch_direct([]):
            result = await recon.reconcile_share_drift(bot, auto_resolve=True)

        from services.trading_bot_service import TradeStatus
        assert live.status == TradeStatus.OPEN
        resolved_kinds = [r.get("kind") for r in result.get("drifts_resolved", [])]
        assert "zero_external_close" not in resolved_kinds

    @pytest.mark.asyncio
    async def test_pusher_partial_but_direct_full_skips_shrink(self):
        """Pusher shows fewer shares than bot expects (mid-fill lag),
        but direct shows full position. v19.34.52 must SKIP partial-shrink."""
        from services.position_reconciler import PositionReconciler
        live = _make_open_trade("GOOG", direction="long", remaining=116, trade_id="g1")
        recon = PositionReconciler(db=MagicMock())
        bot = _make_bot([live])
        # Pusher only sees 50 shares (partial)
        _patch_pusher([{"symbol": "GOOG", "position": 50, "avgCost": 394.80}])

        # Direct sees the full 116
        with patch("routers.ib.is_pusher_connected", return_value=True), \
             _patch_direct([
                 {"symbol": "GOOG", "position": 116, "avgCost": 394.80}
             ]):
            result = await recon.reconcile_share_drift(bot, auto_resolve=True)

        # Trade should NOT be shrunk — direct says it's still 116.
        # (After v19.34.52, ib_q gets re-read from direct = 116, so no
        # drift exists at all between bot=116 and direct=116.)
        from services.trading_bot_service import TradeStatus
        assert live.status == TradeStatus.OPEN
        assert live.remaining_shares == 116
        resolved_kinds = [r.get("kind") for r in result.get("drifts_resolved", [])]
        assert "partial_external_close" not in resolved_kinds


class TestIbQtyAuthoritativeHelper:
    """Direct unit coverage of the new helper."""

    @pytest.mark.asyncio
    async def test_high_confidence_when_sources_agree(self):
        from services.position_reconciler import PositionReconciler
        recon = PositionReconciler(db=MagicMock())
        _patch_pusher([{"symbol": "AAPL", "position": 100}])

        with patch("routers.ib.is_pusher_connected", return_value=True), \
             _patch_direct([{"symbol": "AAPL", "position": 100}]):
            qty, conf, reason = await recon._ib_qty_authoritative("AAPL")
        assert conf == "high"
        assert qty == 100

    @pytest.mark.asyncio
    async def test_unreliable_when_sources_disagree(self):
        from services.position_reconciler import PositionReconciler
        recon = PositionReconciler(db=MagicMock())
        _patch_pusher([{"symbol": "AAPL", "position": 0}])

        with patch("routers.ib.is_pusher_connected", return_value=True), \
             _patch_direct([{"symbol": "AAPL", "position": 100}]):
            qty, conf, reason = await recon._ib_qty_authoritative("AAPL")
        assert conf == "unreliable"
        assert "disagree" in reason

    @pytest.mark.asyncio
    async def test_unreliable_when_direct_disconnected(self):
        from services.position_reconciler import PositionReconciler
        recon = PositionReconciler(db=MagicMock())
        _patch_pusher([])
        with patch("routers.ib.is_pusher_connected", return_value=True), \
             _patch_direct([], connected=False):
            qty, conf, reason = await recon._ib_qty_authoritative("AAPL")
        assert conf == "unreliable"
        assert reason == "ib_direct_disconnected"

    @pytest.mark.asyncio
    async def test_unreliable_when_direct_returns_empty(self):
        from services.position_reconciler import PositionReconciler
        recon = PositionReconciler(db=MagicMock())
        _patch_pusher([])
        with patch("routers.ib.is_pusher_connected", return_value=True), \
             _patch_direct([]):
            qty, conf, reason = await recon._ib_qty_authoritative("AAPL")
        assert conf == "unreliable"
        assert reason == "ib_direct_returned_empty_positions"
