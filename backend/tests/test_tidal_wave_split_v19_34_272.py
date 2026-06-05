"""
test_tidal_wave_split_v19_34_272.py — m8

Locks the tidal_wave → (fading_bounce reversion + new momentum tidal_wave) split:
canonical taxonomy class/family/archetype, AI ensemble routing, scanner registry
coverage, and the trade-style assignment. Pure logic — no DB/IB/network.
"""
import importlib

import pytest


def test_taxonomy_tidal_wave_is_momentum():
    import services.setup_taxonomy as t
    importlib.reload(t)
    assert t.setup_class("tidal_wave") == "momentum"
    assert t.strategy_family("tidal_wave") == "breakout"
    assert t.exit_archetype_prior("tidal_wave") == "runner"      # rides the surge
    assert t.ai_feature_family("tidal_wave") == "BREAKOUT"


def test_taxonomy_fading_bounce_is_reversion():
    import services.setup_taxonomy as t
    importlib.reload(t)
    assert t.setup_class("fading_bounce") == "fade"
    assert t.strategy_family("fading_bounce") == "reversion"
    assert t.exit_archetype_prior("fading_bounce") == "target"   # fixed, no runner
    assert t.ai_feature_family("fading_bounce") == "MEAN_REVERSION"


def test_ensemble_routing_split():
    from services.ai_modules.ensemble_live_inference import SCANNER_TO_ENSEMBLE_KEY as S
    assert S.get("TIDAL_WAVE") == "MOMENTUM"          # now correct (true momentum)
    assert S.get("FADING_BOUNCE") == "MEAN_REVERSION"  # renamed reversion


def test_scanner_registry_has_both():
    import services.enhanced_scanner as es
    importlib.reload(es)
    reg = es.EnhancedBackgroundScanner.REGISTERED_SETUP_TYPES
    assert "tidal_wave" in reg
    assert "fading_bounce" in reg


def test_trade_style_split():
    import services.trade_style_classifier as ts
    importlib.reload(ts)
    # momentum tidal_wave is intraday (so exit_archetype resolves to runner, not scalp→target)
    assert ts.SETUP_TO_STYLE.get("tidal_wave") == "intraday"
    # fading_bounce keeps the old scalp style
    assert ts.SETUP_TO_STYLE.get("fading_bounce") == "scalp"


def test_canonicalize_idempotent_on_new_names():
    import services.setup_taxonomy as t
    importlib.reload(t)
    assert t.canonicalize("tidal_wave") == "tidal_wave"
    assert t.canonicalize("fading_bounce") == "fading_bounce"
    # not edge-excluded
    assert t.is_edge_excluded("tidal_wave") is False
    assert t.is_edge_excluded("fading_bounce") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
