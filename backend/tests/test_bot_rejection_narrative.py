"""
Regression tests for `TradingBotService._compose_rejection_narrative`
(added 2026-04-28).

Closes the operator's "what is the bot thinking?" feedback loop —
every rejection gate (dedup, position-exists, setup-disabled, TQS,
regime, EOD, etc.) must produce a wordy 1-2 sentence narrative
that surfaces in Bot's Brain.

Goal: lock the contract so future PRs adding a new gate also get
narrative coverage instead of silently swallowing the alert.
"""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def bot():
    """Construct a TradingBotService with all heavy deps stubbed —
    we only need _compose_rejection_narrative + record_rejection.
    """
    from services.trading_bot_service import TradingBotService

    b = TradingBotService()
    # Stub the smart_filter so record_rejection's append doesn't blow up.
    b._smart_filter = MagicMock()
    b._smart_filter.get_thoughts.return_value = []
    return b


def _all_substrings_present(narrative: str, *parts: str) -> bool:
    return all(p in narrative for p in parts)


def test_dedup_open_position_narrative(bot):
    out = bot._compose_rejection_narrative(
        symbol="NVDA", setup_type="squeeze", direction="long",
        reason_code="dedup_open_position",
        ctx={"existing_position": "NVDA"},
    )
    assert "Passing on NVDA" in out
    assert "Squeeze" in out
    assert "already have an open NVDA position" in out


def test_dedup_cooldown_narrative_includes_seconds_left(bot):
    out = bot._compose_rejection_narrative(
        symbol="AAPL", setup_type="vwap_bounce", direction="long",
        reason_code="dedup_cooldown",
        ctx={"cooldown_seconds_left": 87},
    )
    assert "AAPL" in out
    assert "Vwap Bounce" in out
    assert "cooldown" in out.lower()
    assert "87s" in out


def test_position_exists_narrative(bot):
    out = bot._compose_rejection_narrative(
        symbol="MSFT", setup_type="orb", direction="long",
        reason_code="position_exists", ctx={},
    )
    assert "MSFT" in out and "double up" in out


def test_pending_trade_exists_narrative(bot):
    out = bot._compose_rejection_narrative(
        symbol="TSLA", setup_type="opening_drive", direction="long",
        reason_code="pending_trade_exists", ctx={},
    )
    assert "TSLA" in out and "pending" in out


def test_setup_disabled_narrative_explains_off_in_bot_setup(bot):
    out = bot._compose_rejection_narrative(
        symbol="GOOG", setup_type="bella_fade", direction="short",
        reason_code="setup_disabled", ctx={"base_setup": "bella_fade"},
    )
    assert "currently OFF" in out
    assert "Bot Setup" in out
    assert "GOOG" in out


def test_max_open_positions_narrative_includes_cap(bot):
    out = bot._compose_rejection_narrative(
        symbol="—", setup_type="any", direction="",
        reason_code="max_open_positions", ctx={"cap": 5},
    )
    assert "max-open-positions cap" in out
    assert "(cap: 5)" in out
    # Gate-level rejection — should NOT lead with "Passing on —".
    assert "Skipping the whole scan cycle" in out


def test_tqs_too_low_narrative_includes_threshold(bot):
    out = bot._compose_rejection_narrative(
        symbol="NVDA", setup_type="squeeze", direction="long",
        reason_code="tqs_too_low", ctx={"tqs": 42, "min_tqs": 65},
    )
    assert "42/100" in out
    assert "65 minimum" in out


def test_confidence_gate_veto_narrative_quotes_the_numbers(bot):
    out = bot._compose_rejection_narrative(
        symbol="AMD", setup_type="breakout", direction="long",
        reason_code="confidence_gate_veto",
        ctx={"confidence": 0.42, "min_confidence": 0.6, "why": "model split"},
    )
    assert "AMD" in out
    assert "42%" in out
    assert "60%" in out
    assert "model split" in out


def test_regime_mismatch_narrative_uses_direction_word(bot):
    out = bot._compose_rejection_narrative(
        symbol="SPY", setup_type="breakout", direction="long",
        reason_code="regime_mismatch",
        ctx={"regime": "CONFIRMED_DOWN"},
    )
    assert "long setups" in out
    assert "CONFIRMED_DOWN" in out


def test_eod_blackout_narrative(bot):
    out = bot._compose_rejection_narrative(
        symbol="QQQ", setup_type="hod_breakout", direction="long",
        reason_code="eod_blackout", ctx={},
    )
    assert "EOD blackout" in out
    assert "QQQ" in out


def test_unknown_reason_code_falls_back_gracefully(bot):
    """Unknown reason_code must produce SOME narrative — never empty,
    never raise."""
    out = bot._compose_rejection_narrative(
        symbol="ABC", setup_type="weird", direction="long",
        reason_code="future_unknown_gate", ctx={"why": "TBD"},
    )
    assert out
    assert "ABC" in out
    assert "future_unknown_gate" in out


def test_record_rejection_pushes_into_smart_filter(bot):
    """End-to-end: record_rejection must compose narrative AND append
    to the same buffer the UI already streams."""
    narrative = bot.record_rejection(
        symbol="NVDA", setup_type="squeeze", direction="long",
        reason_code="setup_disabled", context={"base_setup": "squeeze"},
    )
    assert "NVDA" in narrative
    bot._smart_filter.add_thought.assert_called_once()
    pushed = bot._smart_filter.add_thought.call_args.args[0]
    assert pushed["symbol"] == "NVDA"
    assert pushed["setup_type"] == "squeeze"
    assert pushed["direction"] == "long"
    assert pushed["reason_code"] == "setup_disabled"
    assert pushed["action"] == "rejected"
    assert pushed["text"] == narrative


def test_record_rejection_never_throws_on_buffer_failure(bot):
    """If the smart_filter buffer breaks, record_rejection must still
    return the narrative and not propagate the error into the
    rejection hot path."""
    bot._smart_filter.add_thought.side_effect = RuntimeError("buffer dead")
    out = bot.record_rejection(
        symbol="NVDA", setup_type="squeeze", direction="long",
        reason_code="setup_disabled",
    )
    assert "NVDA" in out
    assert "currently OFF" in out


def test_short_direction_renders_short_word(bot):
    out = bot._compose_rejection_narrative(
        symbol="AMD", setup_type="vwap_rejection", direction="short",
        reason_code="regime_mismatch", ctx={"regime": "CONFIRMED_UP"},
    )
    assert "short setups" in out


def test_tight_stop_narrative_includes_distance(bot):
    out = bot._compose_rejection_narrative(
        symbol="SPY", setup_type="vwap_bounce", direction="long",
        reason_code="tight_stop", ctx={"stop_distance_pct": 0.08},
    )
    assert "SPY" in out
    assert "0.08%" in out
    assert "wicked out" in out


def test_oversized_notional_narrative(bot):
    out = bot._compose_rejection_narrative(
        symbol="BRK.B", setup_type="breakout", direction="long",
        reason_code="oversized_notional", ctx={},
    )
    assert "max-notional-per-trade cap" in out
    assert "BRK.B" in out


def test_account_guard_veto_includes_reason(bot):
    out = bot._compose_rejection_narrative(
        symbol="NVDA", setup_type="squeeze", direction="long",
        reason_code="account_guard_veto",
        ctx={"why": "would breach 2% daily loss cap"},
    )
    assert "account guard" in out
    assert "2% daily loss cap" in out
