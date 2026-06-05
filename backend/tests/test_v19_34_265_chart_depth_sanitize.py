"""
v19.34.265 — Chart depth bump + transient bad-tick sanitization.

Covers the two behaviours shipped in v265:
  • `_sanitize_intraday_bars` clamps a lone corrupt IB print (e.g. a $36
    tick on a $260 stock) back into a ±50% band around the LOCAL median
    close, while leaving genuine trends untouched.
  • `_compute_volume_profile` clips its lo/hi range so one bad tick can't
    collapse bin_size and produce a garbage POC.

Run on the DGX:  .venv/bin/python -m pytest backend/tests/test_v19_34_265_chart_depth_sanitize.py -q
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from routers.sentcom_chart import _sanitize_intraday_bars  # noqa: E402
from services.smart_levels_service import _compute_volume_profile  # noqa: E402


def _clean_bars(price=260.0, n=20):
    return [
        {"time": i, "open": price, "high": price + 0.5,
         "low": price - 0.5, "close": price, "volume": 1000}
        for i in range(n)
    ]


def test_bad_tick_low_is_clamped():
    bars = _clean_bars()
    bars[10] = {"time": 10, "open": 260.0, "high": 260.2,
                "low": 36.0, "close": 260.0, "volume": 1000}
    out, fixed = _sanitize_intraday_bars([dict(b) for b in bars])
    assert fixed == 1
    # ref ~= 260, lower bound = 260 * 0.5 = 130
    assert out[10]["low"] >= 130.0
    assert out[10]["low"] <= out[10]["open"]  # OHLC invariant preserved


def test_genuine_trend_is_untouched():
    trend = [
        {"time": i, "open": 100 + i, "high": 100.5 + i,
         "low": 99.5 + i, "close": 100 + i, "volume": 500}
        for i in range(20)
    ]
    _, fixed = _sanitize_intraday_bars([dict(b) for b in trend])
    assert fixed == 0


def test_too_few_bars_no_op():
    bars = _clean_bars(n=2)
    out, fixed = _sanitize_intraday_bars([dict(b) for b in bars])
    assert fixed == 0 and len(out) == 2


def test_volume_profile_poc_survives_bad_tick():
    vbars = [{"low": 259.5, "high": 260.5, "close": 260.0, "volume": 1000}
             for _ in range(20)]
    vbars[10] = {"low": 36.0, "high": 260.0, "close": 260.0, "volume": 1000}
    vp = _compute_volume_profile(vbars, 40)
    assert vp["poc_price"] is not None
    assert 255.0 < vp["poc_price"] < 265.0
    # lo must be clipped to the median-anchored floor, not the $36 tick
    assert vp["lo"] >= 260.0 * 0.4 - 0.01
