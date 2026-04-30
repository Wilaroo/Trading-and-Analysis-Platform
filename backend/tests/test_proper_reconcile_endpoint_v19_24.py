"""
test_proper_reconcile_endpoint_v19_24.py — pin the behaviour of the
proper reconcile path shipped in v19.24.

v19.23.1 shipped lazy (read-only) reconcile in sentcom_service.get_our_positions
that enriched the UI payload for IB-only orphan positions but didn't
materialize bot_trades. v19.24 closes the loop:

  - New `RiskParameters.reconciled_default_stop_pct` (2.0%) and
    `reconciled_default_rr` (2.0) defaults.
  - New `PositionReconciler.reconcile_orphan_positions` method writes
    actual BotTrade records + inserts into `_open_trades`.
  - New `POST /api/trading-bot/reconcile` endpoint with `symbols=[...]`
    (explicit) or `all=true&confirm=RECONCILE_ALL` (sweep) modes.
  - Frontend "Reconcile N" button in OpenPositionsV5 header (UI-only —
    tested separately via frontend screenshot / testing agent).

All tests are pure-Python, no IB Gateway, no network, no real DB.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _run(coro):
    """Run an async coroutine to completion on a fresh loop.

    Avoids pollution from pytest-asyncio fixtures that aren't in this
    session's environment (DGX runs plain pytest, not pytest-asyncio).
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _mock_ib_position(symbol, qty, avg_cost, market_price=None):
    """Shape of an entry in `routers.ib._pushed_ib_data['positions']`."""
    return {
        "symbol": symbol,
        "position": qty,
        "avgCost": avg_cost,
        "marketPrice": market_price or avg_cost,
    }


def _mock_bot(open_trades_map=None):
    """Minimal mock of TradingBotService shape used by reconcile."""
    from services.trading_bot_service import RiskParameters
    bot = MagicMock()
    bot.risk_params = RiskParameters()
    bot._open_trades = open_trades_map if open_trades_map is not None else {}
    bot._persist_trade = MagicMock()
    bot._db = MagicMock()
    return bot


def _prep_direction_history(symbol: str, direction: str = "long",
                            stable_for_seconds: int = 60) -> None:
    """v19.29 — Pre-populate the direction-stability history so the
    reconcile direction-stability gate passes. Without this, every
    reconcile call after v19.29 would skip with 'direction_unstable'
    because the history starts empty in unit tests."""
    from datetime import datetime, timedelta, timezone
    from services.position_reconciler import _ib_direction_history
    sym = (symbol or "").upper()
    now = datetime.now(timezone.utc)
    _ib_direction_history[sym] = [
        (now - timedelta(seconds=stable_for_seconds), direction.lower()),
        (now - timedelta(seconds=max(1, stable_for_seconds // 2)), direction.lower()),
        (now - timedelta(seconds=1), direction.lower()),
    ]


# --------------------------------------------------------------------------
# 1. RiskParameters defaults
# --------------------------------------------------------------------------

def test_risk_parameters_has_reconciled_defaults():
    """RiskParameters must expose `reconciled_default_stop_pct` + `_rr`
    with the v19.24 values (2.0% / 2.0 R:R). Operator picked wider-than-
    global-floor defaults because orphan positions have no setup context
    to anchor a tighter stop on."""
    from services.trading_bot_service import RiskParameters
    rp = RiskParameters()
    assert hasattr(rp, "reconciled_default_stop_pct"), (
        "RiskParameters must expose reconciled_default_stop_pct"
    )
    assert hasattr(rp, "reconciled_default_rr"), (
        "RiskParameters must expose reconciled_default_rr"
    )
    assert rp.reconciled_default_stop_pct == 2.0
    assert rp.reconciled_default_rr == 2.0


# --------------------------------------------------------------------------
# 2. Persistence round-trip — operator curl tweaks survive restart
# --------------------------------------------------------------------------

def test_bot_persistence_save_state_includes_reconcile_defaults():
    """bot_persistence.save_state must emit the new reconcile defaults
    into the `risk_params` sub-doc so they round-trip through Mongo."""
    import inspect
    from services import bot_persistence
    src = inspect.getsource(bot_persistence)
    assert "reconciled_default_stop_pct" in src, (
        "save_state / load_state must reference reconciled_default_stop_pct"
    )
    assert "reconciled_default_rr" in src, (
        "save_state / load_state must reference reconciled_default_rr"
    )


def test_get_status_surfaces_reconcile_defaults():
    """get_status must surface the reconcile defaults in the response's
    risk_params block so the operator can see them without a separate
    risk-params GET."""
    import inspect
    from services import trading_bot_service
    src = inspect.getsource(trading_bot_service.TradingBotService.get_status)
    assert "reconciled_default_stop_pct" in src
    assert "reconciled_default_rr" in src


# --------------------------------------------------------------------------
# 3. PositionReconciler.reconcile_orphan_positions — core behaviour
# --------------------------------------------------------------------------

def test_reconcile_creates_bot_trade_for_orphan_position():
    """Happy path: SBUX is an IB orphan with avg_cost=$100.
    reconcile_orphan_positions(symbols=['SBUX']) must:
      - materialize a BotTrade with setup_type='reconciled_orphan'
      - insert into bot._open_trades
      - persist via bot._persist_trade
      - compute stop = $98.00 (2% below entry)
      - compute target = $104.00 (2.0 R:R × 2% stop distance)
    """
    from services.position_reconciler import PositionReconciler
    from services.trading_bot_service import TradeDirection

    bot = _mock_bot()
    ib_positions = [_mock_ib_position("SBUX", qty=150, avg_cost=100.00, market_price=100.50)]
    ib_quotes = {"SBUX": {"last": 100.50}}
    _prep_direction_history("SBUX", "long")  # v19.29 stability gate

    pr = PositionReconciler()

    with patch("routers.ib._pushed_ib_data",
               {"positions": ib_positions, "quotes": ib_quotes}), \
         patch("routers.ib.is_pusher_connected", return_value=True), \
         patch("services.sentcom_service.emit_stream_event",
               new=AsyncMock(return_value=True)):
        result = _run(pr.reconcile_orphan_positions(bot, symbols=["SBUX"]))

    assert result["success"] is True
    assert len(result["reconciled"]) == 1
    assert len(result["skipped"]) == 0
    assert len(result["errors"]) == 0

    rec = result["reconciled"][0]
    assert rec["symbol"] == "SBUX"
    assert rec["shares"] == 150
    assert rec["direction"] == "long"
    assert rec["entry_price"] == 100.00
    assert rec["stop_price"] == pytest.approx(98.00, abs=1e-4)
    assert rec["target_price"] == pytest.approx(104.00, abs=1e-4)
    assert rec["risk_reward_ratio"] == 2.0
    assert rec["stop_pct"] == 2.0

    # BotTrade must be in _open_trades
    assert len(bot._open_trades) == 1
    trade = list(bot._open_trades.values())[0]
    assert trade.symbol == "SBUX"
    assert trade.setup_type == "reconciled_orphan"
    assert trade.quality_grade == "R"
    assert trade.trade_style == "reconciled"
    assert trade.close_at_eod is False
    assert trade.direction == TradeDirection.LONG
    assert trade.entry_price == 100.00
    assert trade.shares == 150
    assert trade.remaining_shares == 150
    assert trade.fill_price == 100.00
    assert trade.stop_price == pytest.approx(98.00, abs=1e-4)
    assert trade.target_prices == [pytest.approx(104.00, abs=1e-4)]
    # Rich entry_context — V5 UI consumes these fields.
    assert trade.entry_context.get("reconciled") is True
    assert "reasoning" in trade.entry_context
    assert trade.entry_context.get("scan_tier") == "reconciled"

    # Persistence was called (fire-and-forget via asyncio.to_thread).
    assert bot._persist_trade.called


def test_reconcile_short_position_flips_stop_and_target_correctly():
    """SHORT orphan: qty=-100, avg_cost=$50 → stop ABOVE, target BELOW."""
    from services.position_reconciler import PositionReconciler
    from services.trading_bot_service import TradeDirection

    bot = _mock_bot()
    ib_positions = [_mock_ib_position("TSLA", qty=-100, avg_cost=50.00, market_price=49.80)]
    ib_quotes = {"TSLA": {"last": 49.80}}
    _prep_direction_history("TSLA", "short")  # v19.29 stability gate

    pr = PositionReconciler()

    with patch("routers.ib._pushed_ib_data",
               {"positions": ib_positions, "quotes": ib_quotes}), \
         patch("routers.ib.is_pusher_connected", return_value=True), \
         patch("services.sentcom_service.emit_stream_event",
               new=AsyncMock(return_value=True)):
        result = _run(pr.reconcile_orphan_positions(bot, symbols=["TSLA"]))

    assert result["success"] is True
    rec = result["reconciled"][0]
    assert rec["direction"] == "short"
    # Short: stop above avg_cost by 2% → $51.00
    assert rec["stop_price"] == pytest.approx(51.00, abs=1e-4)
    # Target: 2.0 R:R × 2% below → $48.00
    assert rec["target_price"] == pytest.approx(48.00, abs=1e-4)

    trade = list(bot._open_trades.values())[0]
    assert trade.direction == TradeDirection.SHORT


def test_reconcile_skips_already_tracked_symbol():
    """Idempotent: if the bot already has a trade for SBUX, reconcile
    must SKIP with reason='already_tracked' (no double-insert)."""
    from services.position_reconciler import PositionReconciler
    from services.trading_bot_service import (
        BotTrade, TradeDirection, TradeStatus,
    )

    # Pre-populate bot._open_trades with SBUX.
    existing = BotTrade(
        id="existing-abc",
        symbol="SBUX",
        direction=TradeDirection.LONG,
        status=TradeStatus.OPEN,
        setup_type="squeeze",
        timeframe="intraday",
        quality_score=70,
        quality_grade="A",
        entry_price=99.0,
        current_price=100.0,
        stop_price=97.0,
        target_prices=[103.0],
        shares=100,
        risk_amount=200.0,
        potential_reward=400.0,
        risk_reward_ratio=2.0,
    )
    bot = _mock_bot(open_trades_map={"existing-abc": existing})

    ib_positions = [_mock_ib_position("SBUX", qty=150, avg_cost=100.00)]
    pr = PositionReconciler()

    with patch("routers.ib._pushed_ib_data",
               {"positions": ib_positions, "quotes": {}}), \
         patch("routers.ib.is_pusher_connected", return_value=True):
        result = _run(pr.reconcile_orphan_positions(bot, symbols=["SBUX"]))

    assert len(result["reconciled"]) == 0
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["symbol"] == "SBUX"
    assert result["skipped"][0]["reason"] == "already_tracked"
    # Existing trade still there, no new one added.
    assert len(bot._open_trades) == 1


def test_reconcile_skips_stop_already_breached_long():
    """Safety: if current_price has fallen below the proposed 2% stop
    (e.g. gap-down after entry), reconcile must SKIP with reason=
    'stop_already_breached' — never materialize a trade that would
    insta-stop on the next tick. Operator decides manually."""
    from services.position_reconciler import PositionReconciler

    bot = _mock_bot()
    # avg_cost=100, 2% stop = 98. Current price = 97 (already breached).
    ib_positions = [_mock_ib_position("OKLO", qty=200, avg_cost=100.00, market_price=97.00)]
    ib_quotes = {"OKLO": {"last": 97.00}}
    _prep_direction_history("OKLO", "long")  # v19.29 stability gate

    pr = PositionReconciler()

    with patch("routers.ib._pushed_ib_data",
               {"positions": ib_positions, "quotes": ib_quotes}), \
         patch("routers.ib.is_pusher_connected", return_value=True):
        result = _run(pr.reconcile_orphan_positions(bot, symbols=["OKLO"]))

    assert len(result["reconciled"]) == 0
    assert len(result["skipped"]) == 1
    sk = result["skipped"][0]
    assert sk["symbol"] == "OKLO"
    assert sk["reason"] == "stop_already_breached"
    assert sk["suggest_manual"] is True
    assert sk["direction"] == "long"
    # No trade was created.
    assert len(bot._open_trades) == 0


def test_reconcile_skips_no_ib_position():
    """If the operator asks to reconcile a symbol that's NOT in the IB
    position snapshot, reconcile SKIPS with reason='no_ib_position'."""
    from services.position_reconciler import PositionReconciler

    bot = _mock_bot()
    pr = PositionReconciler()
    with patch("routers.ib._pushed_ib_data",
               {"positions": [], "quotes": {}}), \
         patch("routers.ib.is_pusher_connected", return_value=True):
        result = _run(pr.reconcile_orphan_positions(bot, symbols=["XYZ"]))
    assert len(result["reconciled"]) == 0
    assert result["skipped"] == [{"symbol": "XYZ", "reason": "no_ib_position"}]


def test_reconcile_all_orphans_when_all_true():
    """When called with `all_orphans=True`, reconcile picks up every
    IB position that's not already in bot._open_trades."""
    from services.position_reconciler import PositionReconciler

    bot = _mock_bot()
    ib_positions = [
        _mock_ib_position("SBUX", qty=150, avg_cost=100.00, market_price=100.50),
        _mock_ib_position("SOFI", qty=500, avg_cost=10.00, market_price=10.20),
        _mock_ib_position("OKLO", qty=200, avg_cost=50.00, market_price=50.50),
    ]
    ib_quotes = {
        "SBUX": {"last": 100.50},
        "SOFI": {"last": 10.20},
        "OKLO": {"last": 50.50},
    }
    # v19.29 stability gate — pre-populate history for all 3 symbols
    _prep_direction_history("SBUX", "long")
    _prep_direction_history("SOFI", "long")
    _prep_direction_history("OKLO", "long")

    pr = PositionReconciler()

    with patch("routers.ib._pushed_ib_data",
               {"positions": ib_positions, "quotes": ib_quotes}), \
         patch("routers.ib.is_pusher_connected", return_value=True), \
         patch("services.sentcom_service.emit_stream_event",
               new=AsyncMock(return_value=True)):
        result = _run(pr.reconcile_orphan_positions(bot, all_orphans=True))

    assert result["success"] is True
    assert len(result["reconciled"]) == 3
    reconciled_syms = {r["symbol"] for r in result["reconciled"]}
    assert reconciled_syms == {"SBUX", "SOFI", "OKLO"}
    assert len(bot._open_trades) == 3


def test_reconcile_requires_pusher_connected():
    """If IB pusher is disconnected, reconcile must fail-fast with a
    clear error — never silently materialize trades with stale data."""
    from services.position_reconciler import PositionReconciler
    bot = _mock_bot()
    pr = PositionReconciler()
    with patch("routers.ib._pushed_ib_data", {"positions": [], "quotes": {}}), \
         patch("routers.ib.is_pusher_connected", return_value=False):
        result = _run(pr.reconcile_orphan_positions(bot, symbols=["SBUX"]))
    assert result["success"] is False
    assert "IB pusher not connected" in result["error"]
    assert len(bot._open_trades) == 0


def test_reconcile_respects_per_request_stop_pct_and_rr_overrides():
    """Per-request override: pass stop_pct=1.0 and rr=3.0 → generated
    stop is 1% below avg_cost, target is 3× the stop distance."""
    from services.position_reconciler import PositionReconciler

    bot = _mock_bot()
    ib_positions = [_mock_ib_position("AAPL", qty=50, avg_cost=200.00, market_price=201.00)]
    ib_quotes = {"AAPL": {"last": 201.00}}
    _prep_direction_history("AAPL", "long")  # v19.29 stability gate

    pr = PositionReconciler()

    with patch("routers.ib._pushed_ib_data",
               {"positions": ib_positions, "quotes": ib_quotes}), \
         patch("routers.ib.is_pusher_connected", return_value=True), \
         patch("services.sentcom_service.emit_stream_event",
               new=AsyncMock(return_value=True)):
        result = _run(pr.reconcile_orphan_positions(
            bot, symbols=["AAPL"], stop_pct=1.0, rr=3.0
        ))
    rec = result["reconciled"][0]
    # 1% stop = $2 → stop at $198
    assert rec["stop_price"] == pytest.approx(198.00, abs=1e-4)
    # 3.0 R:R × $2 = $6 → target at $206
    assert rec["target_price"] == pytest.approx(206.00, abs=1e-4)
    assert rec["risk_reward_ratio"] == 3.0
    assert rec["stop_pct"] == 1.0


def test_reconcile_requires_symbols_or_all_flag():
    """Caller must pass EITHER symbols=[...] OR all_orphans=True. If
    neither is provided, reconcile returns a clear error (no ambiguous
    default behavior)."""
    from services.position_reconciler import PositionReconciler

    bot = _mock_bot()
    pr = PositionReconciler()
    with patch("routers.ib._pushed_ib_data",
               {"positions": [], "quotes": {}}), \
         patch("routers.ib.is_pusher_connected", return_value=True):
        result = _run(pr.reconcile_orphan_positions(bot))
    assert result["success"] is False
    assert "symbols" in result["error"] or "all_orphans" in result["error"]


# --------------------------------------------------------------------------
# 4. Router endpoint — POST /api/trading-bot/reconcile
# --------------------------------------------------------------------------

def test_router_reconcile_endpoint_exists_and_is_post():
    """POST /api/trading-bot/reconcile must be registered on the router."""
    from routers.trading_bot import router
    paths = {(r.path, tuple(sorted(r.methods or {}))) for r in router.routes}
    # Note: router has prefix `/api/trading-bot`, so the route path stored
    # is `/reconcile`.
    matches = [(p, m) for (p, m) in paths if p.endswith("/reconcile")]
    assert matches, "POST /reconcile endpoint missing"
    # At least one match must accept POST.
    assert any("POST" in m for (_, m) in matches)


def test_router_reconcile_rejects_all_without_confirm():
    """Safety: POST /reconcile {all: true} without confirm='RECONCILE_ALL'
    raises HTTP 400. Mirrors the flatten-paper?confirm=FLATTEN pattern."""
    from fastapi import HTTPException
    import routers.trading_bot as tb_router_mod

    tb_router_mod._trading_bot = MagicMock()
    tb_router_mod._trading_bot.reconcile_orphan_positions = AsyncMock(
        return_value={"success": True, "reconciled": [], "skipped": [], "errors": []}
    )

    req_no_token = tb_router_mod.ReconcileRequest(all=True)
    req_wrong_token = tb_router_mod.ReconcileRequest(all=True, confirm="WRONG")

    with pytest.raises(HTTPException) as exc1:
        _run(tb_router_mod.reconcile_orphan_positions(req_no_token))
    assert exc1.value.status_code == 400
    assert "confirm" in exc1.value.detail.lower()

    with pytest.raises(HTTPException) as exc2:
        _run(tb_router_mod.reconcile_orphan_positions(req_wrong_token))
    assert exc2.value.status_code == 400


def test_router_reconcile_rejects_empty_body():
    """POST /reconcile {} (no symbols, no all) raises 400 — no
    ambiguous default behavior."""
    from fastapi import HTTPException
    import routers.trading_bot as tb_router_mod

    tb_router_mod._trading_bot = MagicMock()
    tb_router_mod._trading_bot.reconcile_orphan_positions = AsyncMock(
        return_value={"success": True, "reconciled": [], "skipped": [], "errors": []}
    )

    req = tb_router_mod.ReconcileRequest()
    with pytest.raises(HTTPException) as exc:
        _run(tb_router_mod.reconcile_orphan_positions(req))
    assert exc.value.status_code == 400


def test_router_reconcile_accepts_symbols_list():
    """POST /reconcile {symbols: ['SBUX']} must call the bot's reconcile
    delegator with the symbols passed through unchanged."""
    import routers.trading_bot as tb_router_mod

    tb_router_mod._trading_bot = MagicMock()
    tb_router_mod._trading_bot.reconcile_orphan_positions = AsyncMock(
        return_value={"success": True, "reconciled": [
            {"symbol": "SBUX", "trade_id": "abc"}
        ], "skipped": [], "errors": []}
    )

    req = tb_router_mod.ReconcileRequest(symbols=["SBUX"])
    result = _run(tb_router_mod.reconcile_orphan_positions(req))
    assert result["success"] is True

    call = tb_router_mod._trading_bot.reconcile_orphan_positions.call_args
    assert call.kwargs.get("symbols") == ["SBUX"]
    assert call.kwargs.get("all_orphans") is False


def test_router_reconcile_accepts_all_with_confirm_token():
    """POST /reconcile {all: true, confirm: 'RECONCILE_ALL'} → 200,
    delegator called with all_orphans=True."""
    import routers.trading_bot as tb_router_mod

    tb_router_mod._trading_bot = MagicMock()
    tb_router_mod._trading_bot.reconcile_orphan_positions = AsyncMock(
        return_value={"success": True, "reconciled": [], "skipped": [], "errors": []}
    )

    req = tb_router_mod.ReconcileRequest(all=True, confirm="RECONCILE_ALL")
    result = _run(tb_router_mod.reconcile_orphan_positions(req))
    assert result["success"] is True

    call = tb_router_mod._trading_bot.reconcile_orphan_positions.call_args
    assert call.kwargs.get("all_orphans") is True


def test_router_reconcile_returns_503_when_bot_not_initialized():
    """If _trading_bot is None (service still warming up), the endpoint
    raises 503 — never pretends to have reconciled anything."""
    from fastapi import HTTPException
    import routers.trading_bot as tb_router_mod

    original = tb_router_mod._trading_bot
    try:
        tb_router_mod._trading_bot = None
        req = tb_router_mod.ReconcileRequest(symbols=["SBUX"])
        with pytest.raises(HTTPException) as exc:
            _run(tb_router_mod.reconcile_orphan_positions(req))
        assert exc.value.status_code == 503
    finally:
        tb_router_mod._trading_bot = original


# --------------------------------------------------------------------------
# 5. Source-level pin — MultiIndexRegime classifier plumbing
# --------------------------------------------------------------------------
# (P0 item from the fork handoff — the regime classifier is supposed to
#  stamp `LiveAlert.multi_index_regime` via `_apply_setup_context`. This
#  test pins the call path so a future refactor can't silently drop it.)

def test_apply_setup_context_stamps_multi_index_regime():
    """_apply_setup_context must write to `alert.multi_index_regime`.
    Checks source so regressions are caught at pytest time instead of
    requiring an RTH curl against live-alerts on Spark."""
    import inspect
    from services.enhanced_scanner import EnhancedBackgroundScanner
    src = inspect.getsource(EnhancedBackgroundScanner._apply_setup_context)
    assert "alert.multi_index_regime" in src, (
        "_apply_setup_context must assign alert.multi_index_regime — "
        "this is the plumbing that feeds the regime one-hot features "
        "into the per-Trade ML vector."
    )
    # Must try the per-cycle cache first (v19.15 optimization) AND fall
    # back to the per-alert classifier so a cold cache doesn't leave
    # alerts with regime='unknown'.
    assert "_get_cycle_context" in src
    assert "multi_index_regime_classifier" in src


def test_live_alert_has_multi_index_regime_field():
    """LiveAlert must expose `multi_index_regime` as a field so the
    scanner can stamp it. Default 'unknown' preserved so downstream
    code can tell "classifier hasn't run" from "real unknown regime"."""
    import inspect
    from services.enhanced_scanner import LiveAlert
    src = inspect.getsource(LiveAlert)
    assert "multi_index_regime" in src


def test_refresh_cycle_context_prefetches_regime():
    """_refresh_cycle_context runs ONCE per scan cycle and populates
    `self._cycle_context["multi_index_regime"]`. This is the v19.15
    optimization that saves ~15s/session at 1,500 alerts/day."""
    import inspect
    from services.enhanced_scanner import EnhancedBackgroundScanner
    src = inspect.getsource(EnhancedBackgroundScanner._refresh_cycle_context)
    assert "multi_index_regime" in src
    assert "get_multi_index_regime_classifier" in src
