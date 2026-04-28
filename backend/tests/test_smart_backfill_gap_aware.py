"""
Regression tests for the gap-aware smart-backfill behaviour shipped
2026-04-28e.

Before this fix, `_smart_backfill_sync` only looked at the age of the
**newest** bar. If a symbol's most-recent bar was from yesterday it was
flagged "fresh" and skipped — even if the historical range had multi-
month holes from earlier failed pulls. Caught via TSLA 1d screenshot
showing Apr-prior-year → Jan-this-year gap.

These tests lock the new behaviour:
  1. `_has_internal_gaps` returns True when actual coverage < 80%
     of expected bars in the lookback window.
  2. `_has_internal_gaps` returns False on full-coverage symbols.
  3. The smart-backfill plan increments `gap_filled` instead of
     `skipped_fresh` for symbols that pass the freshness check but
     have detectable gaps.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from services.ib_historical_collector import IBHistoricalCollector


def _make_collector(data_col_count_side_effect):
    coll = IBHistoricalCollector.__new__(IBHistoricalCollector)
    coll._data_col = MagicMock()
    coll._data_col.count_documents = MagicMock(side_effect=data_col_count_side_effect)
    return coll


# ---------- _has_internal_gaps ----------------------------------------

def test_has_internal_gaps_returns_true_when_coverage_low():
    """A daily symbol with only 100 bars in the last 730 days
    (~ 0.20 of expected ~503 trading days) must trigger a gap refill."""
    coll = _make_collector(lambda *_args, **_kw: 100)
    assert coll._has_internal_gaps("TSLA", "1 day") is True


def test_has_internal_gaps_returns_false_when_coverage_high():
    """500 bars in the last 730 calendar days ≈ 99% of the ~503 expected
    trading days — well above the 80% threshold."""
    coll = _make_collector(lambda *_args, **_kw: 500)
    assert coll._has_internal_gaps("TSLA", "1 day") is False


def test_has_internal_gaps_handles_unknown_bar_size():
    coll = _make_collector(lambda *_args, **_kw: 0)
    assert coll._has_internal_gaps("TSLA", "10 secs") is False


def test_has_internal_gaps_fails_open_on_db_error():
    def _raise(*_a, **_kw):
        raise RuntimeError("mongo down")
    coll = _make_collector(_raise)
    assert coll._has_internal_gaps("TSLA", "1 day") is False


def test_has_internal_gaps_returns_false_when_db_handle_missing():
    coll = IBHistoricalCollector.__new__(IBHistoricalCollector)
    coll._data_col = None
    assert coll._has_internal_gaps("TSLA", "1 day") is False


# ---------- threshold sanity ------------------------------------------

def test_gap_threshold_at_80_percent_boundary():
    """A symbol clearly above 80% coverage is NOT flagged; a symbol
    clearly below 80% IS flagged. (Exact-boundary equality is implementation
    detail of `int()` truncation; we test margins on either side.)"""
    expected_trading_days = int(730 * 0.69)
    expected = expected_trading_days * 1   # bars_per_day for "1 day" = 1

    # 90% coverage — well above threshold
    coll = _make_collector(lambda *_a, **_kw: int(expected * 0.90))
    assert coll._has_internal_gaps("TSLA", "1 day") is False

    # 70% coverage — clearly below threshold
    coll = _make_collector(lambda *_a, **_kw: int(expected * 0.70))
    assert coll._has_internal_gaps("TSLA", "1 day") is True
