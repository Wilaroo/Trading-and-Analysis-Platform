"""
test_open_positions_payload_v19_23.py — pin the rich-payload contract
exposed by SentComService.get_our_positions() that the V5 frontend's
expandable Open Positions row depends on.

2026-05-01 v19.23: Operator caught the $0 PnL + missing-detail bug.
v19.22.3 patched the backend to merge live IB quotes + extra trade
context. This test pins the new field set so a future contributor
can't silently drop:
  - current_price (live IB quote, not stale trade.current_price)
  - scan_tier, trade_style, timeframe, smb_grade
  - reasoning[], exit_rule, trading_approach
  - risk_amount, risk_reward_ratio, potential_reward
  - remaining_shares, original_shares
  - scale_out_state{enabled, targets_hit, partial_exits}
  - trailing_stop_state{enabled, mode, current_stop, high_water_mark}

All tests are pure-Python — no IB Gateway, no network calls, no DB.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _bot_trade_dict(**overrides):
    """A canonical bot-trade dict matching what TradingBotService.get_open_trades()
    returns for an open position that the operator just took."""
    base = {
        "id": "trade-abc-123",
        "symbol": "HOOD",
        "direction": "long",
        "shares": 100,
        "fill_price": 73.42,
        "entry_price": 73.42,
        "current_price": 73.42,  # stale on purpose — pusher quote should win
        "stop_price": 72.10,
        "target_prices": [76.50, 78.20],
        "status": "open",
        "setup_type": "opening_range_break",
        "setup_variant": "long",
        "trade_style": "day",
        "timeframe": "intraday",
        "executed_at": "2026-05-01T13:32:00Z",
        "notes": "ORB long off PMH",
        "quality_score": 76,
        "quality_grade": "B+",
        "smb_grade": "A",
        "mfe_pct": 0.5,
        "mae_pct": -0.2,
        "ai_context": {"thesis": "rotation"},
        "market_regime": "RISK_ON",
        "risk_amount": 132.0,
        "risk_reward_ratio": 2.1,
        "potential_reward": 277.0,
        "remaining_shares": 100,
        "original_shares": 100,
        "regime_score": 7,
        "scan_tier": "intraday",
        "tape_score": 65,
        "entry_context": {
            "scan_tier": "intraday",
            "smb_is_a_plus": True,
            "exit_rule": "trail to 9-EMA after PT1",
            "trading_approach": "ORB momentum",
            "reasoning": [
                "PMH break with vol +180% RVol",
                "Regime risk-on, sector XLF leading",
                "Bracket OCA · SL 72.10 / PT 76.50 · R:R 2.1",
            ],
        },
        "scale_out_config": {
            "enabled": True,
            "targets_hit": [],
            "partial_exits": [],
        },
        "trailing_stop_config": {
            "enabled": True,
            "mode": "breakeven",
            "current_stop": 73.42,
            "high_water_mark": 74.10,
            "low_water_mark": 73.20,
        },
    }
    base.update(overrides)
    return base


def _mock_pushed_data(symbol: str, last: float):
    """Build a fake _pushed_ib_data module-level dict with a live quote
    so the merge-quote branch in get_our_positions() actually fires."""
    return {
        "connected": True,
        "quotes": {symbol: {"last": last, "change": 0.5, "change_pct": 0.7}},
        "positions": [],
    }


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

class TestOpenPositionsPayloadV19_23:
    """v19.23 pins the rich open-position payload that the V5 expandable
    Open Positions row depends on. If any of these fields drop the UI
    silently regresses to $0 PnL / missing chips."""

    @pytest.mark.asyncio
    async def test_live_quote_overrides_stale_trade_current_price(self):
        """Operator's bug: trade.current_price = 73.42 (stale fill price),
        but pusher had a live $73.95 quote. PnL should reflect live quote."""
        from services.sentcom_service import SentComService

        svc = SentComService.__new__(SentComService)  # bypass __init__
        # Stub the trading bot
        bot = MagicMock()
        bot.get_open_trades = MagicMock(return_value=[
            _bot_trade_dict(current_price=73.42),
        ])
        svc._get_trading_bot = lambda: bot

        # Patch _pushed_ib_data with a fresher quote
        with patch.dict(
            "routers.ib._pushed_ib_data",
            _mock_pushed_data("HOOD", 73.95),
            clear=True,
        ):
            positions = await svc.get_our_positions()

        assert len(positions) == 1
        p = positions[0]
        # Live quote MUST override the stale trade.current_price
        assert p["current_price"] == pytest.approx(73.95, abs=0.001)
        # PnL = (73.95 - 73.42) * 100 = +$53
        assert p["pnl"] == pytest.approx(53.0, abs=0.5)
        # Direction-aware percent
        assert p["pnl_percent"] > 0

    @pytest.mark.asyncio
    async def test_short_position_pnl_uses_live_quote(self):
        """SHORT position: pnl = (entry - current) * shares.  Live quote
        falling means profit; stale quote stuck at fill = $0 PnL bug."""
        from services.sentcom_service import SentComService

        svc = SentComService.__new__(SentComService)
        bot = MagicMock()
        bot.get_open_trades = MagicMock(return_value=[
            _bot_trade_dict(symbol="TSLA", direction="short", entry_price=242.98,
                            fill_price=242.98, current_price=242.98, stop_price=245.40,
                            target_prices=[238.10]),
        ])
        svc._get_trading_bot = lambda: bot

        with patch.dict(
            "routers.ib._pushed_ib_data",
            _mock_pushed_data("TSLA", 241.50),
            clear=True,
        ):
            positions = await svc.get_our_positions()

        assert len(positions) == 1
        p = positions[0]
        assert p["current_price"] == pytest.approx(241.50, abs=0.001)
        # SHORT pnl = (242.98 - 241.50) * 100 = $148
        assert p["pnl"] == pytest.approx(148.0, abs=1.0)
        assert p["direction"] == "short"

    @pytest.mark.asyncio
    async def test_payload_exposes_v5_rich_fields(self):
        """V5 Open Positions expandable row keys MUST be in the payload —
        otherwise UI silently shows blanks."""
        from services.sentcom_service import SentComService

        svc = SentComService.__new__(SentComService)
        bot = MagicMock()
        bot.get_open_trades = MagicMock(return_value=[_bot_trade_dict()])
        svc._get_trading_bot = lambda: bot

        with patch.dict(
            "routers.ib._pushed_ib_data",
            _mock_pushed_data("HOOD", 74.10),
            clear=True,
        ):
            positions = await svc.get_our_positions()

        assert len(positions) == 1
        p = positions[0]
        # Tier / style / timeframe — feed the V5 tier chip
        assert p["scan_tier"] == "intraday"
        assert p["trade_style"] == "day"
        assert p["timeframe"] == "intraday"
        # AI thesis fields
        assert p["smb_is_a_plus"] is True
        assert p["exit_rule"] == "trail to 9-EMA after PT1"
        assert p["trading_approach"] == "ORB momentum"
        assert isinstance(p["reasoning"], list)
        assert len(p["reasoning"]) >= 1
        # Risk math
        assert p["risk_amount"] == pytest.approx(132.0)
        assert p["risk_reward_ratio"] == pytest.approx(2.1)
        assert p["potential_reward"] == pytest.approx(277.0)
        # Shares accounting
        assert p["remaining_shares"] == 100
        assert p["original_shares"] == 100
        # Scale-out state — V5 expandable section reads these
        assert p["scale_out_state"]["enabled"] is True
        assert p["scale_out_state"]["targets_hit"] == []
        # Trailing-stop state — drives the "BREAKEVEN SL → $73.42" subtitle
        assert p["trailing_stop_state"]["enabled"] is True
        assert p["trailing_stop_state"]["mode"] == "breakeven"
        assert p["trailing_stop_state"]["current_stop"] == pytest.approx(73.42)
        assert p["trailing_stop_state"]["high_water_mark"] == pytest.approx(74.10)

    @pytest.mark.asyncio
    async def test_payload_falls_back_when_entry_context_missing(self):
        """Legacy trades may not have `entry_context` populated. Payload
        must still expose every key (with safe defaults) so the UI's
        optional-chaining never crashes."""
        from services.sentcom_service import SentComService

        svc = SentComService.__new__(SentComService)
        legacy = _bot_trade_dict()
        legacy["entry_context"] = {}
        legacy["scan_tier"] = "swing"
        bot = MagicMock()
        bot.get_open_trades = MagicMock(return_value=[legacy])
        svc._get_trading_bot = lambda: bot

        with patch.dict(
            "routers.ib._pushed_ib_data",
            _mock_pushed_data("HOOD", 73.95),
            clear=True,
        ):
            positions = await svc.get_our_positions()

        p = positions[0]
        # Falls back to top-level scan_tier when entry_context missing it
        assert p["scan_tier"] == "swing"
        # Empty dict / list defaults
        assert p["exit_rule"] == ""
        assert p["trading_approach"] == ""
        assert p["reasoning"] == []
        assert p["smb_is_a_plus"] is False

    @pytest.mark.asyncio
    async def test_payload_handles_ib_only_position(self):
        """Untracked IB positions (NVDA / TSLA / GOOGL pre-reconcile)
        should still come back with required keys — empty defaults
        when bot didn't open the trade."""
        from services.sentcom_service import SentComService

        svc = SentComService.__new__(SentComService)
        bot = MagicMock()
        bot.get_open_trades = MagicMock(return_value=[])
        svc._get_trading_bot = lambda: bot

        ib_blob = _mock_pushed_data("GOOGL", 165.10)
        ib_blob["positions"] = [{
            "symbol": "GOOGL",
            "position": 50,
            "avgCost": 162.40,
            "marketPrice": 165.10,
            "unrealizedPnL": 135.0,
            "realizedPnL": 0.0,
        }]
        # Stub Mongo so the lazy-reconcile path returns no match
        with patch.dict("routers.ib._pushed_ib_data", ib_blob, clear=True), \
             patch("services.sentcom_service._get_db") as mock_db:
            mock_collection = MagicMock()
            mock_collection.find_one = MagicMock(return_value=None)
            mock_db.return_value = {"bot_trades": mock_collection}
            positions = await svc.get_our_positions()

        assert len(positions) == 1
        p = positions[0]
        assert p["symbol"] == "GOOGL"
        assert p["source"] == "ib"
        assert p["pnl"] == pytest.approx(135.0)
        # Status normalized to "open" (was "ib_position" pre-v19.23.1)
        assert p["status"] == "open"
        # Reconciled flag exposes whether lazy-reconcile found a match
        assert p["reconciled"] is False
        # Required fields exist (even as empty strings) so the V5 row
        # renders without throwing
        for key in ("setup_type", "trade_style", "market_regime",
                    "timeframe", "quality_grade", "notes"):
            assert key in p

    @pytest.mark.asyncio
    async def test_lazy_reconcile_enriches_ib_position_with_bot_trade_levels(self):
        """v19.23.1 — when the bot has an open bot_trade record for an
        IB-side symbol (typical after a backend restart), get_our_positions
        should inject SL/TP/reasoning into the IB position so the V5 chart
        + Open Positions panel show real protective levels."""
        from services.sentcom_service import SentComService

        svc = SentComService.__new__(SentComService)
        bot = MagicMock()
        bot.get_open_trades = MagicMock(return_value=[])  # in-memory list empty
        svc._get_trading_bot = lambda: bot

        ib_blob = _mock_pushed_data("SBUX", 105.28)
        ib_blob["positions"] = [{
            "symbol": "SBUX",
            "position": 2858,
            "avgCost": 104.89,
            "marketPrice": 105.28,
            "unrealizedPnL": 1114.62,
            "realizedPnL": 0.0,
        }]
        # Mongo returns an open bot_trade for SBUX with full context
        bot_trade_doc = {
            "id": "trade-sbux-1",
            "symbol": "SBUX",
            "status": "open",
            "executed_at": "2026-05-01T13:32:00Z",
            "stop_price": 103.50,
            "target_prices": [107.00, 109.00],
            "setup_type": "vwap_continuation",
            "trade_style": "day",
            "scan_tier": "intraday",
            "smb_grade": "B+",
            "risk_amount": 397.0,
            "risk_reward_ratio": 1.85,
            "potential_reward": 734.0,
            "remaining_shares": 2858,
            "original_shares": 2858,
            "entry_context": {
                "scan_tier": "intraday",
                "exit_rule": "trail to 9-EMA after PT1",
                "trading_approach": "VWAP continuation long",
                "reasoning": [
                    "VWAP reclaim with vol +120% RVol",
                    "Sector XLY leading; risk-on regime",
                ],
            },
            "market_regime": "RISK_ON",
            "quality_grade": "B+",
            "notes": "VWAP continuation post-pullback",
        }
        with patch.dict("routers.ib._pushed_ib_data", ib_blob, clear=True), \
             patch("services.sentcom_service._get_db") as mock_db:
            mock_collection = MagicMock()
            mock_collection.find_one = MagicMock(return_value=bot_trade_doc)
            mock_db.return_value = {"bot_trades": mock_collection}
            positions = await svc.get_our_positions()

        assert len(positions) == 1
        p = positions[0]
        # SL/TP injected from bot_trade
        assert p["stop_price"] == pytest.approx(103.50)
        assert p["target_prices"] == [107.00, 109.00]
        assert p["target_price"] == pytest.approx(107.00)
        # Rich V5 fields populated
        assert p["setup_type"] == "vwap_continuation"
        assert p["trade_style"] == "day"
        assert p["scan_tier"] == "intraday"
        assert p["smb_grade"] == "B+"
        assert p["risk_reward_ratio"] == pytest.approx(1.85)
        assert p["remaining_shares"] == 2858
        assert p["original_shares"] == 2858
        assert p["reasoning"][0].startswith("VWAP reclaim")
        assert p["exit_rule"] == "trail to 9-EMA after PT1"
        # Reconciled flag is True
        assert p["reconciled"] is True
        # entry_time copied from bot_trade
        assert p["entry_time"] is not None
        assert "2026-05-01" in str(p["entry_time"])
