"""
test_setup_multipliers_coverage_v19_34_118.py
─────────────────────────────────────────────────────────────────────────────
Regression guard for the bleeding-position bug (Feb 2026):
   `day_2_continuation` (and many other classifier-emitted setup_types)
   were missing from `setup_multipliers` in opportunity_evaluator.py,
   silently falling through to `bot.risk_params.base_atr_multiplier`.

Post-v19.34.118:
  • Every SETUP_REGISTRY name must resolve to an *exact* or *normalized*
    multiplier — NEVER `horizon_fallback` and NEVER `unknown`.
  • Every scanner-emitted setup_type collected via grep on the live
    codebase must resolve to a non-`unknown` multiplier.
  • Direction-suffixed variants (`_long`, `_short`, `_confirmed`,
    `approaching_*`) must normalize correctly.
  • Scalp setups must keep the sub-`min_atr_multiplier` budget.
"""
from __future__ import annotations

import pytest

from services.opportunity_evaluator import OpportunityEvaluator
from services.smb_integration import SETUP_REGISTRY


class _DummyRisk:
    base_atr_multiplier = 1.5
    min_atr_multiplier = 1.0
    max_atr_multiplier = 3.0


class _DummyBot:
    risk_params = _DummyRisk()


# Scanner-emitted setup_types collected from services/*.py (Feb 2026).
# Keep this list in sync with grep `setup_type=` across services/.
SCANNER_EMITTED_SETUPS = [
    "9_ema_scalp", "abc_scalp", "abcd_short", "accumulation_entry",
    "approaching_breakout", "approaching_hod", "approaching_orb",
    "approaching_range_break", "back_through_open", "backside",
    "base_breakout", "bella_fade", "big_dog", "bouncy_ball", "breakdown",
    "breakdown_confirmed", "breakout", "breakout_confirmed",
    "breakout_scalp", "carry_forward_watch", "chart_pattern",
    "daily_breakout", "daily_squeeze", "day_2", "day_2_continuation",
    "earnings_play", "ema_pullback", "fashionably_late", "first_move_down",
    "first_move_up", "first_vwap_pullback", "gap_and_go", "gap_fade",
    "gap_fill_open", "gap_give_go", "gap_pick_roll", "hitchhiker",
    "hod_breakout", "lhld", "mean_reversion", "mean_reversion_long",
    "mean_reversion_short", "momentum", "momentum_breakout",
    "momentum_continuation", "nine_ema_scalp", "off_sides_short",
    "opening_drive", "opening_range_break", "orb", "orb_long",
    "orb_long_confirmed", "orb_short", "pocket_pivot",
    "premarket_high_break", "pullback", "puppy_dog", "range_break_confirmed",
    "relative_strength_laggard", "relative_strength_leader", "rubber_band",
    "rubber_band_long", "rubber_band_scalp_long", "rubber_band_scalp_short",
    "rubber_band_short", "scalp", "second_chance", "short_breakdown",
    "short_orb", "short_squeeze_intraday", "spencer_scalp",
    "stage_2_breakout", "squeeze", "the_3_30_trade", "tidal_wave",
    "trade_2_hold", "trend_continuation", "up_through_open",
    "volume_capitulation", "vwap_bounce", "vwap_bounce_long",
    "vwap_continuation", "vwap_fade", "vwap_fade_long", "vwap_fade_short",
    "vwap_reclaim_long", "vwap_rejection", "vwap_reversal",
    "weekly_base", "weekly_breakout",
]

# Reconciler / importer / system tags. These should never be `unknown`.
SYSTEM_TAGS = [
    "reconciled_orphan", "reconciled_excess_slice", "imported_from_ib",
    "manual", "bot_fired", "default",
]


def _resolve(setup_type: str):
    return OpportunityEvaluator._resolve_atr_multiplier(setup_type, _DummyBot())


@pytest.mark.parametrize("setup", sorted(SETUP_REGISTRY.keys()))
def test_every_registry_setup_has_explicit_multiplier(setup):
    """Every SETUP_REGISTRY entry must resolve exact/normalized, not via
    horizon_fallback (and never `unknown`)."""
    mult, _is_scalp, kind = _resolve(setup)
    assert kind in {"exact", "normalized"}, (
        f"{setup} resolved via {kind} — add it explicitly to SETUP_MULTIPLIERS."
    )
    assert mult > 0


@pytest.mark.parametrize("setup", sorted(SCANNER_EMITTED_SETUPS))
def test_every_scanner_emitted_setup_resolves(setup):
    """Setup names the scanner / daily-scan / carry-forward pipeline
    can emit must never silently fall through to base_atr_multiplier."""
    mult, _is_scalp, kind = _resolve(setup)
    assert kind != "unknown", (
        f"{setup} resolved as `unknown` — would fall to base_atr_multiplier. "
        f"Add it to SETUP_MULTIPLIERS in opportunity_evaluator.py."
    )
    assert mult > 0


@pytest.mark.parametrize("setup", SYSTEM_TAGS)
def test_system_tags_have_explicit_multiplier(setup):
    """Reconciler / importer tags get an exact multiplier so stop math
    doesn't drift on re-entries."""
    mult, _is_scalp, kind = _resolve(setup)
    assert kind == "exact"
    assert mult > 0


def test_day_2_short_uses_swing_horizon_not_base():
    """Specific guard for the Feb 2026 bleeding-position bug."""
    mult, is_scalp, kind = _resolve("day_2_continuation")
    assert kind == "exact"
    assert is_scalp is False
    # Should be wider than the intraday default of 1.5×, narrower than position 3.0×.
    assert 1.5 <= mult <= 2.5


def test_direction_suffixes_normalize_when_not_explicitly_keyed():
    """`breakout_long` (not explicitly listed) normalizes to `breakout`."""
    # `breakout_long` is not in SETUP_MULTIPLIERS; it should normalize
    # to `breakout` and resolve as `normalized`.
    mult, _is_scalp, kind = _resolve("breakout_long")
    breakout_mult, _, _ = _resolve("breakout")
    assert kind == "normalized"
    assert mult == breakout_mult


def test_scalp_setups_are_flagged_for_floor_skip():
    """Scalp setups must report is_scalp=True so the
    min_atr_multiplier floor (1.0×) doesn't clamp their 0.4-0.5× stop."""
    for s in ("scalp", "9_ema_scalp", "nine_ema_scalp", "abc_scalp",
              "spencer_scalp", "hitchhiker", "bouncy_ball"):
        _mult, is_scalp, _kind = _resolve(s)
        assert is_scalp is True, f"{s} should be flagged is_scalp=True"


def test_unknown_setup_still_returns_base_multiplier_and_logs():
    """A truly-unknown setup_type still returns a sane value (not None)
    and the resolution kind is `unknown` so the caller can log it."""
    mult, is_scalp, kind = _resolve("totally_fake_setup_xyz_19_34_118")
    assert kind == "unknown"
    assert is_scalp is False
    assert mult == _DummyBot.risk_params.base_atr_multiplier
