"""T3 (fork 2026-06): the SMB alias map and the market_setup_classifier context
lookup must delegate to the SSOT (services.setup_taxonomy) instead of keeping
parallel, drifting alias tables.

Guards:
  1. SMB_SETUP_ALIASES is sourced from the SSOT alias table (no second copy).
  2. lookup_trade_context canonicalizes directional/confirmed variants so they
     stop silently returning NOT_APPLIC, while staying monotonic on the
     experimental set (nothing that was experimental stops being experimental).
"""
from services.setup_taxonomy import ALIASES as SSOT_ALIASES, canonicalize
from services.smb_integration import SMB_SETUP_ALIASES, resolve_setup_name
from services.market_setup_classifier import (
    lookup_trade_context, TradeContext, MarketSetup, EXPERIMENTAL_TRADES,
)


class TestSmbAliasDelegation:
    def test_smb_aliases_equal_ssot(self):
        # Single source of truth: the SMB copy must match the SSOT table exactly.
        assert SMB_SETUP_ALIASES == dict(SSOT_ALIASES)

    def test_resolve_known_alias(self):
        assert resolve_setup_name("big_dawg") == "big_dog"
        assert resolve_setup_name("opening_range_breakout") == "orb"
        assert resolve_setup_name("scalp") == "spencer_scalp"

    def test_resolve_passthrough(self):
        # Unknown names fall through lower-cased (unchanged behavior).
        assert resolve_setup_name("Some_Brand_New") == "some_brand_new"


class TestClassifierContextDelegation:
    def test_directional_variant_now_matches_base(self):
        # vwap_fade is experimental; the suffixed variant used to miss everything
        # and return NOT_APPLIC. Now it canonicalizes to the experimental base.
        ctx = lookup_trade_context("vwap_fade_short", MarketSetup.GAP_AND_GO)
        assert ctx == TradeContext.WITH_TREND
        # base vwap_fade still behaves the same
        assert lookup_trade_context("vwap_fade", MarketSetup.GAP_AND_GO) == TradeContext.WITH_TREND

    def test_matrix_specific_alias_preserved(self):
        # puppy_dog -> big_dog matrix routing (SSOT keeps puppy_dog distinct).
        assert lookup_trade_context("puppy_dog", MarketSetup.GAP_AND_GO) == TradeContext.WITH_TREND
        # vwap_bounce -> first_vwap_pullback matrix routing.
        assert lookup_trade_context("vwap_bounce", MarketSetup.RANGE_BREAK) == TradeContext.WITH_TREND

    def test_legacy_emit_name_still_experimental(self):
        # range_break_confirmed is listed in EXPERIMENTAL_TRADES (legacy emit name);
        # the monotonic raw-OR-canonical check keeps it experimental.
        assert "range_break_confirmed" in EXPERIMENTAL_TRADES
        assert lookup_trade_context("range_break_confirmed", MarketSetup.OVEREXTENSION) == TradeContext.WITH_TREND

    def test_real_matrix_trade_unaffected(self):
        # range_break is a real matrix trade (NOT experimental) — it must still
        # read its matrix cell, not be swallowed by the experimental set.
        assert "range_break" not in EXPERIMENTAL_TRADES
        ctx = lookup_trade_context("range_break", MarketSetup.OVEREXTENSION)
        assert ctx == TradeContext.COUNTERTREND

    def test_neutral_passthrough(self):
        assert lookup_trade_context("first_move_up", MarketSetup.NEUTRAL) == TradeContext.WITH_TREND

    def test_canonicalize_is_used(self):
        # sanity: the SSOT actually strips the suffix we rely on
        assert canonicalize("vwap_fade_short") == "vwap_fade"
