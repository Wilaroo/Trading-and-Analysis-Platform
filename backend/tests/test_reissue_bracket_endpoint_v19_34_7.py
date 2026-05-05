"""
test_reissue_bracket_endpoint_v19_34_7.py — pin the new
POST /api/trading-bot/reissue-bracket endpoint.

Operator-driven manual + auto-call entry point for the bracket re-issue
service. Tested:
  - 400 on missing trade_id / 404 on trade_id not in _open_trades
  - 503 when trading bot uninitialized
  - dry_run path returns a plan WITHOUT calling cancel/submit
  - happy path delegates to reissue_bracket_for_trade and forwards args
  - orchestrator exceptions handled with safe error envelope (no 500)
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _setup_bot_with_trade(trade_id="trade-1"):
    """Patches `routers.trading_bot._trading_bot` with a stub that has a
    matching open trade. Returns (bot, trade)."""
    from services.trading_bot_service import (
        BotTrade, RiskParameters, TradeDirection, TradeStatus, TradeTimeframe,
    )
    trade = BotTrade(
        id=trade_id, symbol="XLU",
        direction=TradeDirection.LONG, status=TradeStatus.OPEN,
        setup_type="orb", timeframe=TradeTimeframe.INTRADAY,
        quality_score=70, quality_grade="B",
        entry_price=80.0, current_price=80.0, stop_price=79.0,
        target_prices=[81.0, 82.0, 83.0],
        shares=100, remaining_shares=100,
        risk_amount=100.0, potential_reward=300.0, risk_reward_ratio=3.0,
        scale_out_config={"enabled": True,
                          "scale_out_pcts": [0.5, 0.3, 0.2],
                          "targets_hit": [], "partial_exits": []},
        trade_style="intraday",
    )
    bot = MagicMock()
    bot.risk_params = RiskParameters()
    bot._open_trades = {trade_id: trade}
    bot._save_trade = AsyncMock()
    bot._emit_stream_event = AsyncMock()
    return bot, trade


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

class TestReissueBracketEndpointV19_34_7:

    @pytest.mark.asyncio
    async def test_missing_trade_id_returns_400(self):
        from routers import trading_bot as tb
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await tb.reissue_bracket({})
        assert exc.value.status_code == 400
        assert "trade_id" in exc.value.detail

    @pytest.mark.asyncio
    async def test_invalid_new_total_shares_returns_400(self):
        from routers import trading_bot as tb
        from fastapi import HTTPException
        bot, _ = _setup_bot_with_trade()
        original = tb._trading_bot
        tb._trading_bot = bot
        try:
            with pytest.raises(HTTPException) as exc:
                await tb.reissue_bracket({
                    "trade_id": "trade-1",
                    "new_total_shares": "not-a-number",
                })
        finally:
            tb._trading_bot = original
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_missing_bot_returns_503(self):
        from routers import trading_bot as tb
        from fastapi import HTTPException
        original = tb._trading_bot
        tb._trading_bot = None
        try:
            with pytest.raises(HTTPException) as exc:
                await tb.reissue_bracket({"trade_id": "x"})
        finally:
            tb._trading_bot = original
        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_unknown_trade_id_returns_404(self):
        from routers import trading_bot as tb
        from fastapi import HTTPException
        bot, _ = _setup_bot_with_trade(trade_id="trade-1")
        original = tb._trading_bot
        tb._trading_bot = bot
        try:
            with pytest.raises(HTTPException) as exc:
                await tb.reissue_bracket({"trade_id": "trade-DOES-NOT-EXIST"})
        finally:
            tb._trading_bot = original
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_dry_run_returns_plan_without_calling_orchestrator(self):
        from routers import trading_bot as tb
        bot, _ = _setup_bot_with_trade()
        original = tb._trading_bot
        tb._trading_bot = bot
        try:
            with patch("services.bracket_reissue_service.reissue_bracket_for_trade",
                       new_callable=AsyncMock) as mock_orch:
                resp = await tb.reissue_bracket({
                    "trade_id": "trade-1",
                    "reason": "scale_in",
                    "new_total_shares": 150,
                    "new_avg_entry": 80.33,
                    "dry_run": True,
                })
        finally:
            tb._trading_bot = original

        assert resp["success"] is True
        assert resp["phase"] == "compute"
        assert resp["dry_run"] is True
        plan = resp["plan"]
        assert plan["new_total_shares"] == 150
        assert plan["remaining_shares"] == 150
        # Orchestrator NEVER called in dry_run
        mock_orch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_happy_path_delegates_to_orchestrator(self):
        from routers import trading_bot as tb
        bot, trade = _setup_bot_with_trade()
        original = tb._trading_bot
        tb._trading_bot = bot

        fake_result = {
            "success": True, "phase": "done", "trade_id": "trade-1",
            "symbol": "XLU", "reason": "scale_in",
        }
        try:
            with patch("services.bracket_reissue_service.reissue_bracket_for_trade",
                       new_callable=AsyncMock,
                       return_value=fake_result) as mock_orch:
                resp = await tb.reissue_bracket({
                    "trade_id": "trade-1",
                    "reason": "scale_in",
                    "new_total_shares": 150,
                    "new_avg_entry": 80.33,
                    "preserve_target_levels": True,
                })
        finally:
            tb._trading_bot = original

        assert resp == fake_result
        # Orchestrator called exactly once with our args
        mock_orch.assert_awaited_once()
        kwargs = mock_orch.await_args.kwargs
        assert kwargs["trade"] is trade
        assert kwargs["bot"] is bot
        assert kwargs["reason"] == "scale_in"
        assert kwargs["new_total_shares"] == 150
        assert kwargs["new_avg_entry"] == 80.33
        assert kwargs["preserve_target_levels"] is True

    @pytest.mark.asyncio
    async def test_orchestrator_exception_returns_safe_envelope(self):
        from routers import trading_bot as tb
        bot, _ = _setup_bot_with_trade()
        original = tb._trading_bot
        tb._trading_bot = bot
        try:
            with patch("services.bracket_reissue_service.reissue_bracket_for_trade",
                       new_callable=AsyncMock,
                       side_effect=RuntimeError("simulated orch crash")):
                resp = await tb.reissue_bracket({
                    "trade_id": "trade-1",
                    "reason": "manual",
                })
        finally:
            tb._trading_bot = original

        assert resp["success"] is False
        assert resp["phase"] == "orchestrator"
        assert "simulated orch crash" in resp["error"]
        assert resp["trade_id"] == "trade-1"

    @pytest.mark.asyncio
    async def test_dry_run_compute_failure_returns_safe_envelope(self):
        """When dry_run hits a compute_reissue_params ValueError (e.g.
        zero remaining shares), returns success:false with the error
        instead of raising."""
        from routers import trading_bot as tb
        bot, _ = _setup_bot_with_trade()
        original = tb._trading_bot
        tb._trading_bot = bot
        try:
            resp = await tb.reissue_bracket({
                "trade_id": "trade-1",
                "reason": "scale_out",
                "new_total_shares": 100,
                "already_executed_shares": 100,  # zero remaining
                "dry_run": True,
            })
        finally:
            tb._trading_bot = original

        assert resp["success"] is False
        assert resp["phase"] == "compute"
        assert resp["dry_run"] is True
        assert "remaining shares" in resp["error"]
