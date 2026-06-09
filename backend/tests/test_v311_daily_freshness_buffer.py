"""v19.34.311 — daily/weekly freshness now gets the weekend/overnight buffer.

Regression guard for the 'every Monday is stale on 1 day' false-flag: a Friday
daily bar viewed Monday evening is ~3.97 days old and was tripping the hard
3-day daily threshold."""
from services.backfill_readiness_service import _adjusted_stale_days, STALE_DAYS


def test_daily_gets_overnight_buffer_clears_monday_night():
    # Monday ~21:00 ET: state='overnight'. Friday daily bar = ~3.97d.
    thr = _adjusted_stale_days("1 day", "overnight")
    assert thr == STALE_DAYS["1 day"] + 1  # 3 -> 4
    assert 3.97 <= thr  # the real Monday-night age now passes


def test_daily_gets_weekend_buffer():
    assert _adjusted_stale_days("1 day", "weekend") == STALE_DAYS["1 day"] + 3  # 3 -> 6


def test_weekly_gets_buffer_too():
    assert _adjusted_stale_days("1 week", "overnight") == STALE_DAYS["1 week"] + 1
    assert _adjusted_stale_days("1 week", "weekend") == STALE_DAYS["1 week"] + 3


def test_rth_unbuffered_unchanged():
    # During RTH no buffer is applied — base thresholds intact for all tfs.
    assert _adjusted_stale_days("1 day", "rth") == STALE_DAYS["1 day"]
    assert _adjusted_stale_days("1 min", "rth") == STALE_DAYS["1 min"]


def test_intraday_buffer_preserved():
    # Existing intraday behavior must be unchanged.
    assert _adjusted_stale_days("1 min", "weekend") == STALE_DAYS["1 min"] + 3
    assert _adjusted_stale_days("5 mins", "overnight") == STALE_DAYS["5 mins"] + 1


def test_real_multiday_gap_still_flags():
    # A genuine 8-day-old daily bar must still be stale even with weekend buffer.
    thr = _adjusted_stale_days("1 day", "weekend")  # 6
    assert 8.0 > thr  # 8-day gap exceeds buffered threshold -> still flagged
