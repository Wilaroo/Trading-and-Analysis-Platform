"""
test_zombie_drift_v19_34_19.py — pins the v19.34.19 fix for the
v19.34.15b blind spot the operator caught 2026-05-06.

Bug class: bot has OPEN trades for a symbol with `remaining_shares=0`
(lifecycle bug — partial-close path didn't flip status). Bot_q sums
to 0 while IB still holds the original parent qty. v19.34.15b's
`if abs(bot_q) < 0.01: skip` deferred to orphan reconciler, which
ignores tracked symbols. Net: 1592 unmanaged shares accumulated.
"""
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _make_zombie_trade(sym, original=276, trade_id="t-zombie", direction="long"):
    from services.trading_bot_service import TradeDirection, TradeStatus
    t = MagicMock()
    t.id = trade_id
    t.symbol = sym
    t.status = TradeStatus.OPEN
    t.direction = TradeDirection.LONG if direction == "long" else TradeDirection.SHORT
    t.remaining_shares = 0  # <-- the zombie marker
    t.original_shares = original
    t.shares = original
    t.fill_price = 100.0
    t.entered_by = "bot_fired"
    t.trade_style = "trade_2_hold"
    t.notes = ""
    t.target_prices = []
    return t


def _make_bot(open_trades=None):
    from services.trading_bot_service import RiskParameters
    bot = MagicMock()
    bot._open_trades = {t.id: t for t in (open_trades or [])}
    bot._save_trade = MagicMock()
    bot.risk_params = RiskParameters()
    return bot


def _patch_ib(positions, quotes=None):
    """Set the routers.ib module globals exactly as production does."""
    import routers.ib as ib_mod
    ib_mod._pushed_ib_data["positions"] = positions
    ib_mod._pushed_ib_data["quotes"] = quotes or {}


class TestZombieDriftDetection:

    @pytest.mark.asyncio
    async def test_zombie_drift_detected_when_remaining_shares_zero(self):
        """Bot has 2 OPEN FDX trades with remaining=0; IB has 369 long.
        Old 15b would skip; v19.34.19 must DETECT."""
        from services.position_reconciler import PositionReconciler
        z1 = _make_zombie_trade("FDX", original=256, trade_id="z-1")
        z2 = _make_zombie_trade("FDX", original=20, trade_id="z-2")
        recon = PositionReconciler(db=MagicMock())
        bot = _make_bot(open_trades=[z1, z2])
        _patch_ib([{"symbol": "FDX", "position": 369, "avgCost": 360.0, "marketPrice": 365.0}],
                  {"FDX": {"last": 365.0}})
        with patch("routers.ib.is_pusher_connected", return_value=True):
            with patch("services.sentcom_service.emit_stream_event",
                       new=AsyncMock(), create=True):
                result = await recon.reconcile_share_drift(
                    bot, zombie_detect_only=True,
                )
        detected = result["drifts_detected"]
        assert len(detected) == 1
        d = detected[0]
        assert d["symbol"] == "FDX"
        assert d["kind"] == "zombie_trade_drift"
        assert d["zombie_count"] == 2
        assert set(d["zombie_trade_ids"]) == {"z-1", "z-2"}
        assert d["ib_qty"] == 369
        assert d["bot_qty"] == 0

    @pytest.mark.asyncio
    async def test_zombie_detect_only_does_not_spawn_or_close(self):
        """zombie_detect_only=True: detect but no slice spawn, no close."""
        from services.position_reconciler import PositionReconciler
        z = _make_zombie_trade("UPS", original=885, trade_id="z-ups")
        recon = PositionReconciler(db=MagicMock())
        bot = _make_bot(open_trades=[z])
        _patch_ib([{"symbol": "UPS", "position": 1223, "avgCost": 98.0, "marketPrice": 99.0}],
                  {"UPS": {"last": 99.0}})
        with patch("routers.ib.is_pusher_connected", return_value=True):
            with patch("services.sentcom_service.emit_stream_event",
                       new=AsyncMock(), create=True):
                result = await recon.reconcile_share_drift(
                    bot, zombie_detect_only=True, auto_resolve=True,
                )
        # Detected but NOT resolved.
        assert len(result["drifts_detected"]) == 1
        assert len(result["drifts_resolved"]) == 0
        # Zombie still OPEN with original shares unchanged.
        from services.trading_bot_service import TradeStatus
        assert z.status == TradeStatus.OPEN
        assert "z-ups" in bot._open_trades

    @pytest.mark.asyncio
    async def test_zombie_full_heal_spawns_slice_and_closes_zombies(self):
        """auto_resolve=True + zombie_detect_only=False: full heal."""
        from services.position_reconciler import PositionReconciler
        from services.trading_bot_service import TradeStatus
        z1 = _make_zombie_trade("FDX", original=256, trade_id="z-1")
        z2 = _make_zombie_trade("FDX", original=20, trade_id="z-2")
        recon = PositionReconciler(db=MagicMock())
        recon._spawn_excess_slice = AsyncMock(return_value="new-slice-1")
        bot = _make_bot(open_trades=[z1, z2])
        _patch_ib([{"symbol": "FDX", "position": 369, "avgCost": 360.0, "marketPrice": 365.0}],
                  {"FDX": {"last": 365.0}})
        with patch("routers.ib.is_pusher_connected", return_value=True):
            with patch("services.sentcom_service.emit_stream_event",
                       new=AsyncMock(), create=True):
                result = await recon.reconcile_share_drift(
                    bot, zombie_detect_only=False, auto_resolve=True,
                )
        assert len(result["drifts_resolved"]) == 1
        d = result["drifts_resolved"][0]
        assert d["new_trade_id"] == "new-slice-1"
        assert set(d["zombies_closed"]) == {"z-1", "z-2"}
        assert z1.status == TradeStatus.CLOSED
        assert z2.status == TradeStatus.CLOSED
        assert z1.close_reason == "zombie_cleanup_v19_34_19"
        assert "v19.34.19" in z1.notes
        assert "z-1" not in bot._open_trades
        assert "z-2" not in bot._open_trades
        recon._spawn_excess_slice.assert_called_once()
        call_kwargs = recon._spawn_excess_slice.call_args.kwargs
        assert call_kwargs["stop_pct"] == 1.0
        assert call_kwargs["rr"] == 1.0

    @pytest.mark.asyncio
    async def test_orphan_path_still_skips_when_no_bot_trades(self):
        """Pure orphan still defers to reconcile_orphan_positions."""
        from services.position_reconciler import PositionReconciler
        recon = PositionReconciler(db=MagicMock())
        bot = _make_bot(open_trades=[])
        _patch_ib([{"symbol": "GOOG", "position": 50, "avgCost": 145.0, "marketPrice": 146.0}],
                  {"GOOG": {"last": 146.0}})
        with patch("routers.ib.is_pusher_connected", return_value=True):
            with patch("services.sentcom_service.emit_stream_event",
                       new=AsyncMock(), create=True):
                result = await recon.reconcile_share_drift(bot, auto_resolve=True)
        skipped = result["skipped"]
        assert len(skipped) == 1
        assert skipped[0]["reason"] == "ib_only_use_orphan_reconciler"
        assert len(result["drifts_detected"]) == 0

    @pytest.mark.asyncio
    async def test_existing_excess_slice_path_still_works(self):
        """Regression: bot=276, IB=369 → excess +93 (Case 1 unchanged)."""
        from services.position_reconciler import PositionReconciler
        from services.trading_bot_service import TradeDirection, TradeStatus
        live = MagicMock()
        live.id = "live-1"
        live.symbol = "FDX"
        live.status = TradeStatus.OPEN
        live.direction = TradeDirection.LONG
        live.remaining_shares = 276
        live.original_shares = 276
        live.shares = 276
        live.fill_price = 360.0
        live.notes = ""
        live.target_prices = []
        recon = PositionReconciler(db=MagicMock())
        recon._spawn_excess_slice = AsyncMock(return_value="new-slice-X")
        bot = _make_bot(open_trades=[live])
        _patch_ib([{"symbol": "FDX", "position": 369, "avgCost": 360.0, "marketPrice": 365.0}],
                  {"FDX": {"last": 365.0}})
        with patch("routers.ib.is_pusher_connected", return_value=True):
            with patch("services.sentcom_service.emit_stream_event",
                       new=AsyncMock(), create=True):
                result = await recon.reconcile_share_drift(bot, auto_resolve=True)
        d = result["drifts_resolved"][0]
        assert d["kind"] == "excess_unbracketed"
