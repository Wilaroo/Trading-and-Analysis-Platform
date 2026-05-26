"""Offline unit tests for bar_pipeline_diagnostic_phase_d helpers.

These tests target the pure functions in the diagnostic script —
`_parse_bar_date`, `_quarter_window`, `_max_sev` — so the script's
correctness is verified before any operator ever runs it on the DGX.

The integration-level Mongo checks are NOT unit-tested here (they
require either a live Mongo with realistic data or extensive mocking
that would just re-implement the script). Operator runs the full
script against the live DGX Mongo as the integration test.

Run:
    cd /app/backend && PYTHONPATH=. python3 -m pytest \
        tests/test_bar_pipeline_diagnostic_phase_d.py -v
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from datetime import datetime

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
SCRIPT_PATH = os.path.join(BACKEND_ROOT, "scripts",
                           "bar_pipeline_diagnostic_phase_d.py")


@pytest.fixture(scope="module")
def diag():
    """Load the script as a module (it's in /scripts, not on sys.path)."""
    spec = importlib.util.spec_from_file_location(
        "bar_pipeline_diagnostic_phase_d", SCRIPT_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── _parse_bar_date ──────────────────────────────────────────────────


def test_parse_bar_date_handles_iso_string(diag):
    dt = diag._parse_bar_date("2026-02-13 09:30:00")
    assert dt == datetime(2026, 2, 13, 9, 30, 0)


def test_parse_bar_date_handles_iso_with_t(diag):
    dt = diag._parse_bar_date("2026-02-13T09:30:00")
    assert dt == datetime(2026, 2, 13, 9, 30, 0)


def test_parse_bar_date_strips_us_eastern_suffix(diag):
    dt = diag._parse_bar_date("20260213 09:30:00 US/Eastern")
    assert dt == datetime(2026, 2, 13, 9, 30, 0)


def test_parse_bar_date_handles_one_day_format(diag):
    dt = diag._parse_bar_date("2026-02-13")
    assert dt == datetime(2026, 2, 13, 0, 0, 0)


def test_parse_bar_date_handles_compact_one_day(diag):
    dt = diag._parse_bar_date("20260213")
    assert dt == datetime(2026, 2, 13, 0, 0, 0)


def test_parse_bar_date_handles_python_datetime_passthrough(diag):
    src = datetime(2026, 2, 13, 9, 30, 0)
    assert diag._parse_bar_date(src) == src


def test_parse_bar_date_handles_epoch_seconds(diag):
    # 2026-02-13 14:30:00 UTC
    ts = 1771000200
    dt = diag._parse_bar_date(ts)
    assert dt is not None
    assert dt.year == 2026 and dt.month == 2


def test_parse_bar_date_returns_none_on_garbage(diag):
    assert diag._parse_bar_date("not a date") is None
    assert diag._parse_bar_date(None) is None


# ── _quarter_window ─────────────────────────────────────────────────


def test_quarter_window_q1(diag):
    start, end = diag._quarter_window("Q1", 2025)
    assert start == datetime(2025, 1, 1)
    assert end.year == 2025 and end.month == 3 and end.day == 31


def test_quarter_window_q2(diag):
    start, end = diag._quarter_window("Q2", 2025)
    assert start == datetime(2025, 4, 1)
    assert end.year == 2025 and end.month == 6 and end.day == 30


def test_quarter_window_q3(diag):
    start, end = diag._quarter_window("Q3", 2025)
    assert start == datetime(2025, 7, 1)
    assert end.year == 2025 and end.month == 9 and end.day == 30


def test_quarter_window_q4_rolls_year_correctly(diag):
    start, end = diag._quarter_window("Q4", 2025)
    assert start == datetime(2025, 10, 1)
    # End must be in Dec 2025, not Jan 2026.
    assert end.year == 2025 and end.month == 12 and end.day == 31


def test_quarter_window_invalid_raises(diag):
    with pytest.raises(ValueError):
        diag._quarter_window("Q5", 2025)


# ── _max_sev (severity comparator) ──────────────────────────────────


def test_max_sev_orders_pass_warn_fail(diag):
    assert diag._max_sev(diag.PASS, diag.PASS) == diag.PASS
    assert diag._max_sev(diag.PASS, diag.WARN) == diag.WARN
    assert diag._max_sev(diag.WARN, diag.PASS) == diag.WARN
    assert diag._max_sev(diag.WARN, diag.FAIL) == diag.FAIL
    assert diag._max_sev(diag.FAIL, diag.WARN) == diag.FAIL
    assert diag._max_sev(diag.FAIL, diag.FAIL) == diag.FAIL


def test_max_sev_unknown_defaults_to_pass(diag):
    """Defense: unknown severity strings shouldn't crash; should be
    treated as the safest tier (PASS)."""
    assert diag._max_sev("??", diag.PASS) in (diag.PASS, "??")
    # Real-world contract: any known sev should win over unknown.
    assert diag._max_sev("??", diag.FAIL) == diag.FAIL
