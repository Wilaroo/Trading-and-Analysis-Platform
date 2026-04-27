"""
Regression tests for the conversational setup-found narrative
composer (added 2026-04-28 per operator preference for more wordy /
conversational bot copy).

Goal: lock the "what the bot is thinking and doing at all times"
contract — every renderable input field must surface in the narrative
so future refactors can't quietly drop a piece of context.
"""

import pytest


@pytest.fixture
def svc():
    from services.sentcom_service import SentComService

    return SentComService()


def test_full_payload_renders_three_sentence_narrative(svc):
    out = svc._compose_conversational_setup_narrative(
        symbol="NVDA",
        setup_display="Relative Strength Leader",
        setup_name="relative_strength_leader",
        headline="RS LEADER NVDA +6.8% vs SPY - Outperforming market",
        direction="long",
        score=51.0,
        tqs_grade="C",
        entry_price=480.50,
        stop_price=475.20,
        target_price=495.00,
        risk_reward=1.7,
        win_rate=0.58,
        profit_factor=1.45,
        trade_type="Day Trade",
        timeframe="5min",
        reasoning_list=[
            "Outperforming SPY by 6.8% today",
            "RS leaders tend to continue in trend days",
        ],
    )

    # Sentence 1 — what we saw
    assert "NVDA" in out
    assert "Relative Strength Leader" in out
    assert "RS LEADER NVDA +6.8% vs SPY" in out
    # Sentence 2 — quality interpretation
    assert "TQS 51/100" in out
    assert "grade C" in out
    assert "borderline" in out  # 51 lands in 50-60 band
    # Track record
    assert "58% win rate" in out
    assert "profit factor 1.4" in out  # 1.45 → "1.4" or "1.5" depending on rounding
    # Sentence 3 — plan
    assert "long entry around $480.50" in out
    assert "stop at $475.20" in out
    assert "target $495.00" in out
    assert "1.7R potential" in out
    # Hold horizon + timeframe
    assert "day trade" in out.lower() or "intraday" in out.lower()
    assert "5min" in out


def test_high_quality_setup_uses_high_conviction_language(svc):
    out = svc._compose_conversational_setup_narrative(
        symbol="AAPL", setup_display="Vwap Reclaim", setup_name="vwap_reclaim",
        headline="", direction="long", score=85.0, tqs_grade="A",
        entry_price=0, stop_price=0, target_price=0, risk_reward=0,
        win_rate=0, profit_factor=0, trade_type="", timeframe="",
        reasoning_list=[],
    )
    assert "high-conviction" in out
    assert "TQS 85/100" in out


def test_low_quality_setup_warns_operator(svc):
    out = svc._compose_conversational_setup_narrative(
        symbol="XYZ", setup_display="Test Setup", setup_name="test",
        headline="", direction="long", score=42.0, tqs_grade="D",
        entry_price=0, stop_price=0, target_price=0, risk_reward=0,
        win_rate=0, profit_factor=0, trade_type="", timeframe="",
        reasoning_list=[],
    )
    assert "weak" in out
    assert "skip" in out


def test_missing_data_does_not_throw_or_dangle(svc):
    """Operator's biggest fear: empty fields produce a broken sentence
    like 'long entry around $None' or trailing empty parentheses."""
    out = svc._compose_conversational_setup_narrative(
        symbol="TSLA", setup_display="Gap Fade", setup_name="gap_fade",
        headline="", direction="", score=0, tqs_grade="",
        entry_price=None, stop_price=None, target_price=None, risk_reward=0,
        win_rate=0, profit_factor=0, trade_type="", timeframe="",
        reasoning_list=None,
    )
    assert "TSLA" in out
    assert "Gap Fade" in out
    # No dollar-zero or "None" leaks
    assert "$0.00" not in out
    assert "None" not in out
    # No dangling sentence fragments
    assert not out.endswith(",")
    assert not out.endswith(":")


def test_short_direction_renders_short_phrase(svc):
    out = svc._compose_conversational_setup_narrative(
        symbol="AMD", setup_display="Rs Laggard", setup_name="relative_strength_laggard",
        headline="RS LAGGARD AMD -4.2% vs SPY",
        direction="short", score=72.0, tqs_grade="B",
        entry_price=110.0, stop_price=113.0, target_price=104.0, risk_reward=2.0,
        win_rate=0, profit_factor=0, trade_type="Scalp", timeframe="1min",
        reasoning_list=["Underperforming SPY by 4.2%"],
    )
    assert "short entry around $110.00" in out
    assert "intraday" in out.lower()


def test_scalp_setup_uses_intraday_language(svc):
    out = svc._compose_conversational_setup_narrative(
        symbol="SPY", setup_display="9 Ema Scalp", setup_name="9_ema_scalp",
        headline="", direction="long", score=70.0, tqs_grade="B",
        entry_price=500.0, stop_price=499.0, target_price=502.0, risk_reward=2.0,
        win_rate=0, profit_factor=0, trade_type="Scalp", timeframe="1min",
        reasoning_list=[],
    )
    assert "intraday" in out.lower()


def test_swing_setup_uses_multi_day_language(svc):
    out = svc._compose_conversational_setup_narrative(
        symbol="AAPL", setup_display="Daily Squeeze", setup_name="daily_squeeze",
        headline="", direction="long", score=70.0, tqs_grade="B",
        entry_price=180.0, stop_price=175.0, target_price=190.0, risk_reward=2.0,
        win_rate=0, profit_factor=0, trade_type="Swing", timeframe="Daily",
        reasoning_list=[],
    )
    assert "multi-day swing" in out


def test_first_reasoning_line_added_when_not_in_headline(svc):
    out = svc._compose_conversational_setup_narrative(
        symbol="NVDA", setup_display="Squeeze", setup_name="squeeze",
        headline="NVDA Bollinger squeeze firing",
        direction="long", score=70, tqs_grade="B",
        entry_price=0, stop_price=0, target_price=0, risk_reward=0,
        win_rate=0, profit_factor=0, trade_type="", timeframe="",
        reasoning_list=["Volatility compression at 6-month low",
                        "Volume drying up below 20d avg"],
    )
    # Why-clause picks up the first reasoning bullet
    assert "Why:" in out
    assert "Volatility compression" in out


def test_first_reasoning_line_skipped_if_already_in_headline(svc):
    out = svc._compose_conversational_setup_narrative(
        symbol="NVDA", setup_display="Squeeze", setup_name="squeeze",
        headline="NVDA - Volatility compression at 6-month low",
        direction="long", score=70, tqs_grade="B",
        entry_price=0, stop_price=0, target_price=0, risk_reward=0,
        win_rate=0, profit_factor=0, trade_type="", timeframe="",
        reasoning_list=["Volatility compression at 6-month low"],
    )
    # No duplication — we don't want the same fact twice
    assert out.count("Volatility compression") == 1
