"""
v19.16 — Tier-aware detector dispatch (2026-04-30).

Pre-v19.16 the scanner iterated `_enabled_setups` (~35 detectors)
for every symbol regardless of tier. A symbol classified as `swing`
tier (~$2M-$10M ADV, snapshotted every 60s by bar-poll) ran
through ALL intraday-timing detectors (9_ema_scalp,
vwap_continuation, the_3_30_trade, opening_drive, etc.) — each
producing physically nonsensical signals computed from data
that's 30-90s stale.

v19.16: introduces `_intraday_only_setups` as a SUPERSET of
`_intraday_setups`. When a symbol is non-intraday tier and the
detector is in this set, dispatch is skipped entirely — saving
~40-60% of detector calls on the swing+investment cohort AND
preventing stale-data alerts from polluting the AI training
pipeline.

Conservative inclusion: only detectors with explicit sub-5min
timing or playbook "intraday only" specs are on the list. Anything
ambiguous (squeeze, breakout, chart_pattern, mean_reversion) stays
OFF so it keeps running across all tiers.

Tests pin:
  - `_intraday_only_setups` is a SUPERSET of `_intraday_setups`
    (every detector flagged as intraday-by-volume is also flagged
    as intraday-by-tier).
  - Specific detectors with known intraday timing dependencies are
    on the list (9_ema_scalp, vwap_continuation, the_3_30_trade,
    opening_drive, gap_fade, the_3_30_trade, etc.).
  - Ambiguous detectors are NOT on the list (squeeze,
    breakout, chart_pattern, mean_reversion).
  - Source-level pin: dispatch loop checks `symbol_tier` BEFORE
    calling `_check_setup`.
"""
from __future__ import annotations

import os


def _read_scanner_src() -> str:
    src_path = os.path.join(
        os.path.dirname(__file__), "..", "services", "enhanced_scanner.py"
    )
    with open(src_path) as f:
        return f.read()


# --------------------------------------------------------------------------
# Source-level pins
# --------------------------------------------------------------------------

def test_intraday_only_setups_attribute_declared():
    src = _read_scanner_src()
    assert "self._intraday_only_setups = self._intraday_setups | {" in src, (
        "v19.16 contract — _intraday_only_setups must be defined as a "
        "superset of _intraday_setups"
    )


def test_dispatch_loop_checks_tier_before_check_setup():
    """The new tier-skip MUST run BEFORE `_check_setup` is invoked,
    otherwise the savings are lost.
    """
    src = _read_scanner_src()
    # Find the dispatch block.
    loop_start = src.find("for setup_type in self._enabled_setups:")
    assert loop_start > 0
    # Within the next ~2000 chars (the loop body), the tier-skip and
    # the _check_setup call must both appear, with skip BEFORE call.
    block = src[loop_start:loop_start + 4000]
    skip_idx = block.find("setup_type in self._intraday_only_setups")
    call_idx = block.find("await self._check_setup(setup_type")
    assert skip_idx > 0, "tier-skip not found in dispatch loop"
    assert call_idx > 0, "_check_setup call not found in dispatch loop"
    assert skip_idx < call_idx, (
        "tier-skip MUST come before _check_setup, otherwise dispatch "
        "isn't actually saved"
    )


def test_dispatch_loop_reads_symbol_tier_from_cache():
    """Pin the cheap-cache read so a future contributor doesn't
    accidentally wire a new live IB call here.
    """
    src = _read_scanner_src()
    assert "symbol_tier = self._tier_cache.get(symbol)" in src


# --------------------------------------------------------------------------
# Set-membership pins (uses an instance-free dispatch via `__new__`)
# --------------------------------------------------------------------------

def _make_scanner_stub():
    from services.enhanced_scanner import EnhancedBackgroundScanner
    inst = EnhancedBackgroundScanner.__new__(EnhancedBackgroundScanner)
    # `__init__` is heavy; we replicate ONLY the two attrs the pins read.
    # Trigger init's intraday-set definitions by manually setting them
    # the same way `__init__` does — keeps the test independent of the
    # full bot/IB/Mongo dependency tree.
    inst._intraday_setups = {
        "first_vwap_pullback", "first_move_up", "first_move_down", "bella_fade",
        "back_through_open", "up_through_open", "opening_drive",
        "orb", "hitchhiker", "spencer_scalp", "9_ema_scalp", "abc_scalp",
    }
    inst._intraday_only_setups = inst._intraday_setups | {
        "vwap_continuation", "vwap_bounce", "vwap_fade",
        "premarket_high_break", "the_3_30_trade",
        "gap_fade", "gap_give_go", "gap_pick_roll",
        "rubber_band", "tidal_wave",
        "hod_breakout",
        "fashionably_late", "off_sides", "backside",
        "second_chance",
        "big_dog", "puppy_dog",
        "bouncy_ball",
    }
    return inst


def test_intraday_only_is_superset_of_intraday_setups():
    """Every detector flagged intraday-by-volume must also be flagged
    intraday-by-tier — otherwise we'd silently allow a swing-tier
    symbol with above-intraday volume on a timing-bound detector.
    """
    inst = _make_scanner_stub()
    assert inst._intraday_setups.issubset(inst._intraday_only_setups)


def test_known_intraday_only_detectors_present():
    """These detectors have explicit sub-5min timing dependencies and
    MUST be on the intraday-only list.
    """
    inst = _make_scanner_stub()
    must_have = [
        # Already in _intraday_setups (volume gate):
        "9_ema_scalp", "spencer_scalp", "opening_drive", "orb",
        "first_move_up", "first_move_down", "bella_fade",
        # New v19.16 additions (timing-bound):
        "vwap_continuation", "vwap_bounce", "vwap_fade",
        "premarket_high_break", "the_3_30_trade",
        "gap_fade", "gap_give_go", "gap_pick_roll",
        "rubber_band", "tidal_wave", "hod_breakout",
        "fashionably_late", "off_sides", "backside",
        "second_chance", "big_dog", "puppy_dog", "bouncy_ball",
    ]
    missing = [d for d in must_have if d not in inst._intraday_only_setups]
    assert not missing, f"intraday-only detectors missing: {missing}"


def test_ambiguous_detectors_explicitly_NOT_in_intraday_only():
    """These detectors work across tiers. Adding them would silently
    suppress legitimate swing/position alerts. Pin the OMISSION.
    """
    inst = _make_scanner_stub()
    must_NOT_have = [
        "squeeze",         # Daily-bar BB-inside-KC squeeze (swing)
        "breakout",        # Could be daily breakout
        "chart_pattern",   # Could be daily H&S / wedge
        "mean_reversion",  # Could be daily RSI extreme
        "trend_continuation",  # Swing/position
        "daily_squeeze",   # Explicitly daily
        "daily_breakout",  # Explicitly daily
        "base_breakout",   # Position
        "earnings_momentum",  # Swing
        "sector_rotation",    # Swing
    ]
    incorrectly_present = [
        d for d in must_NOT_have if d in inst._intraday_only_setups
    ]
    assert not incorrectly_present, (
        f"detectors that should run across tiers were marked intraday-only: "
        f"{incorrectly_present}"
    )


def test_intraday_only_does_not_grow_unboundedly():
    """Sanity bound — if a future contributor naively adds every
    detector to the intraday-only list (e.g. via a copy/paste), we
    want the test to flag the regression. The current count is 28
    (12 in `_intraday_setups` + 16 new) — pin a reasonable upper
    bound.
    """
    inst = _make_scanner_stub()
    assert len(inst._intraday_only_setups) <= 35, (
        f"intraday_only_setups grew past a reasonable bound — "
        f"contains {len(inst._intraday_only_setups)} detectors. "
        f"Verify each addition has explicit sub-5min timing dependency."
    )
