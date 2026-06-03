"""
v19.34.245 — EOD trade-style filter tests.

The bug: both EOD-close paths (auto `check_eod_close` + manual `/eod-close-now`)
trusted a per-trade `close_at_eod` attribute that was set at entry from
STRATEGY_CONFIG with a default-True fallback. Position/swing/investment setups
missing that config key were wrongly flagged True and swept at EOD (observed:
accumulation_entry closed via eod_auto_close), skewing the learning loop.

Fix: `should_close_at_eod(trade)` resolves from the trade-style ORDER POLICY
(authoritative), so long-horizon styles are held overnight regardless of a
wrong/missing attribute, while scalp/intraday still close.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.order_policy_registry import should_close_at_eod  # noqa: E402


# ── long-horizon styles are HELD overnight ─────────────────────────────────
def test_position_style_not_closed():
    assert should_close_at_eod({"trade_style": "position"}) is False


def test_swing_style_not_closed():
    assert should_close_at_eod({"trade_style": "swing"}) is False


def test_investment_style_not_closed():
    assert should_close_at_eod({"trade_style": "investment"}) is False


def test_multi_day_style_not_closed():
    assert should_close_at_eod({"trade_style": "multi_day"}) is False


# ── intraday/scalp still CLOSE (operator's primary concern) ─────────────────
def test_scalp_style_closed():
    assert should_close_at_eod({"trade_style": "scalp"}) is True


def test_intraday_style_closed():
    assert should_close_at_eod({"trade_style": "intraday"}) is True


# ── THE FIX: a wrongly-stored close_at_eod=True on a position trade is IGNORED
def test_wrong_attribute_ignored_for_position():
    # This is exactly the accumulation_entry bug: stored close_at_eod=True but
    # the trade is position-style -> policy wins, NOT closed.
    trade = {"trade_style": "position", "close_at_eod": True}
    assert should_close_at_eod(trade) is False


def test_unknown_style_defaults_to_close():
    # Unknown/empty style -> DEFAULT_POLICY (intraday) -> close. Safe: an
    # uncategorized intraday name still gets flattened (no overnight orphan).
    assert should_close_at_eod({}) is True
    assert should_close_at_eod({"trade_style": "banana"}) is True
