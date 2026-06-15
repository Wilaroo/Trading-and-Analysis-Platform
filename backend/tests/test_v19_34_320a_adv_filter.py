"""
test_v19_34_320a_adv_filter — verifies the pre-listing pollution filter
behaves correctly on the SPCX-shaped data confirmed by
diag_spcx_forensics.py on 2026-06-15.
"""
from datetime import datetime, timezone
from services.ib_historical_collector import IBHistoricalCollector


def _spcx_shape():
    """24 stale bars (Feb-Mar 2026, vol ~400) + 91-day gap + 1 IPO bar
    (Jun 12 2026, vol 227M). Newest-first."""
    dates_old = [
        datetime(2026, 3, d, tzinfo=timezone.utc) for d in range(13, 7, -1)
    ] + [
        datetime(2026, 2, d, tzinfo=timezone.utc) for d in range(28, 8, -1)
    ]
    dates_old = dates_old[:24]
    return (
        [datetime(2026, 6, 12, tzinfo=timezone.utc)] + dates_old,
        [227_267_555] + [400] * 24,
        [176.52]      + [22.0] * 24,
        [135.00]      + [21.8] * 24,
        [167.94]      + [22.0] * 24,
    )


def test_spcx_pollution_stripped():
    d, v, h, l, c = _spcx_shape()
    fd, fv, fh, fl, fc, meta = IBHistoricalCollector._filter_pre_listing_pollution(d, v, h, l, c)
    assert meta["filter_applied"] is True
    assert meta["removed_count"] == 24
    assert len(fd) == 1
    assert fv == [227_267_555]
    assert fc == [167.94]


def test_clean_series_passes_through():
    # consecutive daily bars, no big gap — must NOT trigger filter.
    dts = [datetime(2026, 6, d, tzinfo=timezone.utc) for d in range(12, 0, -1)]
    vols = [1_000_000 + i * 5_000 for i in range(len(dts))]
    fd, fv, fh, fl, fc, meta = IBHistoricalCollector._filter_pre_listing_pollution(
        dts, vols, vols, vols, vols)
    assert meta["filter_applied"] is False
    assert meta["removed_count"] == 0
    assert len(fd) == len(dts)


def test_short_series_no_filter():
    dts = [datetime(2026, 6, 12, tzinfo=timezone.utc),
           datetime(2026, 6, 11, tzinfo=timezone.utc)]
    fd, fv, fh, fl, fc, meta = IBHistoricalCollector._filter_pre_listing_pollution(
        dts, [100, 200], [1, 2], [1, 2], [1, 2])
    assert meta["filter_applied"] is False


def test_gap_without_volume_jump_passes_through():
    # 60-day gap but volumes similar on both sides → likely a real trading
    # pause, NOT a ticker recycle. Filter must remain silent.
    dts = [datetime(2026, 6, 12, tzinfo=timezone.utc),
           datetime(2026, 6, 11, tzinfo=timezone.utc),
           datetime(2026, 4, 10, tzinfo=timezone.utc),
           datetime(2026, 4,  9, tzinfo=timezone.utc)]
    vols = [500_000, 510_000, 480_000, 490_000]
    _, _, _, _, _, meta = IBHistoricalCollector._filter_pre_listing_pollution(
        dts, vols, vols, vols, vols)
    assert meta["filter_applied"] is False


def test_mixed_tz_input_does_not_crash():
    """Mongo BSON Date returns naive datetime via pymongo. ISO strings
    parsed via fromisoformat return tz-aware. Filter must accept both
    in the same series without throwing 'can't subtract offset-naive
    and offset-aware datetimes'.
    """
    from datetime import datetime
    # newest = naive (mimics pymongo BSON Date)
    # next   = tz-aware string (mimics legacy ISO-stored bars)
    dts = [
        datetime(2026, 6, 12),                          # naive
        "2026-03-13T00:00:00+00:00",                    # iso tz-aware
        "2026-03-12T00:00:00Z",                         # iso Z-style
        datetime(2026, 3, 11),                          # naive
    ]
    vols = [227_267_555, 200, 187, 1315]
    fd, fv, fh, fl, fc, meta = IBHistoricalCollector._filter_pre_listing_pollution(
        dts, vols, vols, vols, vols)
    # 91-day gap + huge vol jump → must trigger filter
    assert meta["filter_applied"] is True
    assert len(fd) == 1
    assert fv == [227_267_555]
