"""
test_open_positions_watchlist_filter_v19_34_6.py — pin the V5 Open
Positions filter that suppresses watchlist-only gameplan rows from the
panel when IB does NOT confirm a matching position.

2026-05-05 v19.34.6 — operator-filed bug from 2026-05-04 EVE:

  > The Open Positions panel was rendering a MELI "DAY 2 short" card
  > from yesterday's after-hours `_rank_carry_forward_setups_for_tomorrow`
  > scanner pass. The bot never actually placed that order — it was a
  > pre-market gameplan watchlist item — but a stale `bot_trades` row
  > with `setup_type='carry_forward_watch'` and `status='open'` had
  > been left behind, so on restart it loaded into `_open_trades` and
  > leaked into Open Positions despite zero IB exposure.

Fix: in `SentComService.get_our_positions`, skip bot-tracked rows
whose `setup_type` is in `_WATCHLIST_ONLY_SETUPS` UNLESS IB confirms a
matching (symbol, direction, qty>0) position. Real bot fills with
non-watchlist setups (ORB, opening_drive, etc.) are unaffected. Real
bot fills WITH watchlist setups but actively confirmed by IB also pass
through (defensive — covers the rare case where the bot DID fire a
day_2_continuation and IB still has the position).

All tests are pure-Python — no IB Gateway, no network, no DB.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _bot_trade_dict(**overrides):
    """Canonical bot-trade dict mimicking TradingBotService.get_open_trades()."""
    base = {
        "id": "trade-meli-day2",
        "symbol": "MELI",
        "direction": "short",
        "shares": 50,
        "fill_price": 1820.10,
        "entry_price": 1820.10,
        "current_price": 1820.10,
        "stop_price": 1840.00,
        "target_prices": [1790.00],
        "status": "open",
        "setup_type": "carry_forward_watch",   # the leaky setup type
        "setup_variant": "short",
        "trade_style": "day",
        "timeframe": "intraday",
        "executed_at": "2026-05-04T20:15:00Z",
        "notes": "DAY 2 short carry-forward (EOD scanner)",
        "quality_score": 60,
        "quality_grade": "B",
        "smb_grade": "B",
        "mfe_pct": 0.0,
        "mae_pct": 0.0,
        "ai_context": {},
        "market_regime": "RISK_OFF",
        "risk_amount": 995.0,
        "risk_reward_ratio": 1.5,
        "potential_reward": 1505.0,
        "remaining_shares": 50,
        "original_shares": 50,
        "regime_score": 5,
        "scan_tier": "intraday",
        "tape_score": 50,
        "entry_context": {
            "scan_tier": "intraday",
            "smb_is_a_plus": False,
            "exit_rule": "trail to today's high",
            "trading_approach": "DAY 2 short",
            "reasoning": ["EOD carry-forward: closed below VWAP +RVOL"],
        },
        "scale_out_config": {"enabled": False, "targets_hit": [], "partial_exits": []},
        "trailing_stop_config": {
            "enabled": False, "mode": "original",
            "current_stop": 1840.00, "high_water_mark": 1820.10,
            "low_water_mark": 1820.10,
        },
    }
    base.update(overrides)
    return base


def _pushed_data(symbol=None, last=None, position_qty=None):
    """Build a fake _pushed_ib_data dict.
    
    - If `position_qty` is None, no IB position exists (pure orphan case).
    - If `position_qty` is non-zero, IB confirms a matching position.
    """
    data = {"connected": True, "quotes": {}, "positions": []}
    if symbol and last is not None:
        data["quotes"][symbol] = {"last": last, "change": 0.0, "change_pct": 0.0}
    if symbol and position_qty is not None:
        data["positions"].append({
            "symbol": symbol,
            "position": position_qty,
            "avgCost": last if last is not None else 0.0,
            "marketPrice": last if last is not None else 0.0,
        })
    return data


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

class TestOpenPositionsWatchlistFilterV19_34_6:

    @pytest.mark.asyncio
    async def test_carry_forward_watch_without_ib_is_suppressed(self):
        """The exact bug: MELI carry_forward_watch row, NO IB position.
        Expectation: row is dropped from Open Positions output."""
        from services.sentcom_service import SentComService

        svc = SentComService.__new__(SentComService)
        bot = MagicMock()
        bot.get_open_trades = MagicMock(return_value=[_bot_trade_dict()])
        svc._get_trading_bot = lambda: bot

        # No IB position for MELI
        with patch.dict(
            "routers.ib._pushed_ib_data",
            _pushed_data(symbol="MELI", last=1815.00, position_qty=None),
            clear=True,
        ):
            positions = await svc.get_our_positions()

        # The carry_forward_watch row MUST be filtered out.
        symbols = [p["symbol"] for p in positions]
        assert "MELI" not in symbols, (
            f"carry_forward_watch row leaked into Open Positions: {positions}"
        )
        assert len(positions) == 0

    @pytest.mark.asyncio
    async def test_day_2_continuation_without_ib_is_suppressed(self):
        """day_2_continuation is also a watchlist-only setup; same rule."""
        from services.sentcom_service import SentComService

        svc = SentComService.__new__(SentComService)
        bot = MagicMock()
        bot.get_open_trades = MagicMock(return_value=[
            _bot_trade_dict(symbol="HOOD", setup_type="day_2_continuation",
                            direction="long", entry_price=72.10,
                            fill_price=72.10, current_price=72.10,
                            stop_price=70.00, target_prices=[75.00]),
        ])
        svc._get_trading_bot = lambda: bot

        with patch.dict(
            "routers.ib._pushed_ib_data",
            _pushed_data(symbol="HOOD", last=72.40, position_qty=None),
            clear=True,
        ):
            positions = await svc.get_our_positions()

        assert all(p["symbol"] != "HOOD" for p in positions)

    @pytest.mark.asyncio
    async def test_approaching_breakout_without_ib_is_suppressed(self):
        """`approaching_*` proximity warnings are also watchlist-only."""
        from services.sentcom_service import SentComService

        svc = SentComService.__new__(SentComService)
        bot = MagicMock()
        bot.get_open_trades = MagicMock(return_value=[
            _bot_trade_dict(symbol="NVDA", setup_type="approaching_breakout",
                            direction="long", entry_price=510.00,
                            fill_price=510.00, current_price=510.00,
                            stop_price=505.00, target_prices=[525.00]),
        ])
        svc._get_trading_bot = lambda: bot

        with patch.dict(
            "routers.ib._pushed_ib_data",
            _pushed_data(symbol="NVDA", last=512.00, position_qty=None),
            clear=True,
        ):
            positions = await svc.get_our_positions()

        assert all(p["symbol"] != "NVDA" for p in positions)

    @pytest.mark.asyncio
    async def test_carry_forward_watch_with_ib_confirmation_is_kept(self):
        """Edge case: bot DID fire a day_2_continuation, IB still has
        position. Row must NOT be suppressed — it's a real exposure."""
        from services.sentcom_service import SentComService

        svc = SentComService.__new__(SentComService)
        bot = MagicMock()
        bot.get_open_trades = MagicMock(return_value=[
            _bot_trade_dict(symbol="MELI", setup_type="carry_forward_watch",
                            direction="short", shares=50,
                            fill_price=1820.10, entry_price=1820.10,
                            current_price=1820.10),
        ])
        svc._get_trading_bot = lambda: bot

        # IB confirms a SHORT position of 50 shares (negative qty)
        with patch.dict(
            "routers.ib._pushed_ib_data",
            _pushed_data(symbol="MELI", last=1815.00, position_qty=-50),
            clear=True,
        ):
            positions = await svc.get_our_positions()

        symbols = [p["symbol"] for p in positions]
        assert "MELI" in symbols, (
            "Confirmed IB short MUST stay in Open Positions even with "
            "watchlist setup_type"
        )

    @pytest.mark.asyncio
    async def test_direction_mismatch_with_ib_still_suppressed(self):
        """Edge case: bot row says LONG carry_forward_watch, IB shows
        SHORT. Direction mismatch → no real confirmation → row dropped."""
        from services.sentcom_service import SentComService

        svc = SentComService.__new__(SentComService)
        bot = MagicMock()
        bot.get_open_trades = MagicMock(return_value=[
            _bot_trade_dict(symbol="MELI", direction="long",
                            setup_type="day_2_continuation",
                            shares=50, entry_price=1820.10,
                            fill_price=1820.10, current_price=1820.10),
        ])
        svc._get_trading_bot = lambda: bot

        # IB shows SHORT position — bot row direction does NOT match
        with patch.dict(
            "routers.ib._pushed_ib_data",
            _pushed_data(symbol="MELI", last=1815.00, position_qty=-50),
            clear=True,
        ):
            positions = await svc.get_our_positions()

        # Bot LONG row must be filtered out (no matching direction).
        # The IB short position WILL emit a separate orphan row, but
        # that's fine — it's a real IB position the operator should see.
        bot_long_rows = [p for p in positions
                         if p["symbol"] == "MELI" and p["direction"] == "long"]
        assert len(bot_long_rows) == 0

    @pytest.mark.asyncio
    async def test_real_setup_without_ib_is_kept(self):
        """Defensive: a non-watchlist setup (ORB / opening_drive) without
        IB confirmation is the `stale_bot` case — must be KEPT so the
        auto-sweep loop can clean it up. Filter must not regress."""
        from services.sentcom_service import SentComService

        svc = SentComService.__new__(SentComService)
        bot = MagicMock()
        bot.get_open_trades = MagicMock(return_value=[
            _bot_trade_dict(symbol="HOOD", setup_type="opening_range_break",
                            direction="long", shares=100,
                            fill_price=73.42, entry_price=73.42,
                            current_price=73.42, stop_price=72.10,
                            target_prices=[76.50]),
        ])
        svc._get_trading_bot = lambda: bot

        with patch.dict(
            "routers.ib._pushed_ib_data",
            _pushed_data(symbol="HOOD", last=73.95, position_qty=None),
            clear=True,
        ):
            positions = await svc.get_our_positions()

        # ORB is a real setup — keep the row even with no IB confirmation.
        # The smart_source classifier downstream will mark it stale_bot
        # and the auto-sweep loop will clean it up.
        symbols = [p["symbol"] for p in positions]
        assert "HOOD" in symbols

    @pytest.mark.asyncio
    async def test_watchlist_filter_is_case_insensitive(self):
        """Setup_type may have stray casing; filter must match anyway."""
        from services.sentcom_service import SentComService
        from services.sentcom_service import _is_watchlist_only_setup

        # Directly test the helper
        assert _is_watchlist_only_setup("carry_forward_watch") is True
        assert _is_watchlist_only_setup("CARRY_FORWARD_WATCH") is True
        assert _is_watchlist_only_setup(" Day_2_Continuation ") is True
        assert _is_watchlist_only_setup("opening_range_break") is False
        assert _is_watchlist_only_setup(None) is False
        assert _is_watchlist_only_setup("") is False

        # End-to-end: weird casing on the bot row also gets filtered
        svc = SentComService.__new__(SentComService)
        bot = MagicMock()
        bot.get_open_trades = MagicMock(return_value=[
            _bot_trade_dict(setup_type="CARRY_FORWARD_WATCH"),
        ])
        svc._get_trading_bot = lambda: bot

        with patch.dict(
            "routers.ib._pushed_ib_data",
            _pushed_data(symbol="MELI", last=1815.00, position_qty=None),
            clear=True,
        ):
            positions = await svc.get_our_positions()

        assert len(positions) == 0

    @pytest.mark.asyncio
    async def test_mixed_real_and_watchlist_rows_only_real_kept(self):
        """End-to-end: bot returns ONE real trade + ONE watchlist row.
        Output must contain exactly the real trade."""
        from services.sentcom_service import SentComService

        svc = SentComService.__new__(SentComService)
        bot = MagicMock()
        bot.get_open_trades = MagicMock(return_value=[
            # Real ORB trade (kept)
            _bot_trade_dict(id="real-orb", symbol="HOOD",
                            setup_type="opening_range_break",
                            direction="long", shares=100,
                            entry_price=73.42, fill_price=73.42,
                            current_price=73.42, stop_price=72.10),
            # Watchlist gameplan (suppressed)
            _bot_trade_dict(id="gameplan-meli", symbol="MELI",
                            setup_type="carry_forward_watch",
                            direction="short", shares=50),
        ])
        svc._get_trading_bot = lambda: bot

        with patch.dict(
            "routers.ib._pushed_ib_data",
            _pushed_data(),  # no IB positions, no IB quotes
            clear=True,
        ):
            positions = await svc.get_our_positions()

        symbols = [p["symbol"] for p in positions]
        assert "HOOD" in symbols
        assert "MELI" not in symbols
        assert len(positions) == 1
