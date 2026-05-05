"""
test_share_drift_reconciler_v19_34_15b.py — share-count drift reconciler.

Pins v19.34.15b operator-caught UPS drift fix (IB had 5,304 long, bot
tracked only 425 — 4,879 naked unbracketed shares from
`[REJECTED: Bracket unknown]` parent-fill race).

Three cases from operator approval 2026-05-06:
  1. EXCESS    (IB > bot)  → spawn `reconciled_excess_slice` BotTrade
  2. PARTIAL   (IB < bot, IB > 0)  → shrink remaining_shares pro-rata
  3. ZERO      (IB == 0, bot > 0)  → close bot_trade external_close_v19_34_15b
"""
import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _make_reconciler_with_db():
    from services.position_reconciler import PositionReconciler
    db = MagicMock()
    coll = MagicMock()
    coll.create_index = MagicMock()
    coll.insert_one = MagicMock()
    db.__getitem__.return_value = coll
    return PositionReconciler(db), db


def _make_open_trade(*, sym, direction, remaining, trade_id="t-mock"):
    from services.trading_bot_service import TradeDirection, TradeStatus
    t = MagicMock()
    t.id = trade_id
    t.symbol = sym
    t.direction = TradeDirection.LONG if direction == "long" else TradeDirection.SHORT
    t.remaining_shares = remaining
    t.status = TradeStatus.OPEN
    t.notes = ""
    t.closed_at = None
    t.close_reason = None
    return t


def _make_bot(*, open_trades, ib_positions, ib_quotes=None):
    from services.trading_bot_service import RiskParameters
    bot = MagicMock()
    bot._open_trades = {t.id: t for t in open_trades}
    bot.risk_params = RiskParameters()
    bot._save_trade = AsyncMock()

    # Patch the routers.ib globals via the import inside method.
    import routers.ib as ib_mod
    ib_mod._pushed_ib_data["positions"] = ib_positions
    ib_mod._pushed_ib_data["quotes"] = ib_quotes or {}

    # is_pusher_connected → True
    return bot


# ─── Case 1: EXCESS (IB > bot) ────────────────────────────────────

class TestExcessSlice:

    @pytest.mark.asyncio
    async def test_ups_class_drift_spawns_excess_slice(self):
        """Operator's exact UPS scenario: IB 5,304 long, bot 425.
        Should spawn a new BotTrade for the +4,879 excess."""
        recon, db = _make_reconciler_with_db()
        bot_t = _make_open_trade(sym="UPS", direction="long",
                                 remaining=425, trade_id="t-ups-orig")
        bot = _make_bot(
            open_trades=[bot_t],
            ib_positions=[{
                "symbol": "UPS", "position": 5304,
                "avgCost": 97.24, "marketPrice": 97.30,
            }],
            ib_quotes={"UPS": {"last": 97.30}},
        )
        with patch("routers.ib.is_pusher_connected", return_value=True):
            with patch("services.sentcom_service.emit_stream_event",
                       new=AsyncMock(), create=True):
                result = await recon.reconcile_share_drift(bot)

        assert result["success"] is True
        # 1 detected + 1 resolved + 0 errors
        assert len(result["drifts_detected"]) == 1
        assert len(result["drifts_resolved"]) == 1
        assert len(result["errors"]) == 0
        d = result["drifts_resolved"][0]
        assert d["symbol"] == "UPS"
        assert d["kind"] == "excess_unbracketed"
        assert d["drift_shares"] == 4879
        assert d["new_trade_id"]
        # New trade was inserted into _open_trades
        assert d["new_trade_id"] in bot._open_trades
        new_trade = bot._open_trades[d["new_trade_id"]]
        assert new_trade.symbol == "UPS"
        assert new_trade.remaining_shares == 4879
        assert new_trade.original_shares == 4879
        assert new_trade.entered_by == "reconciled_excess_v19_34_15b"
        assert new_trade.synthetic_source == "share_drift_excess"
        # Stop / target are sane (long: stop below price, target above)
        assert new_trade.stop_price < 97.30 < new_trade.target_prices[0]
        # Original trade was UNTOUCHED
        assert bot_t.remaining_shares == 425

    @pytest.mark.asyncio
    async def test_excess_short_direction_correct_anchor(self):
        recon, _ = _make_reconciler_with_db()
        # Bot tracks 50 short, IB has 200 short (excess 150 short more).
        bot_t = _make_open_trade(sym="MELI", direction="short", remaining=50)
        bot = _make_bot(
            open_trades=[bot_t],
            ib_positions=[{
                "symbol": "MELI", "position": -200,
                "avgCost": 1800.0, "marketPrice": 1810.0,
            }],
            ib_quotes={"MELI": {"last": 1810.0}},
        )
        with patch("routers.ib.is_pusher_connected", return_value=True):
            with patch("services.sentcom_service.emit_stream_event",
                       new=AsyncMock(), create=True):
                result = await recon.reconcile_share_drift(bot)
        d = result["drifts_resolved"][0]
        new_trade = bot._open_trades[d["new_trade_id"]]
        # Short: stop above price, target below
        assert new_trade.stop_price > 1810.0 > new_trade.target_prices[0]
        assert new_trade.remaining_shares == 150
        from services.trading_bot_service import TradeDirection
        assert new_trade.direction == TradeDirection.SHORT


# ─── Case 2: PARTIAL (IB < bot, IB > 0) ───────────────────────────

class TestPartialClose:

    @pytest.mark.asyncio
    async def test_partial_external_close_shrinks_tracking(self):
        recon, _ = _make_reconciler_with_db()
        # Bot tracks 100 long, IB has 50 long (operator partial-closed externally).
        bot_t = _make_open_trade(sym="AAPL", direction="long", remaining=100)
        bot = _make_bot(
            open_trades=[bot_t],
            ib_positions=[{
                "symbol": "AAPL", "position": 50,
                "avgCost": 145.0, "marketPrice": 146.0,
            }],
        )
        with patch("routers.ib.is_pusher_connected", return_value=True):
            with patch("services.sentcom_service.emit_stream_event",
                       new=AsyncMock(), create=True):
                result = await recon.reconcile_share_drift(bot)

        d = result["drifts_resolved"][0]
        assert d["kind"] == "partial_external_close"
        assert d["drift_shares"] == -50
        # remaining_shares shrunk
        assert bot_t.remaining_shares == 50
        # Trade still OPEN, not closed
        from services.trading_bot_service import TradeStatus
        assert bot_t.status == TradeStatus.OPEN
        # Notes updated
        assert "v19.34.15b" in bot_t.notes
        assert "100→50" in bot_t.notes


# ─── Case 3: ZERO (IB == 0, bot > 0) ──────────────────────────────

class TestZeroExternalClose:

    @pytest.mark.asyncio
    async def test_zero_at_ib_closes_bot_trade(self):
        """The operator's UPS phantom case: IB has 0, bot still tracks 425."""
        recon, _ = _make_reconciler_with_db()
        bot_t = _make_open_trade(sym="UPS", direction="long",
                                 remaining=425, trade_id="t-ups-phantom")
        bot = _make_bot(
            open_trades=[bot_t],
            ib_positions=[],  # nothing for UPS
        )
        with patch("routers.ib.is_pusher_connected", return_value=True):
            with patch("services.sentcom_service.emit_stream_event",
                       new=AsyncMock(), create=True):
                result = await recon.reconcile_share_drift(bot)

        d = result["drifts_resolved"][0]
        assert d["kind"] == "zero_external_close"
        assert d["drift_shares"] == -425
        # Trade closed
        from services.trading_bot_service import TradeStatus
        assert bot_t.status == TradeStatus.CLOSED
        assert bot_t.close_reason == "external_close_v19_34_15b"
        assert bot_t.remaining_shares == 0
        # Removed from _open_trades
        assert "t-ups-phantom" not in bot._open_trades


# ─── Threshold + auto-resolve gate ─────────────────────────────────

class TestThresholdAndDryRun:

    @pytest.mark.asyncio
    async def test_drift_within_threshold_skipped(self):
        recon, _ = _make_reconciler_with_db()
        bot_t = _make_open_trade(sym="AAPL", direction="long", remaining=100)
        bot = _make_bot(
            open_trades=[bot_t],
            ib_positions=[{
                "symbol": "AAPL", "position": 101,  # +1 drift, equals threshold
                "avgCost": 145.0, "marketPrice": 146.0,
            }],
        )
        with patch("routers.ib.is_pusher_connected", return_value=True):
            with patch("services.sentcom_service.emit_stream_event",
                       new=AsyncMock(), create=True):
                result = await recon.reconcile_share_drift(bot, drift_threshold=1)
        # |drift| == threshold → skip silently (in_sync)
        assert len(result["drifts_detected"]) == 0
        assert len(result["drifts_resolved"]) == 0

    @pytest.mark.asyncio
    async def test_dry_run_detects_but_does_not_mutate(self):
        recon, _ = _make_reconciler_with_db()
        bot_t = _make_open_trade(sym="UPS", direction="long",
                                 remaining=425, trade_id="t-x")
        bot = _make_bot(
            open_trades=[bot_t],
            ib_positions=[{"symbol": "UPS", "position": 5304,
                           "avgCost": 97.24, "marketPrice": 97.30}],
            ib_quotes={"UPS": {"last": 97.30}},
        )
        with patch("routers.ib.is_pusher_connected", return_value=True):
            with patch("services.sentcom_service.emit_stream_event",
                       new=AsyncMock(), create=True):
                result = await recon.reconcile_share_drift(
                    bot, auto_resolve=False,
                )
        # Detected but NOT resolved
        assert len(result["drifts_detected"]) == 1
        assert len(result["drifts_resolved"]) == 0
        # bot._open_trades unchanged
        assert len(bot._open_trades) == 1
        assert bot_t.remaining_shares == 425


# ─── In-sync case ──────────────────────────────────────────────────

class TestInSync:

    @pytest.mark.asyncio
    async def test_no_drifts_when_perfectly_aligned(self):
        recon, _ = _make_reconciler_with_db()
        bot_t = _make_open_trade(sym="FDX", direction="long", remaining=256)
        bot = _make_bot(
            open_trades=[bot_t],
            ib_positions=[{"symbol": "FDX", "position": 256,
                           "avgCost": 360.0, "marketPrice": 360.04}],
        )
        with patch("routers.ib.is_pusher_connected", return_value=True):
            with patch("services.sentcom_service.emit_stream_event",
                       new=AsyncMock(), create=True):
                result = await recon.reconcile_share_drift(bot)
        assert result["success"] is True
        assert len(result["drifts_detected"]) == 0
        assert len(result["drifts_resolved"]) == 0
