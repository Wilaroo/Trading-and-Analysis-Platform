"""Tests for v19.34.161 — `services/trade_style_classifier.py`.

Mirrors the 38-case smoke test in
`frontend/src/utils/__tests__/tradeStyleMeta.smoke.js` to guarantee the
backend bucketer and the frontend bucketer NEVER drift. When you add a
setup to one file, the corresponding case here will catch a missing
add in the other.

Run:
    cd /app/backend && PYTHONPATH=. python3 -m pytest \
        tests/test_trade_style_classifier_v19_34_161.py -v
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from services.trade_style_classifier import (
    resolve_trade_style,
    is_scalp,
    style_bucket_for_setup,
    style_label,
    TRADE_STYLE_META,
    SETUP_TO_STYLE,
)


# ── Parity with frontend smoke test (38 cases) ─────────────────────────────

# Each tuple: (row dict, expected style). Order mirrors
# tradeStyleMeta.smoke.js so it's trivial to diff.
PARITY_CASES = [
    # explicit trade_style (preferred)
    ({"trade_style": "scalp"}, "scalp"),
    ({"trade_style": "INTRADAY"}, "intraday"),
    ({"trade_style": "multi_day"}, "multi_day"),
    ({"trade_style": "swing"}, "swing"),
    ({"trade_style": "investment"}, "investment"),
    ({"trade_style": "position"}, "position"),
    # legacy aliases
    ({"trade_style": "A_PLUS"}, "multi_day"),
    ({"trade_style": "TRADE_2_HOLD"}, "intraday"),
    ({"trade_style": "MOVE_2_MOVE"}, "scalp"),
    # scan_tier fallback
    ({"scan_tier": "swing"}, "swing"),
    ({"tier": "investment"}, "investment"),
    # setup_type fallback for each bucket
    ({"setup_type": "rubber_band"}, "scalp"),
    ({"setup_type": "first_vwap_pullback"}, "intraday"),
    ({"setup_type": "pocket_pivot"}, "swing"),
    ({"setup_type": "weekly_breakout"}, "investment"),
    ({"setup_type": "stage_2_breakout"}, "position"),
    ({"setup_type": "golden_cross_filtered"}, "position"),
    ({"setup_type": "two_hundred_day_reclaim"}, "position"),
    # setup_variant wins over setup_type
    ({"setup_variant": "rubber_band", "setup_type": "SCALP"}, "scalp"),
    ({"trade_style": "TRADE_2_HOLD", "setup_variant": "weekly_breakout"}, "investment"),
    # unknown
    ({}, "unknown"),
    ({"setup_type": "nonexistent_setup_42"}, "unknown"),
    # ── v19.34.160 directional-suffix stripping ──
    ({"setup_type": "vwap_fade_long",      "trade_style": "trade_2_hold"}, "scalp"),
    ({"setup_type": "vwap_fade_short",     "trade_style": "trade_2_hold"}, "scalp"),
    ({"setup_type": "mean_reversion_long", "trade_style": "trade_2_hold"}, "scalp"),
    ({"setup_type": "mean_reversion_short","trade_style": "trade_2_hold"}, "scalp"),
    ({"setup_type": "gap_fade_long",       "trade_style": "trade_2_hold"}, "scalp"),
    ({"setup_type": "rubber_band_long",    "trade_style": "trade_2_hold"}, "scalp"),
    ({"setup_type": "rubber_band_short",   "trade_style": "trade_2_hold"}, "scalp"),
    ({"setup_variant": "vwap_fade_short",  "trade_style": "trade_2_hold"}, "scalp"),
    ({"setup_type": "breakout_long",       "trade_style": "trade_2_hold"}, "intraday"),
    ({"setup_type": "vwap_fade"}, "scalp"),
    # ── v19.34.160 timeframe in fallback chain ──
    ({"timeframe": "scalp"}, "scalp"),
    ({"timeframe": "SCALP"}, "scalp"),
    ({"timeframe": "scalp", "trade_style": ""}, "scalp"),
    # ── v19.34.160 regression guards (live DGX positions) ──
    ({"setup_type": "squeeze",            "trade_style": "trade_2_hold"}, "intraday"),
    ({"setup_type": "vwap_continuation",  "trade_style": "trade_2_hold"}, "intraday"),
    ({"setup_type": "accumulation_entry", "trade_style": "trade_2_hold"}, "swing"),
]


@pytest.mark.parametrize("row,expected", PARITY_CASES)
def test_parity_with_frontend_smoke(row, expected):
    """Backend resolve_trade_style must agree with the JS bucketer on
    every case in tradeStyleMeta.smoke.js."""
    got = resolve_trade_style(row)
    assert got == expected, f"resolve_trade_style({row}) → {got!r}, expected {expected!r}"


# ── Behavioural assertions ────────────────────────────────────────────────


def test_resolve_trade_style_none_safe():
    assert resolve_trade_style(None) == "unknown"
    assert resolve_trade_style({}) == "unknown"


def test_is_scalp_helper():
    assert is_scalp({"setup_type": "vwap_fade_long", "trade_style": "trade_2_hold"}) is True
    assert is_scalp({"setup_type": "squeeze",        "trade_style": "trade_2_hold"}) is False
    assert is_scalp({"timeframe": "scalp"}) is True
    assert is_scalp({}) is False
    assert is_scalp(None) is False


def test_style_bucket_for_setup_convenience():
    # Equivalent to passing a partial row.
    assert style_bucket_for_setup("vwap_fade_long", "trade_2_hold") == "scalp"
    assert style_bucket_for_setup("squeeze") == "intraday"
    assert style_bucket_for_setup("unknown_setup") == "unknown"
    assert style_bucket_for_setup(None) == "unknown"
    assert style_bucket_for_setup("vwap_fade_long", timeframe="scalp") == "scalp"


def test_style_label_returns_human_string():
    assert style_label("scalp") == "Scalp"
    assert style_label("intraday") == "Intraday"
    assert style_label("nonexistent") == "Unknown"


def test_setup_to_style_table_completeness():
    """Defensive: every value in SETUP_TO_STYLE must reference a real
    TRADE_STYLE_META key. Catches typos like 'scapl' → silent unknown."""
    for setup, style in SETUP_TO_STYLE.items():
        assert style in TRADE_STYLE_META, f"setup {setup!r} maps to unknown style {style!r}"


def test_generic_trade_style_is_overridden_by_setup():
    """`trade_style='trade_2_hold'` is generic — must defer to setup-
    derived style when both are present."""
    assert resolve_trade_style({
        "trade_style": "trade_2_hold",
        "setup_type": "rubber_band",
    }) == "scalp"


def test_non_generic_trade_style_wins_over_setup():
    """Explicit non-generic trade_style ALWAYS wins, even when setup
    would suggest otherwise (operator override semantic)."""
    assert resolve_trade_style({
        "trade_style": "investment",
        "setup_type": "rubber_band",  # would normally be scalp
    }) == "investment"
