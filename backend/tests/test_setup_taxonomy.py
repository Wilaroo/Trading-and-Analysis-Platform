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
                     "puppy_dog", "gap_pick_roll"]:
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
