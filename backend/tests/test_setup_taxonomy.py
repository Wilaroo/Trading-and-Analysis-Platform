"""Tests for services/setup_taxonomy.py — the canonical normalization point.

Grounded in the live DB audit (diag_setup_inventory.py, 2026-06):
variant strings, reconciliation artifacts, and momentum/fade classes.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import setup_taxonomy as st  # noqa: E402


class TestCanonicalize:
    def test_directional_variants_collapse_to_base(self):
        assert st.canonicalize("vwap_fade_long") == "vwap_fade"
        assert st.canonicalize("vwap_fade_short") == "vwap_fade"
        assert st.canonicalize("mean_reversion_long") == "mean_reversion"
        assert st.canonicalize("mean_reversion_short") == "mean_reversion"
        assert st.canonicalize("rubber_band_long") == "rubber_band"
        assert st.canonicalize("rubber_band_short") == "rubber_band"
        assert st.canonicalize("off_sides_short") == "off_sides"

    def test_scalp_infix_variants_collapse(self):
        # historical playbook display-name "Rubber Band Scalp" → *_scalp_long
        assert st.canonicalize("rubber_band_scalp_long") == "rubber_band"
        assert st.canonicalize("rubber_band_scalp_short") == "rubber_band"
        assert st.canonicalize("off_sides_scalp") == "off_sides"

    def test_confirmed_suffix_collapses(self):
        assert st.canonicalize("breakout_confirmed") == "breakout"
        assert st.canonicalize("range_break_confirmed") == "range_break"
        assert st.canonicalize("breakdown_confirmed") == "breakdown"

    def test_aliases_resolve(self):
        assert st.canonicalize("big_dawg") == "big_dog"
        assert st.canonicalize("gap_and_go") == "gap_give_go"
        assert st.canonicalize("bounce") == "rubber_band"
        assert st.canonicalize("opening_range_breakout") == "orb"

    def test_distinct_firing_setups_not_merged(self):
        # these fire as their own trades in the DB — must stay distinct
        assert st.canonicalize("puppy_dog") == "puppy_dog"
        assert st.canonicalize("tidal_wave") == "tidal_wave"
        assert st.canonicalize("vwap_bounce") == "vwap_bounce"

    def test_idempotent_on_base_names(self):
        for name in ["squeeze", "vwap_fade", "orb", "accumulation_entry",
                     "daily_breakout", "rs_leader_break", "stage_2_breakout"]:
            assert st.canonicalize(name) == name

    def test_does_not_overstrip_real_names(self):
        # names that merely contain suffix-like tokens must be untouched
        assert st.canonicalize("daily_breakout") == "daily_breakout"
        assert st.canonicalize("trend_continuation") == "trend_continuation"
        assert st.canonicalize("descending_triangle_break") == "descending_triangle_break"
        assert st.canonicalize("golden_cross_filtered") == "golden_cross_filtered"
        assert st.canonicalize("day_2_continuation") == "day_2_continuation"

    def test_empty(self):
        assert st.canonicalize("") == ""
        assert st.canonicalize(None) == ""


class TestEdgeExcluded:
    def test_reconciliation_and_import_excluded(self):
        assert st.is_edge_excluded("reconciled_excess_slice")
        assert st.is_edge_excluded("reconciled_orphan")
        assert st.is_edge_excluded("reconciled_external_v19_34_15b")
        assert st.is_edge_excluded("imported_from_ib")

    def test_watchlist_precursor_excluded(self):
        assert st.is_edge_excluded("carry_forward_watch")
        assert st.is_edge_excluded("approaching_hod")
        assert st.is_edge_excluded("approaching_breakout")
        assert st.is_edge_excluded("approaching_range_break")

    def test_real_setups_not_excluded(self):
        for name in ["vwap_fade_long", "squeeze", "rubber_band", "gap_fade",
                     "accumulation_entry", "rs_leader_break"]:
            assert not st.is_edge_excluded(name)


class TestSetupClass:
    def test_momentum_class(self):
        for name in ["squeeze", "vwap_continuation", "orb", "opening_drive",
                     "bouncy_ball", "gap_give_go", "breakout_confirmed",
                     "puppy_dog", "gap_pick_roll", "tidal_wave"]:
            assert st.setup_class(name) == "momentum", name
        assert st.is_momentum_class("vwap_continuation")
        assert st.is_momentum_class("breakout_confirmed")  # variant resolves

    def test_fade_class(self):
        for name in ["vwap_fade_long", "vwap_fade_short", "mean_reversion_long",
                     "rubber_band_short", "bella_fade", "gap_fade", "off_sides_short"]:
            assert st.setup_class(name) == "fade", name
        assert not st.is_momentum_class("vwap_fade_long")

    def test_swing_and_position(self):
        assert st.setup_class("accumulation_entry") == "swing"
        assert st.setup_class("daily_squeeze") == "swing"
        assert st.setup_class("rs_leader_break") == "position"
        assert st.setup_class("stage_2_breakout") == "position"

    def test_unknown(self):
        assert st.setup_class("totally_made_up") == "unknown"
        assert st.setup_class("") == "unknown"


class TestStyleDelegation:
    def test_style_of_uses_canonical(self):
        # variant must resolve to same style as its base
        assert st.style_of("vwap_fade_long") == st.style_of("vwap_fade")
        assert st.style_of("rubber_band_short") == st.style_of("rubber_band")
        # bouncy_ball now mapped to intraday (style-map fix shipped alongside)
        assert st.style_of("bouncy_ball") == "intraday"


class TestStrategyFamily:
    def test_breakout(self):
        for n in ["orb", "breakout", "squeeze", "range_break_confirmed",
                  "daily_breakout", "stage_2_breakout", "puppy_dog", "tidal_wave"]:
            assert st.strategy_family(n) == "breakout", n

    def test_continuation(self):
        for n in ["opening_drive", "vwap_continuation", "back_through_open",
                  "gap_pick_roll", "trend_continuation"]:
            assert st.strategy_family(n) == "continuation", n

    def test_reversion(self):
        for n in ["vwap_fade_long", "mean_reversion", "rubber_band", "gap_fade",
                  "bella_fade", "fading_bounce"]:
            assert st.strategy_family(n) == "reversion", n

    def test_reversal(self):
        for n in ["first_move_up", "backside", "off_sides_short",
                  "volume_capitulation", "bouncy_ball", "accumulation_entry"]:
            assert st.strategy_family(n) == "reversal", n

    def test_unknown(self):
        assert st.strategy_family("totally_made_up") == "unknown"


class TestExitArchetype:
    def test_runner_intraday_momentum(self):
        for n in ["squeeze", "orb", "vwap_continuation", "breakout"]:
            assert st.exit_archetype_prior(n) == "runner", n

    def test_runner_reversal_exceptions(self):
        for n in ["backside", "volume_capitulation", "bouncy_ball"]:
            assert st.exit_archetype_prior(n) == "runner", n

    def test_target_scalps_and_fades(self):
        # scalps scale out fast → target; reversion fades → target
        for n in ["gap_give_go", "bella_fade", "vwap_fade_long",
                  "mean_reversion", "first_move_up"]:
            assert st.exit_archetype_prior(n) == "target", n

    def test_swing_and_position_holds(self):
        assert st.exit_archetype_prior("accumulation_entry") == "swing_hold"
        assert st.exit_archetype_prior("daily_squeeze") == "swing_hold"
        assert st.exit_archetype_prior("rs_leader_break") == "position_hold"
        assert st.exit_archetype_prior("stage_2_breakout") == "position_hold"


class TestAiFeatureFamily:
    def test_maps_to_extractor_keys(self):
        assert st.ai_feature_family("squeeze") == "BREAKOUT"
        assert st.ai_feature_family("vwap_continuation") == "TREND_CONTINUATION"
        assert st.ai_feature_family("vwap_fade_long") == "MEAN_REVERSION"
        assert st.ai_feature_family("first_move_up") == "REVERSAL"


class TestExportTaxonomy:
    def test_structure(self):
        t = st.export_taxonomy()
        assert t["version"]
        assert set(t["strategy_families"]) >= {"continuation", "breakout",
                                               "reversion", "reversal"}
        assert "runner" in t["exit_archetypes"] and "target" in t["exit_archetypes"]
        assert t["setups"], "should enumerate canonical setups"

    def test_per_setup_fields(self):
        t = st.export_taxonomy()
        sq = t["setups"]["squeeze"]
        assert sq["strategy_family"] == "breakout"
        assert sq["exit_archetype"] == "runner"
        assert sq["style"] == "intraday"
        assert sq["ai_feature_family"] == "BREAKOUT"

    def test_vocabulary_section_text(self):
        text = st.vocabulary_section()
        assert "STRATEGY FAMILY" in text
        assert "exit_archetype" in text
        assert "squeeze" in text


class TestT1CoverageFixes:
    """fork 2026-06 — taxonomy coverage + canonicalization fixes (audit pass 1).
    a-i: accumulation_entry reclassified reversal. b: relative_strength edge-excluded.
    """

    def test_scalp_full_names_resolve_not_unknown(self):
        # _scalp suffix-strip previously dropped these to 'unknown' -> MOMENTUM misroute
        for n in ["spencer_scalp", "abc_scalp", "9_ema_scalp"]:
            assert st.canonicalize(n) == n, n
            assert st.setup_class(n) == "momentum", n

    def test_scalp_infix_variants_still_collapse(self):
        # the known-base guard must NOT break legitimate variant collapse
        assert st.canonicalize("rubber_band_scalp_long") == "rubber_band"
        assert st.canonicalize("off_sides_scalp") == "off_sides"

    def test_stacked_suffixes_collapse(self):
        assert st.canonicalize("orb_long_confirmed") == "orb"
        assert st.setup_class("orb_long_confirmed") == "momentum"

    def test_relative_strength_edge_excluded(self):
        for n in ["relative_strength_long", "relative_strength_short",
                  "relative_strength_leader", "relative_strength_laggard"]:
            assert st.is_edge_excluded(n), n
        # rs_leader_break is a REAL position setup — must NOT be excluded
        assert not st.is_edge_excluded("rs_leader_break")

    def test_accumulation_entry_reclassified_reversal(self):
        assert st.strategy_family("accumulation_entry") == "reversal"
        assert st.ai_feature_family("accumulation_entry") == "REVERSAL"
        # management unchanged: swing class, swing_hold exit
        assert st.setup_class("accumulation_entry") == "swing"
        assert st.exit_archetype_prior("accumulation_entry") == "swing_hold"

    def test_no_traded_setup_classifies_unknown(self):
        # Regression guard: every setup that actually trades (from the live
        # bot_trades audit) must classify; none may silently fall to 'unknown'.
        traded = [
            "squeeze", "vwap_bounce", "accumulation_entry", "second_chance",
            "gap_fade", "vwap_fade_long", "vwap_fade_short", "vwap_continuation",
            "rs_leader_break", "fashionably_late", "daily_squeeze", "chart_pattern",
            "fading_bounce", "abc_scalp", "pocket_pivot", "daily_breakout",
            "mean_reversion_short", "stage_2_breakout", "power_trend_stack",
            "backside", "bouncy_ball", "hod_breakout", "gap_give_go",
            "volume_capitulation", "three_week_tight", "opening_drive", "orb",
            "mean_reversion_long", "breakout_confirmed", "big_dog",
            "off_sides_short", "rubber_band_short", "rubber_band",
            "premarket_high_break", "gap_pick_roll", "breakout", "spencer_scalp",
            "range_break_confirmed", "puppy_dog", "trend_continuation_short",
            "trend_continuation", "bella_fade", "the_3_30_trade", "9_ema_scalp",
        ]
        for n in traded:
            assert st.setup_class(n) != "unknown", n


class TestM2StyleResolutionFixes:
    """m2: trade_style_classifier now delegates suffix-strip to canonicalize,
    so previously-unknown misses resolve, without regressing explicit entries."""

    def setup_method(self):
        from services import trade_style_classifier as tsc
        self.tsc = tsc

    def test_confirmed_variants_resolve(self):
        assert self.tsc.style_bucket_for_setup("breakout_confirmed") == "intraday"
        assert self.tsc.style_bucket_for_setup("range_break_confirmed") == "intraday"

    def test_scalp_infix_variant_resolves(self):
        assert self.tsc.style_bucket_for_setup("rubber_band_scalp_long") == "scalp"

    def test_alias_miss_resolves(self):
        assert self.tsc.style_bucket_for_setup("big_dawg") == "intraday"
        assert self.tsc.style_bucket_for_setup("opening_range_breakout") == "intraday"

    def test_explicit_confirmed_entry_not_regressed(self):
        # breakdown_confirmed is an EXPLICIT multi_day entry; raw-first lookup
        # must keep returning multi_day (NOT intraday via base 'breakdown').
        assert self.tsc.style_bucket_for_setup("breakdown_confirmed") == "multi_day"
