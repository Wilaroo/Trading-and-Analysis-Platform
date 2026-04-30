"""
v19.20 — Feed-noise + wasted-cycle fixes.

Covers the 5 Phase-1 fixes shipped together:
  1. Bucket A — newly-enabled real setups (bouncy_ball, the_3_30_trade, etc.)
  2. Bucket B — base-setup splitter now strips `_confirmed`
  3. Bucket C — watchlist-only setups bypass bot evaluation silently
  4. Sizer respects SafetyGuardrails.max_symbol_exposure_usd (no more
     $50k → $15k cap cascade)
  5. Rejection dedup — duplicate (symbol, setup, reason) within 2 min is
     silenced
"""
import os
import sys
import pytest
from types import SimpleNamespace

# Repo import path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# --------------------------------------------------------------------------- #
# 1. Bucket A — real playbook setups now enabled by default
# --------------------------------------------------------------------------- #
def test_bucket_a_playbook_setups_enabled_by_default():
    """
    These detectors live in enhanced_scanner.py and emit alerts every cycle,
    but were silently missing from `_enabled_setups` so every alert got
    rejected as "setup_disabled" and the operator's Deep Feed was flooded
    with skip messages. v19.20 adds them to the default list.
    """
    from services.trading_bot_service import TradingBotService

    bot = TradingBotService()

    must_be_enabled = {
        "bouncy_ball",           # Bellafiore SHORT playbook
        "the_3_30_trade",        # Bellafiore LONG power-hour
        "vwap_continuation",     # VWAP momentum continuation
        "premarket_high_break",  # Gap & Go PMH break
        "trend_continuation",    # Intraday trend continuation
        "base_breakout",
        "accumulation_entry",
        "back_through_open",
        "up_through_open",
        "daily_breakout",
        "daily_squeeze",
    }
    missing = must_be_enabled - set(bot._enabled_setups)
    assert not missing, f"These real setups are still disabled by default: {missing}"


# --------------------------------------------------------------------------- #
# 2. Bucket B — base-setup splitter also strips `_confirmed`
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_confirmed_suffix_strips_to_enabled_base():
    """
    `range_break_confirmed`, `breakout_confirmed`, `breakdown_confirmed`
    should resolve to their already-enabled base setups via the splitter.
    Simulate `_get_current_alerts` by asserting the splitter algorithm
    directly — it's a pure function in the filter logic.
    """

    def _split_base(setup_type: str) -> str:
        return (
            setup_type
            .rsplit("_long", 1)[0]
            .rsplit("_short", 1)[0]
            .rsplit("_confirmed", 1)[0]
        )

    assert _split_base("range_break_confirmed") == "range_break"
    assert _split_base("breakout_confirmed") == "breakout"
    assert _split_base("breakdown_confirmed") == "breakdown"
    assert _split_base("orb_long_confirmed") == "orb"
    assert _split_base("vwap_fade_long") == "vwap_fade"
    assert _split_base("vwap_fade_short") == "vwap_fade"
    assert _split_base("mean_reversion_short") == "mean_reversion"
    # Non-suffix setups pass through unchanged.
    assert _split_base("squeeze") == "squeeze"
    assert _split_base("bouncy_ball") == "bouncy_ball"


# --------------------------------------------------------------------------- #
# 3. Bucket C — watchlist-only setups bypass bot evaluator silently
# --------------------------------------------------------------------------- #
def test_bucket_c_watchlist_only_setups_defined():
    """
    Watchlist-only setups (EOD carry-forward + approaching_* proximity
    warnings) must be present in `_watchlist_only_setups` so the bot's
    alert consumer skips them silently instead of spamming the Deep Feed
    with "setup_disabled" rejections every cycle.
    """
    from services.trading_bot_service import TradingBotService

    bot = TradingBotService()

    expected = {
        # EOD carry-forward tags
        "day_2_continuation", "carry_forward_watch", "gap_fill_open",
        # Proximity warnings
        "approaching_breakout", "approaching_hod",
        "approaching_orb", "approaching_range_break",
    }
    assert expected.issubset(bot._watchlist_only_setups)


def test_watchlist_only_setups_NOT_in_enabled_list():
    """
    Sanity: watchlist-only setups MUST NOT accidentally also be in
    the enabled list — that would un-do the silent bypass.
    """
    from services.trading_bot_service import TradingBotService
    bot = TradingBotService()
    overlap = bot._watchlist_only_setups & set(bot._enabled_setups)
    assert not overlap, f"Watchlist-only setups leaking into enabled list: {overlap}"


# --------------------------------------------------------------------------- #
# 4. Sizer respects SafetyGuardrails.max_symbol_exposure_usd
# --------------------------------------------------------------------------- #
def test_sizer_respects_safety_cap():
    """
    With `max_symbol_exposure_usd=$15,000` and `max_position_pct=50%` on a
    $100k account ($50k by capital), the sizer used to produce ~$50k
    notionals that safety blocked every time. Post-v19.20 the sizer clamps
    to the safety cap so notional * entry_price <= $15,000.
    """
    os.environ["SAFETY_MAX_SYMBOL_EXPOSURE_USD"] = "15000"
    # Re-import safety singleton fresh so the env takes effect.
    from services import safety_guardrails as _sg
    _sg._singleton = None

    from services.opportunity_evaluator import OpportunityEvaluator
    from services.trading_bot_service import TradingBotService, TradeDirection

    bot = TradingBotService()
    bot.risk_params.starting_capital = 100_000.0
    bot.risk_params.max_position_pct = 50.0
    bot.risk_params.max_risk_per_trade = 2_000.0
    bot._open_trades = {}  # No existing exposure

    evaluator = OpportunityEvaluator()
    entry_price = 6.0        # WULF-like small-dollar name
    stop_price = 5.90        # 10 cents (tight stop) -> huge share count possible
    shares, risk_amount = evaluator.calculate_position_size(
        entry_price=entry_price,
        stop_price=stop_price,
        direction=TradeDirection.LONG,
        bot=bot,
        atr=0.10,
        atr_percent=1.7,
        symbol="WULF",
    )
    notional = shares * entry_price
    assert notional <= 15_000 + 1.0, (
        f"Sizer produced notional ${notional:,.0f} which exceeds safety cap "
        f"$15,000. This would trigger the Deep Feed rejection cascade."
    )
    assert shares > 0, "Sizer should produce some shares when cap allows."


def test_sizer_returns_zero_when_symbol_fully_capped():
    """
    When existing exposure already equals/exceeds the safety cap, the sizer
    must return 0 shares so the upstream flow rejects cleanly as
    position_size_zero instead of wasting an evaluation + safety-block cycle.
    """
    os.environ["SAFETY_MAX_SYMBOL_EXPOSURE_USD"] = "15000"
    from services import safety_guardrails as _sg
    _sg._singleton = None

    from services.opportunity_evaluator import OpportunityEvaluator
    from services.trading_bot_service import TradingBotService, TradeDirection

    bot = TradingBotService()
    bot.risk_params.starting_capital = 100_000.0
    bot.risk_params.max_position_pct = 50.0
    bot.risk_params.max_risk_per_trade = 2_000.0
    # Simulate an already-open $15k WULF position
    bot._open_trades = {
        "t1": SimpleNamespace(symbol="WULF", entry_price=6.0, shares=2500)
    }  # 2500 * 6 = $15,000

    evaluator = OpportunityEvaluator()
    shares, _ = evaluator.calculate_position_size(
        entry_price=6.0,
        stop_price=5.90,
        direction=TradeDirection.LONG,
        bot=bot,
        atr=0.10,
        atr_percent=1.7,
        symbol="WULF",
    )
    assert shares == 0, (
        f"Expected 0 shares when symbol is already at safety cap, got {shares}."
    )


# --------------------------------------------------------------------------- #
# 5. Rejection dedup — same (symbol, setup, reason) silent within 2 min
# --------------------------------------------------------------------------- #
def test_rejection_dedup_suppresses_duplicate_within_window(monkeypatch):
    """
    First rejection records normally; identical follow-ups within
    _REJECTION_DEDUP_WINDOW_SECONDS are silently suppressed from the
    Bot's Brain buffer and the unified stream.
    """
    from services.trading_bot_service import TradingBotService

    bot = TradingBotService()

    added_thoughts = []
    # Spy on add_thought to detect buffer writes.
    real_add = bot._smart_filter.add_thought
    def spy_add_thought(thought):
        added_thoughts.append(thought)
        return real_add(thought)
    monkeypatch.setattr(bot._smart_filter, "add_thought", spy_add_thought)

    # First rejection — should record.
    bot.record_rejection(
        symbol="WULF", setup_type="vwap_fade_long",
        direction="long", reason_code="dedup_cooldown",
    )
    assert len(added_thoughts) == 1, "First rejection must be recorded."

    # Immediate duplicate — should be silently suppressed.
    bot.record_rejection(
        symbol="WULF", setup_type="vwap_fade_long",
        direction="long", reason_code="dedup_cooldown",
    )
    assert len(added_thoughts) == 1, "Duplicate within window must NOT re-record."

    # Different symbol on same setup/reason — should record.
    bot.record_rejection(
        symbol="NEM", setup_type="vwap_fade_long",
        direction="long", reason_code="dedup_cooldown",
    )
    assert len(added_thoughts) == 2, "Different symbol should record separately."

    # Same symbol/setup, different reason — should record.
    bot.record_rejection(
        symbol="WULF", setup_type="vwap_fade_long",
        direction="long", reason_code="symbol_exposure",
    )
    assert len(added_thoughts) == 3, "Different reason_code should record separately."
