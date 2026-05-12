"""
Tests for v19.34.116 — POST /api/trading-bot/retune-stop.

The retune-stop endpoint is the operator's surgical tool for fixing
LEGACY positions opened before v112: scalps running with 1.5–2.0×ATR
stops where v112 expects 0.4–0.5×. It re-uses v112's corrected
multiplier table and v111's cooldown/idempotency guards so a
double-click can't spawn duplicate IB orders.

Drive the endpoint function directly (the project's httpx /
starlette versions don't agree on TestClient kwargs in this CI env).
The endpoint is a thin FastAPI handler; calling it as a coroutine
with a body dict exercises every code path the HTTP layer would.

Contracts:
  1. Validation — missing/empty trade_id rejected (HTTPException 400).
  2. Trade lookup walks `_open_trades` by `trade.id`.
  3. ATR resolution prefers `bot._latest_atr_5m`, falls back to scanner.
  4. New stop is computed by `OpportunityEvaluator.calculate_atr_based_stop`
     — i.e. v112's table for scalps + clamp-bypass.
  5. Dry-run returns the proposal without mutating state.
  6. Live path mutates `trade.stop_price` AND calls
     `_trade_executor.attach_oca_stop_target` exactly once.
  7. Cooldown skip from v111 surfaces as `success=True` with
     `skipped: "bracket_attach_cooldown"` in `attach_result`.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture
def harness(monkeypatch):
    """Swap module-level `_trading_bot` + `_trade_executor` for mocks
    and return them along with the trade object + the bound endpoint
    coroutine."""
    from services.trading_bot_service import TradeDirection
    import routers.trading_bot as tb_router_module

    bot = MagicMock()
    bot._latest_atr_5m = {"SBUX": 2.0}  # $2 ATR
    bot._scanner = None
    bot.risk_params = SimpleNamespace(
        base_atr_multiplier=1.5,
        min_atr_multiplier=1.0,
        max_atr_multiplier=3.0,
    )
    bot._persist_trade = MagicMock(return_value=None)

    trade = SimpleNamespace(
        id="tr-9a1",
        symbol="SBUX",
        setup_type="nine_ema_scalp",
        trade_style="scalp",
        direction=TradeDirection.LONG,
        entry_price=100.0,
        stop_price=97.0,   # 1.5×ATR (legacy / v111-and-earlier)
        target_prices=[103.0],
        stop_order_id="legacy-stp-1",
        target_order_id="legacy-tgt-1",
    )
    bot._open_trades = {"SBUX": trade}

    executor = MagicMock()
    executor.attach_oca_stop_target = AsyncMock(return_value={
        "success": True,
        "stop_order_id": "new-stp-9",
        "target_order_id": "new-tgt-9",
        "oca_group": "ADOPT-OCA-NEW",
    })

    monkeypatch.setattr(tb_router_module, "_trading_bot", bot, raising=False)
    monkeypatch.setattr(tb_router_module, "_trade_executor", executor, raising=False)

    return {
        "bot": bot,
        "executor": executor,
        "trade": trade,
        "retune_stop": tb_router_module.retune_stop,
    }


def _call(retune_stop, **payload):
    """Invoke the endpoint and return the result dict (or raise the
    HTTPException for assertion against status_code)."""
    return asyncio.run(retune_stop(payload))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestRetuneStopValidation:

    def test_missing_trade_id_returns_400(self, harness):
        with pytest.raises(HTTPException) as exc:
            _call(harness["retune_stop"])
        assert exc.value.status_code == 400
        assert "trade_id" in exc.value.detail.lower()

    def test_blank_trade_id_returns_400(self, harness):
        with pytest.raises(HTTPException) as exc:
            _call(harness["retune_stop"], trade_id="   ")
        assert exc.value.status_code == 400

    def test_unknown_trade_id_returns_404(self, harness):
        with pytest.raises(HTTPException) as exc:
            _call(harness["retune_stop"], trade_id="does-not-exist")
        assert exc.value.status_code == 404
        assert "not found" in exc.value.detail.lower()

    def test_trade_with_no_setup_type_returns_400(self, harness):
        harness["trade"].setup_type = ""  # operator-grade defect
        with pytest.raises(HTTPException) as exc:
            _call(harness["retune_stop"], trade_id="tr-9a1")
        assert exc.value.status_code == 400
        assert "setup_type" in exc.value.detail.lower()

    def test_trade_with_no_entry_price_returns_400(self, harness):
        harness["trade"].entry_price = 0
        with pytest.raises(HTTPException) as exc:
            _call(harness["retune_stop"], trade_id="tr-9a1")
        assert exc.value.status_code == 400
        assert "entry_price" in exc.value.detail.lower()

    def test_atr_unavailable_returns_409(self, harness):
        harness["bot"]._latest_atr_5m = {}
        harness["bot"]._scanner = None
        with pytest.raises(HTTPException) as exc:
            _call(harness["retune_stop"], trade_id="tr-9a1")
        assert exc.value.status_code == 409
        assert "atr" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# Math correctness — re-uses v112's calculate_atr_based_stop
# ---------------------------------------------------------------------------

class TestRetuneStopMath:

    def test_scalp_retune_lands_at_0_4_atr(self, harness):
        """`nine_ema_scalp` uses v112's 0.4× multiplier (tightest)."""
        body = _call(harness["retune_stop"], trade_id="tr-9a1", dry_run=True)
        # ATR=2, entry=100, multiplier=0.4 → new_stop = 100 - 0.8 = 99.2
        assert abs(body["new_stop"] - 99.2) < 1e-4
        assert abs(body["multiplier_used"] - 0.4) < 1e-4

    def test_plain_scalp_retune_lands_at_0_5_atr(self, harness):
        harness["trade"].setup_type = "scalp"
        body = _call(harness["retune_stop"], trade_id="tr-9a1", dry_run=True)
        # ATR=2, entry=100, multiplier=0.5 → new_stop = 100 - 1.0 = 99.0
        assert abs(body["new_stop"] - 99.0) < 1e-4
        assert abs(body["multiplier_used"] - 0.5) < 1e-4

    def test_breakout_retune_uses_setup_table_multiplier(self, harness):
        """Non-scalp setups respect the existing min/max clamp.
        `breakout` = 1.5×, no clamping with default risk_params."""
        harness["trade"].setup_type = "breakout"
        body = _call(harness["retune_stop"], trade_id="tr-9a1", dry_run=True)
        # 1.5×2 = 3.0, stop = 97.0
        assert abs(body["new_stop"] - 97.0) < 1e-4

    def test_short_trade_stop_above_entry(self, harness):
        from services.trading_bot_service import TradeDirection
        harness["trade"].direction = TradeDirection.SHORT
        body = _call(harness["retune_stop"], trade_id="tr-9a1", dry_run=True)
        # nine_ema_scalp 0.4× × 2 = 0.8, SHORT stop = entry + 0.8 = 100.8
        assert abs(body["new_stop"] - 100.8) < 1e-4

    def test_atr_falls_back_to_scanner_cache(self, harness):
        harness["bot"]._latest_atr_5m = {}  # primary cache empty
        harness["bot"]._scanner = SimpleNamespace(_latest_atr={"SBUX": 2.5})
        body = _call(harness["retune_stop"], trade_id="tr-9a1", dry_run=True)
        # atr=2.5, multiplier=0.4 → stop = 100 - 1.0 = 99.0
        assert abs(body["new_stop"] - 99.0) < 1e-4
        assert body["atr"] == 2.5


# ---------------------------------------------------------------------------
# Live-path side effects
# ---------------------------------------------------------------------------

class TestRetuneStopSideEffects:

    def test_dry_run_does_not_mutate_trade_or_call_attach(self, harness):
        original_stop = harness["trade"].stop_price
        body = _call(harness["retune_stop"], trade_id="tr-9a1", dry_run=True)
        assert body["dry_run"] is True
        assert harness["trade"].stop_price == original_stop
        harness["executor"].attach_oca_stop_target.assert_not_called()

    def test_live_path_mutates_stop_and_calls_attach(self, harness):
        body = _call(harness["retune_stop"], trade_id="tr-9a1")
        assert body["success"] is True
        assert abs(harness["trade"].stop_price - 99.2) < 1e-4
        # attach_oca_stop_target called EXACTLY once with the trade.
        harness["executor"].attach_oca_stop_target.assert_called_once()
        called_with = harness["executor"].attach_oca_stop_target.call_args[0][0]
        assert called_with is harness["trade"]
        # Old/new stops surfaced so the V6 panel can render
        # "97.00 → 99.20" without a second fetch.
        assert body["old_stop"] == 97.0
        assert abs(body["new_stop"] - 99.2) < 1e-4

    def test_persist_failure_does_not_block_attach(self, harness):
        """If `_persist_trade` raises, the in-memory mutation + attach
        MUST still proceed. The persist call is best-effort."""
        harness["bot"]._persist_trade.side_effect = RuntimeError("mongo blip")
        body = _call(harness["retune_stop"], trade_id="tr-9a1")
        assert body["success"] is True
        harness["executor"].attach_oca_stop_target.assert_called_once()

    def test_executor_raises_returns_structured_error(self, harness):
        """If `attach_oca_stop_target` raises, the endpoint MUST
        surface the error in `attach_result` (not 500). Operator can
        retry or escalate from the V6 panel."""
        harness["executor"].attach_oca_stop_target.side_effect = RuntimeError("ib disconnect")
        body = _call(harness["retune_stop"], trade_id="tr-9a1")
        assert body["success"] is False
        assert "ib disconnect" in body["attach_result"]["error"]

    def test_v111_cooldown_skip_surfaces_as_success(self, harness):
        """v111 cooldown returns `{"skipped": "bracket_attach_cooldown"}`
        — endpoint treats that as a successful outcome (the operator's
        intent is honored; the cooldown is doing its job)."""
        harness["executor"].attach_oca_stop_target.return_value = {
            "skipped": "bracket_attach_cooldown",
            "cooldown_remaining_s": 18.4,
        }
        body = _call(harness["retune_stop"], trade_id="tr-9a1")
        assert body["success"] is True
        assert body["attach_result"]["skipped"] == "bracket_attach_cooldown"


# ---------------------------------------------------------------------------
# Source-level wiring — V6 integration index assertions
# ---------------------------------------------------------------------------

class TestRetuneStopRoutingContract:

    def test_endpoint_registered_with_post_method(self):
        src = (BACKEND_DIR / "routers" / "trading_bot.py").read_text()
        assert '@router.post("/retune-stop")' in src

    def test_endpoint_calls_v112_evaluator(self):
        """The whole point of this endpoint is to USE v112's table.
        Source-grep the import + call so a future refactor can't
        accidentally bypass it."""
        src = (BACKEND_DIR / "routers" / "trading_bot.py").read_text()
        idx = src.find('@router.post("/retune-stop")')
        window = src[idx:idx + 5000]
        assert "from services.opportunity_evaluator import OpportunityEvaluator" in window
        assert "calculate_atr_based_stop(" in window
