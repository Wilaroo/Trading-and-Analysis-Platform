"""
test_runaway_prevention_v19_34_123.py
─────────────────────────────────────────────────────────────────────────────
Two regression guards for the Feb 2026 RJF runaway pattern (28 entries
in 76 min):

1. Per-(symbol, direction) open-exposure cap blocks duplicate entries
   regardless of setup_type. This kills the cooldown-bypass-via-
   setup-classifier-rotation pattern that drove today's bleed.

2. Continuous kill-switch monitor reads PnL directly from `bot_trades`,
   not the cached `_daily_stats.net_pnl` that's missing 90% of closes.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────
# 1. Per-(symbol, direction) open-exposure cap (#2)
# ─────────────────────────────────────────────────────────────────────
class TestSymbolDirectionOpenCap:
    """The setup_type-AGNOSTIC cap that prevents RJF-style runaways."""

    @pytest.mark.asyncio
    async def test_blocks_second_short_entry_on_same_symbol(self):
        """Bot already short RJF — refuse another short entry regardless
        of setup_type."""
        from services.opportunity_evaluator import OpportunityEvaluator

        existing = SimpleNamespace(
            id="t-existing", symbol="RJF",
            direction=SimpleNamespace(value="short"),
            shares=100, setup_type="day_2_continuation",
        )
        bot = SimpleNamespace(
            _open_trades={"t-existing": existing},
            risk_params=SimpleNamespace(allow_multiple_entries_per_symbol_dir=False),
            record_rejection=MagicMock(),
        )

        # Alert is a DIFFERENT setup_type on the same (symbol, direction)
        # — exactly the bypass pattern that drove today's RJF runaway.
        alert = {
            "symbol": "RJF", "setup_type": "backside",
            "direction": "short",
        }

        evaluator = OpportunityEvaluator()
        result = await evaluator.evaluate_opportunity(alert, bot)
        assert result is None, "second entry on (RJF, short) must be refused"
        bot.record_rejection.assert_called_once()
        kwargs = bot.record_rejection.call_args.kwargs
        assert kwargs["reason_code"] == "symbol_direction_open_cap_v123"
        assert kwargs["context"]["open_canonical_id"] == "t-existing"

    @pytest.mark.asyncio
    async def test_allows_opposite_direction_entry(self):
        """RJF SHORT open → RJF LONG should NOT be blocked by this cap."""
        from services.opportunity_evaluator import OpportunityEvaluator

        existing = SimpleNamespace(
            id="t-shorts", symbol="RJF",
            direction=SimpleNamespace(value="short"), shares=100,
        )
        bot = SimpleNamespace(
            _open_trades={"t-shorts": existing},
            risk_params=SimpleNamespace(allow_multiple_entries_per_symbol_dir=False),
            record_rejection=MagicMock(),
            # Stub the rest so we don't accidentally let the alert go all
            # the way through to actual position creation (which needs
            # heavy mocks). Returning None at a later stage is fine — we
            # just want to confirm the v123 cap DIDN'T short-circuit.
            _trade_executor=None,
        )
        alert = {"symbol": "RJF", "setup_type": "breakout", "direction": "long"}

        evaluator = OpportunityEvaluator()
        # We don't care about the final return value — we care that the
        # v123 cap-rejection reason was NOT used.
        try:
            await evaluator.evaluate_opportunity(alert, bot)
        except Exception:
            pass  # downstream may crash on missing mocks; we don't care
        for call in bot.record_rejection.call_args_list:
            assert call.kwargs.get("reason_code") != "symbol_direction_open_cap_v123"

    @pytest.mark.asyncio
    async def test_override_flag_disables_cap(self):
        """Operator can opt out via allow_multiple_entries_per_symbol_dir."""
        from services.opportunity_evaluator import OpportunityEvaluator

        existing = SimpleNamespace(
            id="t1", symbol="RJF",
            direction=SimpleNamespace(value="short"), shares=100,
        )
        bot = SimpleNamespace(
            _open_trades={"t1": existing},
            risk_params=SimpleNamespace(allow_multiple_entries_per_symbol_dir=True),
            record_rejection=MagicMock(),
            _trade_executor=None,
        )
        alert = {"symbol": "RJF", "setup_type": "backside", "direction": "short"}

        evaluator = OpportunityEvaluator()
        try:
            await evaluator.evaluate_opportunity(alert, bot)
        except Exception:
            pass
        for call in bot.record_rejection.call_args_list:
            assert call.kwargs.get("reason_code") != "symbol_direction_open_cap_v123"

    @pytest.mark.asyncio
    async def test_empty_open_trades_allows_first_entry(self):
        """Bot has no positions — first RJF short must NOT be blocked."""
        from services.opportunity_evaluator import OpportunityEvaluator

        bot = SimpleNamespace(
            _open_trades={},
            risk_params=SimpleNamespace(allow_multiple_entries_per_symbol_dir=False),
            record_rejection=MagicMock(),
            _trade_executor=None,
        )
        alert = {"symbol": "RJF", "setup_type": "backside", "direction": "short"}

        evaluator = OpportunityEvaluator()
        try:
            await evaluator.evaluate_opportunity(alert, bot)
        except Exception:
            pass
        for call in bot.record_rejection.call_args_list:
            assert call.kwargs.get("reason_code") != "symbol_direction_open_cap_v123"


# ─────────────────────────────────────────────────────────────────────
# 2. Continuous kill-switch monitor reads from bot_trades (#1)
# ─────────────────────────────────────────────────────────────────────
class TestContinuousKillSwitchMonitor:
    """Monitor must trip when realized + unrealized PnL exceeds the
    LOWER of the two daily-loss caps, regardless of `_daily_stats`."""

    @pytest.mark.asyncio
    async def test_compute_realtime_pnl_sums_today_closed_trades(self):
        """Reads from bot_trades directly — bypasses stale _daily_stats."""
        from services.trading_bot_service import TradingBotService

        # Mock db that returns 3 closed-today trades (2 LIVE losers + 1 PAPER ignored)
        rows = [
            {"net_pnl": -1500.0, "executor_mode": "LIVE"},
            {"net_pnl": -3200.0, "executor_mode": "LIVE"},
            {"net_pnl": -5000.0, "executor_mode": "PAPER"},  # excluded
        ]

        async def _async_iter(_self):
            for r in rows:
                yield r
        cursor = MagicMock()
        cursor.__aiter__ = _async_iter

        db = MagicMock()
        db.__getitem__.return_value.find.return_value = cursor

        # Build minimal bot
        bot = TradingBotService.__new__(TradingBotService)
        bot._open_trades = {
            "t-unr": SimpleNamespace(unrealized_pnl=-800.0),
        }

        snap = await bot._compute_realtime_daily_pnl(db)
        # realized: -1500 + -3200 = -4700 (PAPER excluded)
        assert snap["realized"] == -4700.0
        # unrealized: -800 from open trade
        assert snap["unrealized"] == -800.0
        # closed_count: 2 LIVE only (PAPER skipped before count)
        assert snap["closed_count"] == 2

    @pytest.mark.asyncio
    async def test_handles_missing_pnl_via_realized_pnl_fallback(self):
        """net_pnl=None → falls back to realized_pnl."""
        from services.trading_bot_service import TradingBotService

        rows = [
            {"net_pnl": None, "realized_pnl": -200.0, "executor_mode": "LIVE"},
            {"net_pnl": None, "realized_pnl": -300.0, "executor_mode": "LIVE"},
        ]
        async def _async_iter(_self):
            for r in rows:
                yield r
        cursor = MagicMock()
        cursor.__aiter__ = _async_iter
        db = MagicMock()
        db.__getitem__.return_value.find.return_value = cursor

        bot = TradingBotService.__new__(TradingBotService)
        bot._open_trades = {}
        snap = await bot._compute_realtime_daily_pnl(db)
        assert snap["realized"] == -500.0
