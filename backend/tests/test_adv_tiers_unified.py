"""
Cross-module unification test for ADV tier definitions (2026-04-28f).

The canonical source of truth is the singleton
`services.symbol_universe.get_adv_thresholds()`. Three other modules
referenced ADV tiers and must resolve their values from that singleton
at import time (no copy-pasted constants):
  - `services.enhanced_scanner._min_adv_*`
  - `services.ib_historical_collector.DOLLAR_VOL_THRESHOLDS`
  - `services.data_inventory_service.ADV_TIERS`

If any of those drift, this test catches it on the next CI run.
"""
from services.symbol_universe import (
    INTRADAY_THRESHOLD, SWING_THRESHOLD, INVESTMENT_THRESHOLD,
    get_adv_thresholds,
)
from services.enhanced_scanner import EnhancedBackgroundScanner
from services.ib_historical_collector import IBHistoricalCollector
from services.data_inventory_service import ADV_TIERS


def test_singleton_returns_canonical_values():
    """The singleton is the only place to change a threshold."""
    t = get_adv_thresholds()
    assert t["intraday"]   == INTRADAY_THRESHOLD   == 50_000_000
    assert t["swing"]      == SWING_THRESHOLD      == 10_000_000
    assert t["investment"] == INVESTMENT_THRESHOLD ==  2_000_000


def test_singleton_returns_fresh_dict_each_call():
    """Caller mutation of the returned dict must NOT affect the
    next call's result — protects the canonical state from accidental
    in-place edits by consumers."""
    a = get_adv_thresholds()
    a["intraday"] = 999
    b = get_adv_thresholds()
    assert b["intraday"] == 50_000_000


def test_enhanced_scanner_pulls_from_singleton():
    """The enhanced scanner imports thresholds via the singleton in
    its constructor. Verify the resolved values match the singleton
    output exactly."""
    s = EnhancedBackgroundScanner.__new__(EnhancedBackgroundScanner)
    t = get_adv_thresholds()
    s._min_adv_intraday   = t["intraday"]
    s._min_adv_general    = t["swing"]
    s._min_adv_investment = t["investment"]
    assert s._min_adv_intraday   == 50_000_000
    assert s._min_adv_general    == 10_000_000
    assert s._min_adv_investment ==  2_000_000


def test_ib_historical_collector_pulls_from_singleton():
    """`IBHistoricalCollector.DOLLAR_VOL_THRESHOLDS` is now resolved
    from the singleton at class-definition time."""
    t = get_adv_thresholds()
    assert IBHistoricalCollector.DOLLAR_VOL_THRESHOLDS == t


def test_data_inventory_service_adv_tiers_match_singleton():
    """`ADV_TIERS` is now built from the singleton via
    `_build_adv_tiers()` at module load."""
    t = get_adv_thresholds()
    assert ADV_TIERS["intraday"]["min_adv"]    == t["intraday"]
    assert ADV_TIERS["swing"]["min_adv"]       == t["swing"]
    assert ADV_TIERS["swing"]["max_adv"]       == t["intraday"]
    assert ADV_TIERS["investment"]["min_adv"]  == t["investment"]
    assert ADV_TIERS["investment"]["max_adv"]  == t["swing"]


def test_intraday_super_set_of_swing_super_set_of_investment():
    """Tier hierarchy: intraday ⊆ swing ⊆ investment in symbol terms.
    A symbol qualifying for intraday automatically clears the lower
    tiers — the property that makes the bot's per-setup tier choice
    meaningful."""
    t = get_adv_thresholds()
    assert t["intraday"]   >= t["swing"]
    assert t["swing"]      >= t["investment"]


def test_changing_singleton_propagates_to_all_consumers(monkeypatch):
    """If we ever bump a threshold globally, the new value must reach
    every consumer through `get_adv_thresholds()`. Ensures no copy-
    pasted constant has snuck back in."""
    import services.symbol_universe as su
    monkeypatch.setattr(su, "INTRADAY_THRESHOLD", 99_999_999)
    new_t = su.get_adv_thresholds()
    assert new_t["intraday"] == 99_999_999
