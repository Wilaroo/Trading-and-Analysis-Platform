"""
test_bot_q_zero_side_v19_34_50.py — pins the v19.34.50 fix for the
`bot_q` zero-side detection blind-spot.

Bug class: bot tracks the symbol with bot_q (signed sum of remaining
shares) ≈ 0, but `len(zombies) == 0` so the v19.34.19 zombie branch
does not fire. The directional Case 1/2/3 branches in
`reconcile_share_drift` all require bot_q to be strictly long or
short, so the drift fell through to `unclassified` and the IB
inventory stayed silently unmanaged.

Two production scenarios this can hit:
  A) Paired hedge: bot has LONG 100 + SHORT 100 with both
     `remaining_shares > 0` → signed sum cancels to 0.
  B) Tracked-but-zero edge: bot has a trade with float remaining
     near 0 (e.g., 0.5 sh from a pathological partial close) where
     `int(abs(rs)) == 0` would tag as zombie, but the bot lifecycle
     persisted a non-int field that doesn't trip the zombie filter.

In both cases, IB has real qty (e.g., 50 shares) that nobody is
managing.

The v19.34.50 fix detects `abs(bot_q) < 0.01 AND abs(ib_q) >= 1`
AFTER the zombie branch and routes to `_spawn_excess_slice` so the
bot claims the IB inventory under a bracketed reconciled-excess
slice. The existing tracked bot_trades are LEFT ALONE — they may be
legitimate paired hedges; we only adopt the unmanaged IB shares.
"""
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _make_live_trade(sym, *, direction, remaining, trade_id, fill_price=100.0):
    """Trade with rs > 0 so it does NOT count as zombie."""
    from services.trading_bot_service import TradeDirection, TradeStatus
    t = MagicMock()
    t.id = trade_id
    t.symbol = sym
    t.status = TradeStatus.OPEN
    t.direction = TradeDirection.LONG if direction == "long" else TradeDirection.SHORT
    t.remaining_shares = remaining
    t.original_shares = remaining
    t.shares = remaining
    t.fill_price = fill_price
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
    import routers.ib as ib_mod
    ib_mod._pushed_ib_data["positions"] = positions
    ib_mod._pushed_ib_data["quotes"] = quotes or {}


class TestBotQZeroSideDetection:

    @pytest.mark.asyncio
    async def test_paired_long_short_with_ib_excess_detected(self):
        """Bot has LONG 100 + SHORT 100 of FDX (both rs>0, bot_q=0).
        IB shows 50 long. Old code: unclassified → silent drop.
        v19.34.50: detect as zero_side_external_inventory."""
        from services.position_reconciler import PositionReconciler
        long_t = _make_live_trade("FDX", direction="long", remaining=100, trade_id="L1")
        short_t = _make_live_trade("FDX", direction="short", remaining=100, trade_id="S1")
        recon = PositionReconciler(db=MagicMock())
        bot = _make_bot(open_trades=[long_t, short_t])
        _patch_ib(
            [{"symbol": "FDX", "position": 50, "avgCost": 360.0, "marketPrice": 365.0}],
            {"FDX": {"last": 365.0}},
        )
        with patch("routers.ib.is_pusher_connected", return_value=True):
            with patch("services.sentcom_service.emit_stream_event",
                       new=AsyncMock(), create=True):
                result = await recon.reconcile_share_drift(
                    bot, auto_resolve=False,
                )
        detected = result["drifts_detected"]
        assert len(detected) == 1, (
            f"expected 1 drift detected, got {len(detected)}: {detected}"
        )
        d = detected[0]
        assert d["symbol"] == "FDX"
        assert d["kind"] == "zero_side_external_inventory"
        assert d["bot_qty"] == 0
        assert d["ib_qty"] == 50
        assert d["tracked_trade_count"] == 2

    @pytest.mark.asyncio
    async def test_paired_long_short_full_heal_spawns_slice(self):
        """auto_resolve=True: spawn excess slice claiming the 50 IB long.
        Original LONG 100 + SHORT 100 trades stay open, untouched."""
        from services.position_reconciler import PositionReconciler
        from services.trading_bot_service import TradeStatus
        long_t = _make_live_trade("FDX", direction="long", remaining=100, trade_id="L1")
        short_t = _make_live_trade("FDX", direction="short", remaining=100, trade_id="S1")
        recon = PositionReconciler(db=MagicMock())
        recon._spawn_excess_slice = AsyncMock(return_value="new-zero-side-slice")
        recon._persist_drift_event = AsyncMock()
        bot = _make_bot(open_trades=[long_t, short_t])
        _patch_ib(
            [{"symbol": "FDX", "position": 50, "avgCost": 360.0, "marketPrice": 365.0}],
            {"FDX": {"last": 365.0}},
        )
        with patch("routers.ib.is_pusher_connected", return_value=True):
            with patch("services.sentcom_service.emit_stream_event",
                       new=AsyncMock(), create=True):
                result = await recon.reconcile_share_drift(
                    bot, auto_resolve=True,
                )
        resolved = result["drifts_resolved"]
        assert len(resolved) == 1
        d = resolved[0]
        assert d["kind"] == "zero_side_external_inventory"
        assert d["new_trade_id"] == "new-zero-side-slice"
        # Existing paired trades MUST stay open and untouched.
        assert long_t.status == TradeStatus.OPEN
        assert short_t.status == TradeStatus.OPEN
        assert "L1" in bot._open_trades
        assert "S1" in bot._open_trades
        # Spawn called with bot_q≈0 and ib_q=50.
        recon._spawn_excess_slice.assert_called_once()
        kwargs = recon._spawn_excess_slice.call_args.kwargs
        assert abs(kwargs["bot_q"]) < 0.01
        # `_spawn_excess_slice(self, bot, sym, ib_qty_signed, ...)` —
        # ib_q is passed positionally as the 3rd arg.
        assert recon._spawn_excess_slice.call_args.args[2] == 50
        # Persist was called at least once with the resolved record.
        # (reconcile_share_drift also calls _persist_drift_event at the
        # end with the entire report, so call_count is typically 2.)
        assert recon._persist_drift_event.call_count >= 1

    @pytest.mark.asyncio
    async def test_paired_short_excess_negative_ib_inventory(self):
        """Symmetric: paired hedge, IB has -75 (short) inventory.
        Should still detect + spawn (excess_signed = -75 - 0 = -75)."""
        from services.position_reconciler import PositionReconciler
        long_t = _make_live_trade("UPS", direction="long", remaining=200, trade_id="L1")
        short_t = _make_live_trade("UPS", direction="short", remaining=200, trade_id="S1")
        recon = PositionReconciler(db=MagicMock())
        recon._spawn_excess_slice = AsyncMock(return_value="ups-zero-side")
        recon._persist_drift_event = AsyncMock()
        bot = _make_bot(open_trades=[long_t, short_t])
        _patch_ib(
            [{"symbol": "UPS", "position": -75, "avgCost": 98.0, "marketPrice": 99.0}],
            {"UPS": {"last": 99.0}},
        )
        with patch("routers.ib.is_pusher_connected", return_value=True):
            with patch("services.sentcom_service.emit_stream_event",
                       new=AsyncMock(), create=True):
                result = await recon.reconcile_share_drift(
                    bot, auto_resolve=True,
                )
        assert len(result["drifts_resolved"]) == 1
        d = result["drifts_resolved"][0]
        assert d["kind"] == "zero_side_external_inventory"
        assert d["ib_qty"] == -75

    @pytest.mark.asyncio
    async def test_zombie_branch_still_wins_when_zombies_present(self):
        """Regression: when bot_q≈0 AND zombies>0 AND ib_q>=1, the
        v19.34.19 zombie branch must still fire (not zero-side)."""
        from services.position_reconciler import PositionReconciler
        from services.trading_bot_service import TradeDirection, TradeStatus
        z = MagicMock()
        z.id = "zombie-x"
        z.symbol = "DDOG"
        z.status = TradeStatus.OPEN
        z.direction = TradeDirection.LONG
        z.remaining_shares = 0  # zombie
        z.original_shares = 100
        z.shares = 100
        z.fill_price = 120.0
        z.notes = ""
        z.target_prices = []
        recon = PositionReconciler(db=MagicMock())
        recon._spawn_excess_slice = AsyncMock(return_value="zombie-slice")
        bot = _make_bot(open_trades=[z])
        _patch_ib(
            [{"symbol": "DDOG", "position": 100, "avgCost": 120.0, "marketPrice": 122.0}],
            {"DDOG": {"last": 122.0}},
        )
        with patch("routers.ib.is_pusher_connected", return_value=True):
            with patch("services.sentcom_service.emit_stream_event",
                       new=AsyncMock(), create=True):
                result = await recon.reconcile_share_drift(
                    bot, auto_resolve=True,
                )
        # Must take the zombie path, NOT zero_side.
        assert len(result["drifts_resolved"]) == 1
        assert result["drifts_resolved"][0]["kind"] == "zombie_trade_drift"

    @pytest.mark.asyncio
    async def test_pure_orphan_still_defers_to_orphan_reconciler(self):
        """Regression: when sym not in bot_qty_by_sym at all (no tracked
        trades), zero-side path must NOT fire — defer to orphan."""
        from services.position_reconciler import PositionReconciler
        recon = PositionReconciler(db=MagicMock())
        bot = _make_bot(open_trades=[])
        _patch_ib(
            [{"symbol": "GOOG", "position": 50, "avgCost": 145.0, "marketPrice": 146.0}],
            {"GOOG": {"last": 146.0}},
        )
        with patch("routers.ib.is_pusher_connected", return_value=True):
            with patch("services.sentcom_service.emit_stream_event",
                       new=AsyncMock(), create=True):
                result = await recon.reconcile_share_drift(bot, auto_resolve=True)
        skipped = result["skipped"]
        assert len(skipped) == 1
        assert skipped[0]["reason"] == "ib_only_use_orphan_reconciler"
        # No zero-side detection should fire.
        zero_sides = [
            d for d in result["drifts_detected"]
            if d.get("kind") == "zero_side_external_inventory"
        ]
        assert len(zero_sides) == 0

    @pytest.mark.asyncio
    async def test_directional_excess_unchanged(self):
        """Regression: bot=276 long, IB=369 long → still excess_unbracketed
        (not zero_side). bot_q=276, not ≈0."""
        from services.position_reconciler import PositionReconciler
        live = _make_live_trade("FDX", direction="long", remaining=276, trade_id="live-1")
        recon = PositionReconciler(db=MagicMock())
        recon._spawn_excess_slice = AsyncMock(return_value="excess-slice")
        bot = _make_bot(open_trades=[live])
        _patch_ib(
            [{"symbol": "FDX", "position": 369, "avgCost": 360.0, "marketPrice": 365.0}],
            {"FDX": {"last": 365.0}},
        )
        with patch("routers.ib.is_pusher_connected", return_value=True):
            with patch("services.sentcom_service.emit_stream_event",
                       new=AsyncMock(), create=True):
                result = await recon.reconcile_share_drift(bot, auto_resolve=True)
        assert len(result["drifts_resolved"]) == 1
        assert result["drifts_resolved"][0]["kind"] == "excess_unbracketed"

    @pytest.mark.asyncio
    async def test_bot_q_zero_but_ib_zero_no_drift(self):
        """Edge: bot_q=0, ib_q=0 → drift=0 → early skip, no detection."""
        from services.position_reconciler import PositionReconciler
        long_t = _make_live_trade("AMZN", direction="long", remaining=50, trade_id="L1")
        short_t = _make_live_trade("AMZN", direction="short", remaining=50, trade_id="S1")
        recon = PositionReconciler(db=MagicMock())
        bot = _make_bot(open_trades=[long_t, short_t])
        _patch_ib([], {})  # IB has no AMZN position
        with patch("routers.ib.is_pusher_connected", return_value=True):
            with patch("services.sentcom_service.emit_stream_event",
                       new=AsyncMock(), create=True):
                result = await recon.reconcile_share_drift(bot, auto_resolve=True)
        # No drift, no detection.
        assert len(result["drifts_detected"]) == 0
        assert len(result["drifts_resolved"]) == 0
