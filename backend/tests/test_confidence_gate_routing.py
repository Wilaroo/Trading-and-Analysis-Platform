"""T2 (fork 2026-06): confidence_gate model-consensus routing is SSOT-aligned.

_SETUP_TO_MODEL is canonical-keyed; resolve_model_bases() canonicalizes the lookup
and falls back to ai_feature_family() for unmapped setups. No counter-trend setup
may be routed to a pure trend model set (the bug class that sent accumulation_entry
to the wrong model before a-i).
"""
from services.ai_modules.confidence_gate import _SETUP_TO_MODEL, resolve_model_bases
from services.setup_taxonomy import ai_feature_family, canonicalize, is_edge_excluded

SPECIALIZED = {"VWAP", "SCALP", "ORB", "GAP_AND_GO", "RANGE"}


def _has_specialized(bases):
    return any(b in SPECIALIZED or b.startswith("SHORT_") for b in bases)


class TestModelRouting:
    def test_all_entries_nonempty(self):
        for key, bases in _SETUP_TO_MODEL.items():
            assert bases, key

    def test_keys_are_canonical(self):
        # Lookups canonicalize first, so every key must equal its own canonical form
        for key in _SETUP_TO_MODEL:
            assert canonicalize(key.lower()).upper() == key, (
                key, canonicalize(key.lower()).upper())

    def test_counter_trend_not_routed_pure_trend(self):
        # reversion/reversal setups must include a reversal-ish or specialized model
        ok = {"MEAN_REVERSION", "REVERSAL", "VWAP", "SCALP"}
        for key, bases in _SETUP_TO_MODEL.items():
            if is_edge_excluded(key.lower()):
                continue
            fam = ai_feature_family(key.lower())
            if fam in ("MEAN_REVERSION", "REVERSAL"):
                assert any(b in ok or b.startswith("SHORT_") for b in bases), (key, bases)

    def test_accumulation_entry_routes_reversal(self):
        # a-i regression: must NOT be routed as trend-continuation
        assert "REVERSAL" in resolve_model_bases("accumulation_entry")

    def test_variant_names_resolve_via_canonicalize(self):
        assert resolve_model_bases("vwap_fade_long") == _SETUP_TO_MODEL["VWAP_FADE"]
        assert resolve_model_bases("orb_long_confirmed") == _SETUP_TO_MODEL["ORB"]
        assert resolve_model_bases("breakout_confirmed") == _SETUP_TO_MODEL["BREAKOUT"]
        assert resolve_model_bases("abc_scalp") == _SETUP_TO_MODEL["ABC_SCALP"]

    def test_unmapped_setup_falls_back_to_family(self):
        # An unmapped setup must resolve to its SSOT family model, never an empty
        # or dead raw-name list.
        bases = resolve_model_bases("some_brand_new_unmapped_setup")
        assert bases and bases == [ai_feature_family("some_brand_new_unmapped_setup")]
