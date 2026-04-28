"""
Regression test for the operator's strategy time-window
reclassification shipped 2026-04-29 (afternoon-15d).

Operator explicitly classified setups into two profiles based on
real trading edge (NOT naming convention):

ALL-DAY (work any time during RTH 9:30-16:00 ET):
  big_dog, puppy_dog, spencer_scalp, backside, hitchhiker,
  fashionably_late, abc_scalp, first_vwap_pullback, time_of_day_fade,
  vwap_reclaim, vwap_rejection, bella_fade, breaking_news

MORNING-ONLY (only edge before ~11am ET):
  9_ema_scalp, opening_drive, orb, gap_give_go, first_move_up,
  first_move_down, back_through_open, gap_pick_roll, up_through_open

This test guards both the named profile constants AND the per-setup
mappings so any future drift (someone "tidying up" the time-windows
dict) is caught immediately.
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/app/backend")

from services.enhanced_scanner import (  # noqa: E402
    STRATEGY_TIME_WINDOWS, _RTH_ALL_DAY, _MORNING_ONLY, TimeWindow,
)


# Operator-stated classification (the source of truth).
ALL_DAY_SETUPS = frozenset({
    "big_dog", "puppy_dog", "spencer_scalp", "backside", "hitchhiker",
    "fashionably_late", "abc_scalp", "first_vwap_pullback",
    "time_of_day_fade", "vwap_reclaim", "vwap_rejection", "bella_fade",
    "breaking_news",
})

MORNING_ONLY_SETUPS = frozenset({
    "9_ema_scalp", "opening_drive", "orb", "gap_give_go",
    "first_move_up", "first_move_down", "back_through_open",
    "gap_pick_roll", "up_through_open",
})


def test_rth_all_day_profile_covers_full_session():
    """`_RTH_ALL_DAY` must include every intra-RTH TimeWindow so a
    setup classified all-day is never blocked during market hours.
    """
    expected = {
        TimeWindow.OPENING_AUCTION, TimeWindow.OPENING_DRIVE,
        TimeWindow.MORNING_MOMENTUM, TimeWindow.MORNING_SESSION,
        TimeWindow.LATE_MORNING, TimeWindow.MIDDAY,
        TimeWindow.AFTERNOON, TimeWindow.CLOSE,
    }
    assert set(_RTH_ALL_DAY) == expected, (
        "_RTH_ALL_DAY must cover every intra-RTH TimeWindow"
    )


def test_morning_only_profile_excludes_midday_afternoon_close():
    """`_MORNING_ONLY` must end at LATE_MORNING (11:30 ET buffer) and
    must NOT include MIDDAY / AFTERNOON / CLOSE.
    """
    excluded = {TimeWindow.MIDDAY, TimeWindow.AFTERNOON, TimeWindow.CLOSE}
    assert excluded.isdisjoint(set(_MORNING_ONLY)), (
        "_MORNING_ONLY must not include any post-lunch window"
    )
    assert TimeWindow.LATE_MORNING in _MORNING_ONLY, (
        "_MORNING_ONLY should extend through LATE_MORNING (~11:30 ET) "
        "as buffer for 'usually before 11am' rule"
    )


def test_all_day_setups_use_rth_all_day_profile():
    """Every operator-classified all-day setup must map to
    `_RTH_ALL_DAY`. Catches any future re-narrowing.
    """
    for setup in ALL_DAY_SETUPS:
        assert setup in STRATEGY_TIME_WINDOWS, (
            f"{setup} missing from STRATEGY_TIME_WINDOWS — operator classified it as all-day"
        )
        assert STRATEGY_TIME_WINDOWS[setup] == _RTH_ALL_DAY, (
            f"{setup} expected _RTH_ALL_DAY profile, "
            f"got {STRATEGY_TIME_WINDOWS[setup]}"
        )


def test_morning_only_setups_use_morning_only_profile():
    """Every operator-classified morning-only setup must map to
    `_MORNING_ONLY`. Catches accidental promotions to all-day that
    would let edgeless trades fire in the afternoon.
    """
    for setup in MORNING_ONLY_SETUPS:
        assert setup in STRATEGY_TIME_WINDOWS, (
            f"{setup} missing from STRATEGY_TIME_WINDOWS — operator classified it as morning-only"
        )
        assert STRATEGY_TIME_WINDOWS[setup] == _MORNING_ONLY, (
            f"{setup} expected _MORNING_ONLY profile, "
            f"got {STRATEGY_TIME_WINDOWS[setup]}"
        )


def test_no_overlap_between_classifications():
    """A setup must not appear in BOTH operator lists. Sanity guard
    against a future operator note that contradicts itself.
    """
    overlap = ALL_DAY_SETUPS & MORNING_ONLY_SETUPS
    assert not overlap, f"Setup(s) classified as both all-day AND morning-only: {overlap}"
