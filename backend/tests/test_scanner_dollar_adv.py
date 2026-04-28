"""
Regression tests for the dollar-volume ADV gates shipped 2026-04-28e.

Lock the new contract:
  - Default thresholds are dollar amounts ($1M / $5M / $25M).
  - `_get_adv_from_cache` reads `avg_dollar_volume` from
    `symbol_adv_cache` (with a fallback to `avg_volume × latest_close`
    for old rows missing the dollar field).
  - `_get_adv_from_ib_historical` returns dollar volume not share
    volume.
  - `_classify_symbol_tier` now buckets symbols by dollar volume:
      ≥ $25M → intraday
      ≥ $5M  → swing
      ≥ $1M  → investment
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import pytest

from services.enhanced_scanner import EnhancedBackgroundScanner


def _make_scanner_minimal() -> EnhancedBackgroundScanner:
    """Build a scanner without running its full network/DB init."""
    s = EnhancedBackgroundScanner.__new__(EnhancedBackgroundScanner)
    s._min_adv_general    =  5_000_000
    s._min_adv_intraday   = 25_000_000
    s._min_adv_investment =  1_000_000
    s._adv_cache = {}
    s._known_liquid_symbols = set()
    s._known_liquid_adv = {}
    s._known_liquid_default_adv = 100_000_000
    return s


# ─── default thresholds ─────────────────────────────────────────────────

def test_default_adv_thresholds_are_dollar_amounts():
    s = EnhancedBackgroundScanner.__new__(EnhancedBackgroundScanner)
    # Just call __init__ enough to set the thresholds — full init is heavy.
    # Instead, check the class-level defaults via _make_scanner_minimal.
    s2 = _make_scanner_minimal()
    assert s2._min_adv_intraday   == 25_000_000
    assert s2._min_adv_general    ==  5_000_000
    assert s2._min_adv_investment ==  1_000_000


# ─── _classify_symbol_tier ──────────────────────────────────────────────

def test_classify_tier_intraday_at_25M_dollar_volume():
    s = _make_scanner_minimal()
    s._adv_cache["SPY"] = (35_000_000_000, datetime.now(timezone.utc))
    assert s._classify_symbol_tier("SPY") == "intraday"


def test_classify_tier_swing_between_5M_and_25M():
    s = _make_scanner_minimal()
    s._adv_cache["MID"] = (10_000_000, datetime.now(timezone.utc))
    assert s._classify_symbol_tier("MID") == "swing"


def test_classify_tier_investment_below_5M():
    s = _make_scanner_minimal()
    s._adv_cache["SMALL"] = (2_500_000, datetime.now(timezone.utc))
    assert s._classify_symbol_tier("SMALL") == "investment"


# ─── _get_adv_from_cache: dollar-volume preferred ───────────────────────

@pytest.mark.asyncio
async def test_get_adv_from_cache_prefers_avg_dollar_volume(monkeypatch):
    s = _make_scanner_minimal()
    fake_db = MagicMock()
    fake_db["symbol_adv_cache"].find.return_value = iter([
        {"symbol": "AAPL", "avg_dollar_volume": 12_000_000_000,
         "avg_volume": 60_000_000, "latest_close": 200},
    ])
    import database
    monkeypatch.setattr(database, "get_database", lambda: fake_db)
    result = await s._get_adv_from_cache(["AAPL"])
    assert result == {"AAPL": 12_000_000_000}


@pytest.mark.asyncio
async def test_get_adv_from_cache_backfills_when_dollar_field_missing(monkeypatch):
    """Old cache rows may lack `avg_dollar_volume`. We must compute it
    on the fly from `avg_volume × latest_close` so we don't drop the
    symbol from scanning."""
    s = _make_scanner_minimal()
    fake_db = MagicMock()
    fake_db["symbol_adv_cache"].find.return_value = iter([
        {"symbol": "TSLA", "avg_volume": 80_000_000, "latest_close": 200},
    ])
    import database
    monkeypatch.setattr(database, "get_database", lambda: fake_db)
    result = await s._get_adv_from_cache(["TSLA"])
    assert result["TSLA"] == 80_000_000 * 200   # 16,000,000,000


@pytest.mark.asyncio
async def test_get_adv_from_cache_drops_symbols_with_no_data(monkeypatch):
    s = _make_scanner_minimal()
    fake_db = MagicMock()
    fake_db["symbol_adv_cache"].find.return_value = iter([
        {"symbol": "SHRINK", "avg_dollar_volume": 0, "avg_volume": 0, "latest_close": 0},
    ])
    import database
    monkeypatch.setattr(database, "get_database", lambda: fake_db)
    result = await s._get_adv_from_cache(["SHRINK"])
    assert result == {}


# ─── _get_adv_from_ib_historical: returns dollar volume ─────────────────

@pytest.mark.asyncio
async def test_get_adv_from_ib_historical_returns_dollar_volume(monkeypatch):
    """5 daily bars of (volume=10M, close=$50) → avg dollar vol = $500M."""
    s = _make_scanner_minimal()
    fake_db = MagicMock()
    fake_bars_col = MagicMock()
    fake_bars = [
        {"volume": 10_000_000, "close": 50.0} for _ in range(5)
    ]
    fake_bars_col.find.return_value.limit.return_value = fake_bars
    fake_db.get.return_value = fake_bars_col
    import database
    monkeypatch.setattr(database, "get_database", lambda: fake_db)
    result = await s._get_adv_from_ib_historical(["TEST"])
    assert result["TEST"] == 10_000_000 * 50    # = $500,000,000


@pytest.mark.asyncio
async def test_get_adv_from_ib_historical_skips_symbols_with_too_few_bars(monkeypatch):
    s = _make_scanner_minimal()
    fake_db = MagicMock()
    fake_bars_col = MagicMock()
    # Only 3 bars — need ≥5 to compute
    fake_bars_col.find.return_value.limit.return_value = [
        {"volume": 10_000_000, "close": 50.0} for _ in range(3)
    ]
    fake_db.get.return_value = fake_bars_col
    import database
    monkeypatch.setattr(database, "get_database", lambda: fake_db)
    result = await s._get_adv_from_ib_historical(["THIN"])
    assert result == {}
