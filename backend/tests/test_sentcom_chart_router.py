"""
Tests for the SentCom chart router's indicator math.

These are pure-function tests — no FastAPI, no DB, no network.
They lock the behaviour of EMA / VWAP / rolling mean+std so the
frontend chart overlays never silently regress.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta

import pytest

from routers.sentcom_chart import (
    _ema,
    _rolling_mean_std,
    _vwap,
    _to_utc_seconds,
    _session_key,
    _as_series,
)


# ─── _to_utc_seconds ────────────────────────────────────────────────────────

def test_to_utc_seconds_accepts_iso_string():
    assert _to_utc_seconds("2026-04-23T09:30:00+00:00") == 1776936600


def test_to_utc_seconds_accepts_z_suffix():
    assert _to_utc_seconds("2026-04-23T09:30:00Z") == 1776936600


def test_to_utc_seconds_accepts_seconds_int():
    assert _to_utc_seconds(1776936600) == 1776936600


def test_to_utc_seconds_accepts_millis_int():
    assert _to_utc_seconds(1776936600000) == 1776936600


def test_to_utc_seconds_accepts_naive_datetime_as_utc():
    assert _to_utc_seconds(datetime(2026, 4, 23, 9, 30)) == 1776936600


def test_to_utc_seconds_returns_none_for_garbage():
    assert _to_utc_seconds("not a date") is None
    assert _to_utc_seconds(None) is None


# ─── _ema ───────────────────────────────────────────────────────────────────

def test_ema_returns_none_until_span_reached():
    out = _ema([1.0, 2.0, 3.0], span=5)
    assert all(v is None for v in out)
    assert len(out) == 3


def test_ema_seed_matches_simple_mean_of_first_span():
    out = _ema([2.0, 4.0, 6.0, 8.0, 10.0], span=5)
    assert out[:4] == [None, None, None, None]
    assert out[4] == pytest.approx(6.0)  # simple mean of first 5 = seed


def test_ema_continues_from_seed_with_alpha_2_over_span_plus_1():
    # span=3, so alpha=0.5; seed = mean(1,2,3) = 2.0
    # next: 0.5*4 + 0.5*2 = 3.0; next: 0.5*5 + 0.5*3 = 4.0
    out = _ema([1.0, 2.0, 3.0, 4.0, 5.0], span=3)
    assert out[2] == pytest.approx(2.0)
    assert out[3] == pytest.approx(3.0)
    assert out[4] == pytest.approx(4.0)


def test_ema_zero_or_negative_span_returns_nones():
    assert _ema([1.0, 2.0, 3.0], span=0) == [None, None, None]
    assert _ema([1.0, 2.0, 3.0], span=-1) == [None, None, None]


# ─── _rolling_mean_std ──────────────────────────────────────────────────────

def test_rolling_mean_and_std_produce_correct_values_at_window_edges():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    means, stds = _rolling_mean_std(vals, window=3)
    assert means[:2] == [None, None]
    assert means[2] == pytest.approx(2.0)   # mean(1,2,3)
    assert means[3] == pytest.approx(3.0)   # mean(2,3,4)
    assert means[4] == pytest.approx(4.0)   # mean(3,4,5)
    # population std of {1,2,3} = sqrt(2/3) ≈ 0.8165
    assert stds[2] == pytest.approx(math.sqrt(2 / 3), rel=1e-6)


def test_rolling_std_never_negative_even_with_fp_noise():
    # Repeated values → std should be exactly 0, never a tiny negative.
    vals = [5.0] * 10
    means, stds = _rolling_mean_std(vals, window=5)
    for s in stds[4:]:
        assert s is not None and s >= 0.0


def test_rolling_returns_all_nones_when_window_larger_than_input():
    means, stds = _rolling_mean_std([1.0, 2.0], window=5)
    assert means == [None, None]
    assert stds == [None, None]


# ─── _vwap ──────────────────────────────────────────────────────────────────

def _mk_bar(ts: int, h: float, lo: float, c: float, v: float) -> dict:
    return {"time": ts, "open": c, "high": h, "low": lo, "close": c, "volume": v}


def test_vwap_non_session_is_cumulative():
    bars = [
        _mk_bar(0,           10, 10, 10, 100),
        _mk_bar(86_400,      20, 20, 20, 100),
        _mk_bar(86_400 * 2,  30, 30, 30, 100),
    ]
    out = _vwap(bars, per_session=False)
    # VWAP[0] = 10 ; VWAP[1] = (10+20)/2 = 15 ; VWAP[2] = (10+20+30)/3 = 20
    assert out == pytest.approx([10.0, 15.0, 20.0])


def test_vwap_per_session_resets_each_calendar_day():
    day1_930 = int(datetime(2026, 4, 23, 13, 30, tzinfo=timezone.utc).timestamp())
    day1_945 = day1_930 + 15 * 60
    day2_930 = day1_930 + 86_400
    bars = [
        _mk_bar(day1_930, 10, 10, 10, 100),
        _mk_bar(day1_945, 20, 20, 20, 100),
        _mk_bar(day2_930, 100, 100, 100, 50),
    ]
    out = _vwap(bars, per_session=True)
    assert out[0] == pytest.approx(10.0)
    assert out[1] == pytest.approx(15.0)       # day-1 still accumulating
    assert out[2] == pytest.approx(100.0)      # day-2 reset


def test_vwap_zero_volume_bar_yields_none_then_resumes():
    bars = [
        _mk_bar(0, 10, 10, 10, 0),              # zero volume at start
        _mk_bar(60, 20, 20, 20, 100),
    ]
    out = _vwap(bars, per_session=False)
    assert out[0] is None
    assert out[1] == pytest.approx(20.0)


# ─── _as_series ─────────────────────────────────────────────────────────────

def test_as_series_drops_none_values():
    times = [1, 2, 3, 4]
    values = [None, None, 10.5, 11.0]
    out = _as_series(times, values)
    assert out == [
        {"time": 3, "value": 10.5},
        {"time": 4, "value": 11.0},
    ]


def test_as_series_handles_empty_input():
    assert _as_series([], []) == []


# ─── _session_key ───────────────────────────────────────────────────────────

def test_session_key_groups_same_utc_date():
    a = int(datetime(2026, 4, 23, 13, 30, tzinfo=timezone.utc).timestamp())
    b = int(datetime(2026, 4, 23, 19, 59, tzinfo=timezone.utc).timestamp())
    assert _session_key(a) == _session_key(b) == "2026-04-23"


def test_session_key_differs_across_utc_midnight():
    a = int(datetime(2026, 4, 23, 23, 30, tzinfo=timezone.utc).timestamp())
    b = int((datetime(2026, 4, 23, 23, 30, tzinfo=timezone.utc) + timedelta(hours=1)).timestamp())
    assert _session_key(a) != _session_key(b)


# ─── _classify_model_mode (scorecard) ───────────────────────────────────────

from routers.sentcom_chart import _classify_model_mode  # noqa: E402


def test_classify_missing_when_no_metrics():
    assert _classify_model_mode(None) == "MISSING"
    assert _classify_model_mode({}) == "MISSING"


def test_classify_healthy_when_both_floors_met():
    m = {"recall_up": 0.15, "recall_down": 0.20}
    assert _classify_model_mode(m) == "HEALTHY"


def test_classify_mode_b_when_both_collapsed():
    # Both < 0.05 — the useless-model case (old active direction_predictor_5min
    # pre-promotion: recall_up=0.069 was just above 0.05, so reproduce the
    # fully-collapsed state).
    m = {"recall_up": 0.01, "recall_down": 0.0}
    assert _classify_model_mode(m) == "MODE_B"


def test_classify_mode_c_when_one_side_usable():
    # v20260422_181416 post-promote: UP fixed, DOWN still at 0.
    m = {"recall_up": 0.597, "recall_down": 0.0}
    assert _classify_model_mode(m) == "MODE_C"


def test_classify_mode_c_when_up_just_above_collapse_but_below_floor():
    m = {"recall_up": 0.07, "recall_down": 0.0}
    assert _classify_model_mode(m) == "MODE_C"


def test_classify_handles_garbage_metrics_as_missing():
    m = {"recall_up": "not a number"}
    assert _classify_model_mode(m) == "MISSING"
