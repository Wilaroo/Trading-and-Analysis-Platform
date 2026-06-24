"""v19.34.401 — MFE/MAE writer-fix regression tests.

Two bugs fixed:
  1. current_price<=0 corrupted mae_r to ~ -50R (guarded in position_manager).
  2. winner_capture > 1.0 from sparse-tick MFE under-sampling — excursion_floor
     now bounds mfe_r >= realized favorable / mae_r <= realized adverse, and the
     study clamps capture to <= 1.0 on mixed data.
"""
from services.trade_outcome_hygiene import excursion_floor
from services.mfe_mae_study import _summarize


def test_excursion_floor_long_winner():
    # entry 100, exit 105, stop 95 -> rps 5 -> realized +1R favorable.
    mfe_floor, mae_floor = excursion_floor("long", 100.0, 105.0, 95.0)
    assert mfe_floor == 1.0          # max(0, +1)
    assert mae_floor == 0.0          # min(0, +1)


def test_excursion_floor_long_loser():
    # entry 100, exit 96, stop 95 -> rps 5 -> realized -0.8R.
    mfe_floor, mae_floor = excursion_floor("long", 100.0, 96.0, 95.0)
    assert mfe_floor == 0.0
    assert mae_floor == -0.8


def test_excursion_floor_short_winner():
    # short entry 100, exit 95, stop 105 -> rps 5 -> +1R.
    mfe_floor, mae_floor = excursion_floor("short", 100.0, 95.0, 105.0)
    assert mfe_floor == 1.0
    assert mae_floor == 0.0


def test_excursion_floor_bad_prices_safe():
    assert excursion_floor("long", 0, 100, 95) == (0.0, 0.0)
    assert excursion_floor("long", 100, 0, 95) == (0.0, 0.0)


def test_winner_capture_clamped_when_mfe_undersampled():
    # winner realized +0.55R but tracked mfe only +0.30R (sparse ticks).
    # capture must clamp to 1.0, not 0.55/0.30 = 1.83.
    rows = [(0.55, 0.30, -0.1)]
    s = _summarize("scalp", rows)
    assert s["winner_capture"] == 1.0


def test_winner_capture_normal():
    rows = [(0.5, 1.0, -0.1)]   # kept half the run
    s = _summarize("scalp", rows)
    assert s["winner_capture"] == 0.5
