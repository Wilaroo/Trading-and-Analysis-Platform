"""v19.34.36 — Alert→Trade join key thread-through regression tests.

The bug: pre-v19.34.36, BotTrade had no `alert_id` field, so:
  • `learning_loop.record_trade_outcome` always fell through to a fresh
    `_context_service.capture_context(...)` at CLOSE time, polluting the
    market_regime / time_of_day fields with EXIT-time conditions instead
    of ENTRY-time conditions. Months of trade outcomes had wrong context.
  • `decision_trail.py` Mongo joins by `alert_id` returned empty for every
    trade, so timeline endpoints silently produced no results.

These tests pin the contract: alert.id → alert_dict → BotTrade.alert_id
must survive save→load and be reachable everywhere downstream.
"""

from services.trading_bot_service import BotTrade, TradeDirection, TradeStatus
from services.bot_persistence import BotPersistence


def _make_trade(**overrides) -> BotTrade:
    base = dict(
        id="abc12345",
        symbol="AAPL",
        direction=TradeDirection.LONG,
        status=TradeStatus.OPEN,
        setup_type="vwap_bounce",
        timeframe="5m",
        quality_score=80,
        quality_grade="B+",
        entry_price=150.0,
        current_price=152.0,
        stop_price=148.0,
        target_prices=[154.0],
        shares=100,
        risk_amount=200.0,
        potential_reward=400.0,
        risk_reward_ratio=2.0,
    )
    base.update(overrides)
    return BotTrade(**base)


def test_botrade_has_alert_id_field():
    """BotTrade dataclass must declare alert_id (was missing pre-v19.34.36)."""
    fields = BotTrade.__dataclass_fields__
    assert "alert_id" in fields, "BotTrade is missing alert_id field"
    assert fields["alert_id"].default is None, "alert_id must default to None for backward compat"


def test_alert_id_default_is_none():
    """Existing trade-creation paths that don't pass alert_id must still work."""
    t = _make_trade()
    assert t.alert_id is None


def test_alert_id_survives_to_dict():
    """to_dict must include alert_id so Mongo persistence captures it."""
    t = _make_trade(alert_id="alert-abc-123")
    d = t.to_dict()
    assert d.get("alert_id") == "alert-abc-123"


def test_alert_id_survives_dict_to_trade_roundtrip():
    """v19.34.21 hydration logic must include the new alert_id field."""
    original = _make_trade(alert_id="alert-xyz-789")
    d = original.to_dict()
    rebuilt = BotPersistence.dict_to_trade(d)
    assert rebuilt is not None
    assert rebuilt.alert_id == "alert-xyz-789", \
        "alert_id was dropped during dict_to_trade rehydration — bot restart will lose alert→trade links"


def test_alert_id_survives_when_none():
    """Round-trip with alert_id=None must not coerce to a falsy non-None value."""
    original = _make_trade()  # alert_id defaults to None
    d = original.to_dict()
    rebuilt = BotPersistence.dict_to_trade(d)
    assert rebuilt.alert_id is None


def test_evaluator_stamps_alert_id_from_alert_dict():
    """The evaluator's BotTrade(...) call must pull alert_id from alert_dict.

    This is a static-source assertion: we read opportunity_evaluator.py and
    confirm the constructor includes `alert_id=alert.get("alert_id")`. If
    someone removes that line in a refactor, the learning-loop context
    matching silently breaks again.
    """
    from pathlib import Path
    src = Path("/app/backend/services/opportunity_evaluator.py").read_text("utf-8")
    assert 'alert_id=alert.get("alert_id")' in src, (
        "opportunity_evaluator no longer threads alert_id into BotTrade — "
        "learning-loop context matching will silently break."
    )


def test_trading_bot_alert_dict_includes_alert_id():
    """The scanner→bot alert_dict must carry alert.id forward."""
    from pathlib import Path
    src = Path("/app/backend/services/trading_bot_service.py").read_text("utf-8")
    # The alert_dict construction in _check_for_opportunities
    assert "'alert_id': alert.id" in src, (
        "trading_bot_service no longer threads alert.id into alert_dict — "
        "evaluator can't stamp BotTrade.alert_id."
    )


def test_close_path_uses_real_alert_id_for_learning_loop():
    """position_manager.close_trade must pass trade.alert_id (not getattr fallback)."""
    from pathlib import Path
    src = Path("/app/backend/services/position_manager.py").read_text("utf-8")
    assert "alert_id=trade.alert_id or trade.id" in src, (
        "close_trade no longer uses real trade.alert_id — learning-loop "
        "pending-context lookup will fall through to fresh capture at "
        "CLOSE time, polluting market_regime with exit-time conditions."
    )
    # And the buggy getattr fallback must be gone
    assert "getattr(trade, 'alert_id', trade.id)" not in src, (
        "position_manager.py still has the legacy getattr(trade, 'alert_id', trade.id) "
        "fallback — alert_id must be a real BotTrade field now."
    )


def test_execution_path_planned_r_is_r_multiple_not_price_ratio():
    """trade_execution.py planned_r calc must be reward/risk, not target/entry-1.

    Pre-v19.34.36, `planned_r = (target/entry - 1)` returned 0.10 for a 10%
    target instead of the actual R-multiple. Every downstream
    `r_capture_percent` / `quality_score` was wrong by a factor of risk/entry.
    """
    from pathlib import Path
    src = Path("/app/backend/services/trade_execution.py").read_text("utf-8")
    idx = src.index("# Start execution tracking (Phase 1 Learning)")
    block = src[idx:idx + 1500]
    # The buggy expression `target_prices[0] / trade.entry_price - 1` must be gone
    assert "target_prices[0] / trade.entry_price - 1" not in block, (
        "trade_execution.py planned_r still uses the broken price-ratio "
        "formula — every learning-loop r_capture_percent will be wrong."
    )
    # The corrected R-multiple formula must be present
    assert "abs(trade.target_prices[0] - trade.entry_price) / risk_per_share" in block, (
        "trade_execution.py planned_r must compute reward/risk, not a "
        "percentage return."
    )
