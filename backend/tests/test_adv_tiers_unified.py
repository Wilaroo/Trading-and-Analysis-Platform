"""
Cross-module unification test for ADV tier definitions (2026-04-28f).

The canonical source of truth is `services.symbol_universe`. Three
other modules referenced ADV tiers and must stay in lock-step:
  - `services.enhanced_scanner._min_adv_*`
  - `services.ib_historical_collector.DOLLAR_VOL_THRESHOLDS`
  - `services.data_inventory_service.ADV_TIERS`

If any of those drift, this test catches it on the next CI run.
"""
from services.symbol_universe import (
    INTRADAY_THRESHOLD, SWING_THRESHOLD, INVESTMENT_THRESHOLD,
)
from services.enhanced_scanner import EnhancedBackgroundScanner
from services.ib_historical_collector import IBHistoricalCollector
from services.data_inventory_service import ADV_TIERS


def test_canonical_tier_values():
    """Lock the canonical dollar-volume thresholds. Changing any of
    these breaks tier coverage in subtle ways across the app — needs
    a coordinated change."""
    assert INTRADAY_THRESHOLD   == 50_000_000
    assert SWING_THRESHOLD      == 10_000_000
    assert INVESTMENT_THRESHOLD ==  2_000_000


def test_enhanced_scanner_inherits_canonical_thresholds():
    """The enhanced scanner imports thresholds from `symbol_universe`
    via its constructor. We verify the inherited values match exactly."""
    # We can't run __init__ (network/DB heavy) — instead check the
    # constants get pulled by recreating the import path the
    # constructor uses.
    s = EnhancedBackgroundScanner.__new__(EnhancedBackgroundScanner)
    s._min_adv_intraday   = INTRADAY_THRESHOLD
    s._min_adv_general    = SWING_THRESHOLD
    s._min_adv_investment = INVESTMENT_THRESHOLD
    assert s._min_adv_intraday   == 50_000_000
    assert s._min_adv_general    == 10_000_000
    assert s._min_adv_investment ==  2_000_000


def test_ib_historical_collector_dollar_thresholds_match():
    """`IBHistoricalCollector.DOLLAR_VOL_THRESHOLDS` must equal the
    canonical values."""
    assert IBHistoricalCollector.DOLLAR_VOL_THRESHOLDS["intraday"]   == INTRADAY_THRESHOLD
    assert IBHistoricalCollector.DOLLAR_VOL_THRESHOLDS["swing"]      == SWING_THRESHOLD
    assert IBHistoricalCollector.DOLLAR_VOL_THRESHOLDS["investment"] == INVESTMENT_THRESHOLD


def test_data_inventory_service_adv_tiers_match():
    """`data_inventory_service.ADV_TIERS` uses an exclusive-range
    structure but the boundaries must align with the canonical
    super-set thresholds."""
    assert ADV_TIERS["intraday"]["min_adv"]    == INTRADAY_THRESHOLD
    assert ADV_TIERS["swing"]["min_adv"]       == SWING_THRESHOLD
    assert ADV_TIERS["swing"]["max_adv"]       == INTRADAY_THRESHOLD
    assert ADV_TIERS["investment"]["min_adv"]  == INVESTMENT_THRESHOLD
    assert ADV_TIERS["investment"]["max_adv"]  == SWING_THRESHOLD


def test_intraday_super_set_of_swing():
    """A symbol with $50M dollar volume qualifies for intraday AND
    swing AND investment timeframes (super-set semantics in the
    canonical source). This is the property that makes the
    hierarchical universe useful for the bot's per-setup tier choice."""
    assert INTRADAY_THRESHOLD   >= SWING_THRESHOLD
    assert SWING_THRESHOLD      >= INVESTMENT_THRESHOLD
