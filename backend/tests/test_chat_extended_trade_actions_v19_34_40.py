"""v19.34.40 — Chat-AI extended trade-action surface regression tests.

Pre-v19.34.40 the chat AI's tool surface only knew three actions:
  • close   — flatten a position
  • buy/sell — open a fresh position

When the operator said "let's move our stop on DDOG to $194 please", the
AI responded "I can't push a stop-price change through the trade-action
interface — it only handles opening, closing or flipping a position."

v19.34.40 extends the surface to:
  • move_stop, move_target, partial_close, cancel_orders

These tests pin:
  1. Backend `compute_reissue_params` accepts and validates operator overrides.
  2. New `/api/trading-bot/adjust-trade` endpoint exists and routes.
  3. `chat_server._execute_trade_action` knows the new actions.
  4. The chat AI system prompt advertises them with examples.
"""

from pathlib import Path

import pytest

from services.bracket_reissue_service import compute_reissue_params


# ─────────────────────────── backend: compute ───────────────────────────


class _StubRiskParams:
    reconciled_default_stop_pct = 2.0
    scale_out_pcts = [50, 50]


class _StubTradeLong:
    """Minimal BotTrade-shaped object for the unit tests."""
    id = "TID-LONG-1"
    symbol = "DDOG"
    direction = type("Dir", (), {"value": "long"})()
    shares = 100
    entry_price = 200.0
    fill_price = 200.0
    target_prices = [210.0, 220.0]
    trade_style = "trade_2_hold"
    timeframe = "5m"


class _StubTradeShort:
    id = "TID-SHORT-1"
    symbol = "TSLA"
    direction = type("Dir", (), {"value": "short"})()
    shares = 100
    entry_price = 250.0
    fill_price = 250.0
    target_prices = [240.0, 230.0]
    trade_style = "trade_2_hold"
    timeframe = "5m"


def test_operator_stop_override_long():
    plan = compute_reissue_params(
        trade=_StubTradeLong(), risk_params=_StubRiskParams(),
        reason="chat_ai_move_stop", operator_stop_price=194.0,
    )
    assert plan.new_stop_price == 194.0


def test_operator_stop_override_short():
    plan = compute_reissue_params(
        trade=_StubTradeShort(), risk_params=_StubRiskParams(),
        reason="chat_ai_move_stop", operator_stop_price=260.0,
    )
    assert plan.new_stop_price == 260.0


def test_operator_stop_rejects_long_above_entry():
    """Long stops must sit below entry — otherwise we'd lock in immediate exit."""
    with pytest.raises(ValueError, match="lock in immediate"):
        compute_reissue_params(
            trade=_StubTradeLong(), risk_params=_StubRiskParams(),
            reason="chat_ai_move_stop",
            operator_stop_price=205.0,  # above $200 entry → invalid
        )


def test_operator_stop_rejects_short_below_entry():
    """Short stops must sit above entry."""
    with pytest.raises(ValueError, match="lock in immediate"):
        compute_reissue_params(
            trade=_StubTradeShort(), risk_params=_StubRiskParams(),
            reason="chat_ai_move_stop",
            operator_stop_price=240.0,  # below $250 entry → invalid
        )


def test_operator_targets_override_long():
    plan = compute_reissue_params(
        trade=_StubTradeLong(), risk_params=_StubRiskParams(),
        reason="chat_ai_move_target",
        operator_target_prices=[215.0, 225.0],
    )
    assert plan.target_price_levels == [215.0, 225.0]


def test_operator_target_rejects_long_below_entry():
    """Long targets must sit above entry — otherwise they'd fire immediately at fill."""
    with pytest.raises(ValueError, match="below long entry"):
        compute_reissue_params(
            trade=_StubTradeLong(), risk_params=_StubRiskParams(),
            reason="chat_ai_move_target",
            operator_target_prices=[195.0],  # below $200 → invalid
        )


def test_operator_target_rejects_short_above_entry():
    """Short targets must sit below entry."""
    with pytest.raises(ValueError, match="above short entry"):
        compute_reissue_params(
            trade=_StubTradeShort(), risk_params=_StubRiskParams(),
            reason="chat_ai_move_target",
            operator_target_prices=[260.0],  # above $250 → invalid
        )


def test_operator_stop_and_targets_combine():
    plan = compute_reissue_params(
        trade=_StubTradeLong(), risk_params=_StubRiskParams(),
        reason="chat_ai_combo",
        operator_stop_price=195.0,
        operator_target_prices=[215.0],
    )
    assert plan.new_stop_price == 195.0
    assert plan.target_price_levels == [215.0]


# ─────────────────────────── backend: route ────────────────────────────


def test_adjust_trade_endpoint_registered():
    """The chat-AI-friendly /api/trading-bot/adjust-trade endpoint must exist."""
    src = Path("/app/backend/routers/trading_bot.py").read_text("utf-8")
    assert '@router.post("/adjust-trade")' in src, (
        "trading_bot router lost the /adjust-trade endpoint."
    )
    assert "async def adjust_trade(" in src
    # Body keys the chat AI uses
    for key in ("new_stop", "new_targets", "partial_close_shares", "cancel_pending_only"):
        assert key in src, f"adjust-trade endpoint no longer accepts `{key}`"


# ─────────────────────────── chat AI surface ────────────────────────────


def test_chat_executor_knows_extended_actions():
    src = Path("/app/backend/chat_server.py").read_text("utf-8")
    for action in ("move_stop", "move_target", "partial_close", "cancel_orders"):
        assert f'action == "{action}"' in src, (
            f"chat_server._execute_trade_action no longer knows the `{action}` action"
        )
    # All four routes through the new /adjust-trade endpoint
    assert src.count("/api/trading-bot/adjust-trade") >= 4, (
        "chat_server should call /adjust-trade for each of the 4 new actions"
    )


def test_chat_system_prompt_advertises_new_actions():
    """Operator mental-model: the AI must KNOW it can do these things,
    otherwise it falls back to the old "I can't" message."""
    src = Path("/app/backend/chat_server.py").read_text("utf-8")
    prompt_idx = src.index("Available actions (v19.34.40)")
    prompt_block = src[prompt_idx:prompt_idx + 3000]
    for action in ("move_stop", "move_target", "partial_close", "cancel_orders"):
        assert f'"action": "{action}"' in prompt_block, (
            f"system prompt no longer advertises the `{action}` JSON schema"
        )
    # The old refusal language should be impossible now — make sure the
    # prompt still tells the AI to ASK for a price when ambiguous.
    assert "ASK for the specific price" in src, (
        "system prompt should require the AI to disambiguate prices instead of guessing"
    )
