"""
Unit tests for the rewritten TFT extract_multi_tf_features (daily-anchored,
timestamp-aligned, scale-free). These guard the fix for the majority-class
collapse caused by feature/label misalignment.
"""
import os
import sys
from datetime import datetime, timezone, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.ai_modules.temporal_fusion_transformer import (
    TFTModel, TFT_TIMEFRAMES, FEATURES_PER_TF, TOTAL_INPUT_DIM,
)


def _daily_bars(n, start_price=100.0, day0=None):
    day0 = day0 or datetime(2020, 1, 1, tzinfo=timezone.utc)
    bars = []
    p = start_price
    rng = np.random.default_rng(7)
    for i in range(n):
        p *= (1 + rng.normal(0, 0.01))
        bars.append({
            "close": float(p), "high": float(p * 1.01), "low": float(p * 0.99),
            "volume": 1_000_000, "date": day0 + timedelta(days=i),
        })
    return bars


def _intraday_bars(n, start_price=100.0, t0=None, step_min=5):
    t0 = t0 or datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
    bars = []
    p = start_price
    rng = np.random.default_rng(11)
    for i in range(n):
        p *= (1 + rng.normal(0, 0.002))
        bars.append({
            "close": float(p), "high": float(p * 1.002), "low": float(p * 0.998),
            "volume": 50_000, "date": t0 + timedelta(minutes=step_min * i),
        })
    return bars


def test_shape_and_daily_axis_alignment():
    m = TFTModel()
    daily = _daily_bars(300)
    out = m.extract_multi_tf_features("TEST", {"1 day": daily})
    assert out is not None
    # Daily-anchored: one row per daily bar from index 20 onward
    assert out.shape == (len(daily) - 20, TOTAL_INPUT_DIM)
    # Daily-only: intraday blocks must be all zeros
    day_pos = TFT_TIMEFRAMES.index("1 day")
    for p, tf in enumerate(TFT_TIMEFRAMES):
        block = out[:, p * FEATURES_PER_TF:(p + 1) * FEATURES_PER_TF]
        if tf == "1 day":
            assert np.any(block != 0.0), "daily block should be populated"
        else:
            assert np.all(block == 0.0), f"{tf} block should be zero (no intraday data)"
    print("PASS: shape + daily-axis alignment + zero-padding")


def test_scale_free_no_raw_price_blowup():
    """High-priced and low-priced symbols must produce comparable feature scales."""
    m = TFTModel()
    cheap = m.extract_multi_tf_features("CHEAP", {"1 day": _daily_bars(300, start_price=5.0)})
    pricey = m.extract_multi_tf_features("PRICEY", {"1 day": _daily_bars(300, start_price=900.0)})
    day_pos = TFT_TIMEFRAMES.index("1 day")
    c = cheap[:, day_pos * FEATURES_PER_TF:(day_pos + 1) * FEATURES_PER_TF]
    p = pricey[:, day_pos * FEATURES_PER_TF:(day_pos + 1) * FEATURES_PER_TF]
    # Max absolute feature value should be the same order of magnitude
    # regardless of price level (the old raw-price feat[10] broke this).
    assert np.nanmax(np.abs(c)) < 1e4 and np.nanmax(np.abs(p)) < 1e4
    ratio = (np.nanmax(np.abs(p)) + 1e-9) / (np.nanmax(np.abs(c)) + 1e-9)
    assert 0.05 < ratio < 20, f"feature scales diverge with price level (ratio={ratio:.2f})"
    print(f"PASS: features are scale-free (price-level ratio={ratio:.2f})")


def test_intraday_as_of_join_no_lookahead():
    """Intraday block for daily date D must equal the last intraday bar <= D."""
    m = TFTModel()
    # Daily history spans 2020..; intraday only covers Jan 2024 onward.
    daily = _daily_bars(1600, day0=datetime(2020, 1, 1, tzinfo=timezone.utc))  # ~through 2024
    intraday = _intraday_bars(2000, t0=datetime(2024, 1, 2, 9, 30, tzinfo=timezone.utc), step_min=5)
    out = m.extract_multi_tf_features("TEST", {"1 day": daily, "5 mins": intraday})
    assert out is not None
    p5 = TFT_TIMEFRAMES.index("5 mins")
    blk = out[:, p5 * FEATURES_PER_TF:(p5 + 1) * FEATURES_PER_TF]

    daily_dates = [b["date"] for b in daily[20:]]  # aligned to rows
    first_intraday = intraday[0]["date"]
    # Rows whose daily date is BEFORE any intraday bar must be zero (no look-ahead)
    pre = [i for i, d in enumerate(daily_dates) if d < first_intraday]
    assert pre, "expected some daily rows before intraday history starts"
    assert np.all(blk[pre] == 0.0), "look-ahead leak: intraday filled before its history begins"
    # Rows after intraday starts should be populated
    post = [i for i, d in enumerate(daily_dates) if d >= first_intraday]
    assert post and np.any(blk[post] != 0.0), "intraday block not populated after history begins"
    print(f"PASS: as-of join correct ({len(pre)} pre-rows zeroed, {len(post)} post-rows filled)")


def test_too_few_daily_returns_none():
    m = TFTModel()
    assert m.extract_multi_tf_features("X", {"1 day": _daily_bars(10)}) is None
    assert m.extract_multi_tf_features("X", {}) is None
    print("PASS: insufficient data returns None")


if __name__ == "__main__":
    test_shape_and_daily_axis_alignment()
    test_scale_free_no_raw_price_blowup()
    test_intraday_as_of_join_no_lookahead()
    test_too_few_daily_returns_none()
    print("\nALL TFT ALIGNMENT TESTS PASSED")
