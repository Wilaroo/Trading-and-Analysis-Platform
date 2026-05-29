"""
v19.34.185 (F-F) — gameplan-aware prioritization boost tests (pure logic).

Validates `TradingBotService._compute_gameplan_boost`: the ranking-only soft
conviction boost. No DB / scanner / IB needed.
"""
from services.trading_bot_service import TradingBotService

boost = TradingBotService._compute_gameplan_boost
W_WATCH, W_BIAS = 8.0, 4.0


def _a(symbol, direction="long"):
    return {"symbol": symbol, "direction": direction}


def test_watchlist_hit_gets_watch_boost():
    wl = {"NVDA", "AAPL"}
    assert boost(_a("NVDA"), wl, None, W_WATCH, W_BIAS) == W_WATCH


def test_not_on_watchlist_no_boost():
    wl = {"NVDA"}
    assert boost(_a("TSLA"), wl, None, W_WATCH, W_BIAS) == 0.0


def test_bias_alignment_long_bullish():
    assert boost(_a("TSLA", "long"), set(), "bullish", W_WATCH, W_BIAS) == W_BIAS
    assert boost(_a("TSLA", "buy"), set(), "bullish", W_WATCH, W_BIAS) == W_BIAS


def test_bias_alignment_short_bearish():
    assert boost(_a("TSLA", "short"), set(), "bearish", W_WATCH, W_BIAS) == W_BIAS
    assert boost(_a("TSLA", "sell"), set(), "bearish", W_WATCH, W_BIAS) == W_BIAS


def test_bias_misalignment_no_bias_boost():
    # long alert in a bearish-bias day → no bias boost
    assert boost(_a("TSLA", "long"), set(), "bearish", W_WATCH, W_BIAS) == 0.0
    assert boost(_a("TSLA", "short"), set(), "bullish", W_WATCH, W_BIAS) == 0.0


def test_neutral_bias_gives_no_bias_boost():
    assert boost(_a("TSLA", "long"), set(), "neutral", W_WATCH, W_BIAS) == 0.0
    assert boost(_a("TSLA", "long"), set(), None, W_WATCH, W_BIAS) == 0.0


def test_watchlist_and_bias_stack():
    wl = {"NVDA"}
    assert boost(_a("NVDA", "long"), wl, "bullish", W_WATCH, W_BIAS) == W_WATCH + W_BIAS


def test_case_insensitive_symbol():
    wl = {"NVDA"}
    assert boost({"symbol": "nvda", "direction": "long"}, wl, None, W_WATCH, W_BIAS) == W_WATCH


def test_empty_watchlist_and_missing_fields_safe():
    assert boost({}, set(), None, W_WATCH, W_BIAS) == 0.0
    assert boost(_a("NVDA"), set(), None, W_WATCH, W_BIAS) == 0.0


def test_boost_is_tunable_to_zero():
    # weights at 0 → no influence (operator can disable the feature)
    wl = {"NVDA"}
    assert boost(_a("NVDA", "long"), wl, "bullish", 0.0, 0.0) == 0.0


def test_ranking_effect_mild_additive():
    """A watchlist name (tqs 70 + 8) edges out a non-watchlist name (tqs 75),
    but not a much-higher one (tqs 85). Mirrors the _alert_rank usage."""
    wl = {"NVDA"}
    nvda = 70 + boost(_a("NVDA"), wl, None, W_WATCH, W_BIAS)   # 78
    other75 = 75 + boost(_a("ABC"), wl, None, W_WATCH, W_BIAS)  # 75
    other85 = 85 + boost(_a("XYZ"), wl, None, W_WATCH, W_BIAS)  # 85
    assert nvda > other75      # gameplan name edges out a slightly-higher TQS
    assert nvda < other85      # but does NOT override a clearly-better setup
