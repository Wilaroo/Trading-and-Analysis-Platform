"""
Unit tests for the v19.34.311 daily-anchored, timestamp-aligned TFT features.
Guards the fix for the majority-class collapse (feature/label misalignment).
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
        bars.append({"close": float(p), "high": float(p * 1.01), "low": float(p * 0.99),
                     "volume": 1_000_000, "date": day0 + timedelta(days=i)})
    return bars


def _intraday_bars(n, start_price=100.0, t0=None, step_min=5):
    t0 = t0 or datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
    bars = []
    p = start_price
    rng = np.random.default_rng(11)
    for i in range(n):
        p *= (1 + rng.normal(0, 0.002))
        bars.append({"close": float(p), "high": float(p * 1.002), "low": float(p * 0.998),
                     "volume": 50_000, "date": t0 + timedelta(minutes=step_min * i)})
    return bars


def test_shape_and_daily_axis_alignment():
    m = TFTModel()
    daily = _daily_bars(300)
    out = m.extract_multi_tf_features("TEST", {"1 day": daily})
    assert out is not None and out.shape == (len(daily) - 20, TOTAL_INPUT_DIM)
    for p, tf in enumerate(TFT_TIMEFRAMES):
        block = out[:, p * FEATURES_PER_TF:(p + 1) * FEATURES_PER_TF]
        if tf == "1 day":
            assert np.any(block != 0.0)
        else:
            assert np.all(block == 0.0)
    print("PASS: shape + daily-axis alignment + zero-padding")


def test_scale_free():
    m = TFTModel()
    cheap = m.extract_multi_tf_features("CHEAP", {"1 day": _daily_bars(300, 5.0)})
    pricey = m.extract_multi_tf_features("PRICEY", {"1 day": _daily_bars(300, 900.0)})
    dp = TFT_TIMEFRAMES.index("1 day")
    c = cheap[:, dp * FEATURES_PER_TF:(dp + 1) * FEATURES_PER_TF]
    p = pricey[:, dp * FEATURES_PER_TF:(dp + 1) * FEATURES_PER_TF]
    ratio = (np.nanmax(np.abs(p)) + 1e-9) / (np.nanmax(np.abs(c)) + 1e-9)
    assert 0.05 < ratio < 20, f"scales diverge with price (ratio={ratio:.2f})"
    print(f"PASS: scale-free (ratio={ratio:.2f})")


def test_as_of_no_lookahead():
    m = TFTModel()
    daily = _daily_bars(1600, day0=datetime(2020, 1, 1, tzinfo=timezone.utc))
    intraday = _intraday_bars(2000, t0=datetime(2024, 1, 2, 9, 30, tzinfo=timezone.utc))
    out = m.extract_multi_tf_features("TEST", {"1 day": daily, "5 mins": intraday})
    p5 = TFT_TIMEFRAMES.index("5 mins")
    blk = out[:, p5 * FEATURES_PER_TF:(p5 + 1) * FEATURES_PER_TF]
    dates = [b["date"] for b in daily[20:]]
    first = intraday[0]["date"]
    pre = [i for i, d in enumerate(dates) if d < first]
    post = [i for i, d in enumerate(dates) if d >= first]
    assert pre and np.all(blk[pre] == 0.0), "look-ahead leak"
    assert post and np.any(blk[post] != 0.0), "intraday not populated post-history"
    print(f"PASS: as-of join ({len(pre)} pre zeroed, {len(post)} post filled)")


def test_none_guards():
    m = TFTModel()
    assert m.extract_multi_tf_features("X", {"1 day": _daily_bars(10)}) is None
    assert m.extract_multi_tf_features("X", {}) is None
    print("PASS: None guards")


if __name__ == "__main__":
    test_shape_and_daily_axis_alignment()
    test_scale_free()
    test_as_of_no_lookahead()
    test_none_guards()
    print("\nALL TFT ALIGNMENT TESTS PASSED")
