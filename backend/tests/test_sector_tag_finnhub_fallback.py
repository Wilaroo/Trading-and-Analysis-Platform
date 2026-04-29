"""Tests for the IB / Finnhub sector-tag fallback (2026-04-30, operator P2).

Pre-fix:
  - `SectorTagService.tag_symbol` only consulted `STATIC_SECTOR_MAP`.
  - Newly-listed names (or anything outside the curated ~340 large-caps)
    returned None → SectorRegimeClassifier reported UNKNOWN forever.

Post-fix:
  - New `tag_symbol_async` runs the full chain:
      static-map → symbol_adv_cache.sector → Finnhub industry → persist.
  - `_industry_to_etf` maps free-form Finnhub industry strings to
    SPDR ETF codes via case-insensitive longest-substring match.
  - SectorRegimeClassifier.classify_for_symbol falls through to
    tag_symbol_async on a static miss.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

sys.path.insert(0, "/app/backend")

import pytest  # noqa: E402

SECTOR_TAG_SRC = Path(
    "/app/backend/services/sector_tag_service.py"
).read_text("utf-8")

SECTOR_REGIME_SRC = Path(
    "/app/backend/services/sector_regime_classifier.py"
).read_text("utf-8")


# ───────── Source-level guards ─────────


def test_industry_to_etf_table_present():
    assert "_INDUSTRY_TO_ETF" in SECTOR_TAG_SRC
    assert "def _industry_to_etf(industry:" in SECTOR_TAG_SRC


def test_async_tag_method_present():
    assert "async def tag_symbol_async(self, symbol:" in SECTOR_TAG_SRC


def test_classify_for_symbol_uses_async_fallback():
    """Source-level guard: classify_for_symbol must call
    tag_symbol_async when the static map misses."""
    block = SECTOR_REGIME_SRC[
        SECTOR_REGIME_SRC.find("async def classify_for_symbol"):
    ]
    assert "svc.tag_symbol_async(symbol)" in block


def test_persist_after_finnhub_hit():
    """After Finnhub success the result MUST be written to
    `symbol_adv_cache.sector` so the next call hits the Mongo cache."""
    block = SECTOR_TAG_SRC[
        SECTOR_TAG_SRC.find("async def tag_symbol_async"):
    ]
    assert 'self.db["symbol_adv_cache"].update_one' in block
    assert '"sector": etf' in block
    assert '"sector_source": "finnhub_industry"' in block


# ───────── Industry → ETF mapping ─────────


def test_industry_to_etf_technology():
    from services.sector_tag_service import _industry_to_etf
    assert _industry_to_etf("Technology") == "XLK"
    assert _industry_to_etf("Semiconductor Manufacturing") == "XLK"
    assert _industry_to_etf("Software – Application") == "XLK"


def test_industry_to_etf_communication():
    from services.sector_tag_service import _industry_to_etf
    assert _industry_to_etf("Internet Content & Information") == "XLC"
    assert _industry_to_etf("Telecommunication services") == "XLC"
    assert _industry_to_etf("Entertainment") == "XLC"


def test_industry_to_etf_consumer_disambiguation():
    """`Consumer Cyclical` → XLY, `Consumer Defensive` → XLP, sorted by
    key length so the longer key wins. Important: `Cyclical` alone
    doesn't appear in the map but `Consumer Cyclical` does."""
    from services.sector_tag_service import _industry_to_etf
    assert _industry_to_etf("Consumer Cyclical") == "XLY"
    assert _industry_to_etf("Consumer Defensive") == "XLP"
    assert _industry_to_etf("Consumer Discretionary") == "XLY"


def test_industry_to_etf_healthcare():
    from services.sector_tag_service import _industry_to_etf
    assert _industry_to_etf("Healthcare") == "XLV"
    assert _industry_to_etf("Biotechnology") == "XLV"
    assert _industry_to_etf("Drug Manufacturers - General") == "XLV"


def test_industry_to_etf_financials():
    from services.sector_tag_service import _industry_to_etf
    assert _industry_to_etf("Banks - Diversified") == "XLF"
    assert _industry_to_etf("Insurance - Property & Casualty") == "XLF"


def test_industry_to_etf_energy():
    from services.sector_tag_service import _industry_to_etf
    assert _industry_to_etf("Oil & Gas E&P") == "XLE"
    assert _industry_to_etf("Energy") == "XLE"


def test_industry_to_etf_real_estate():
    from services.sector_tag_service import _industry_to_etf
    assert _industry_to_etf("REIT - Industrial") == "XLRE"
    assert _industry_to_etf("Real Estate Services") == "XLRE"


def test_industry_to_etf_utilities():
    from services.sector_tag_service import _industry_to_etf
    assert _industry_to_etf("Utilities - Renewable") == "XLU"
    assert _industry_to_etf("Utility - Regulated Electric") == "XLU"
    # Ensure "renewable" alone also maps because it's an explicit key
    assert _industry_to_etf("Renewable Energy") == "XLU"


def test_industry_to_etf_unknown():
    from services.sector_tag_service import _industry_to_etf
    assert _industry_to_etf("Cryptocurrency Mining Pool") is None
    assert _industry_to_etf("") is None
    assert _industry_to_etf(None) is None


# ───────── Async fallback chain (with mocked DB + Finnhub) ─────────


class _FakeMongoCollection:
    def __init__(self, docs=None):
        self._docs = docs or {}
        self.updates = []

    def find_one(self, query, _projection=None):
        sym = query.get("symbol")
        return self._docs.get(sym)

    def update_one(self, filter_q, update, upsert=False):
        sym = filter_q.get("symbol")
        new_fields = update.get("$set", {})
        self.updates.append((sym, new_fields))
        existing = self._docs.get(sym, {"symbol": sym})
        existing.update(new_fields)
        self._docs[sym] = existing


class _FakeDb:
    def __init__(self, docs=None):
        self._cache_col = _FakeMongoCollection(docs)

    def __getitem__(self, name):
        if name == "symbol_adv_cache":
            return self._cache_col
        raise KeyError(name)


@pytest.mark.asyncio
async def test_async_static_map_hit_returns_immediately():
    """Static map hit short-circuits — no Mongo / Finnhub calls."""
    from services.sector_tag_service import SectorTagService
    svc = SectorTagService(db=None)
    result = await svc.tag_symbol_async("AAPL")
    assert result == "XLK"


@pytest.mark.asyncio
async def test_async_mongo_cache_hit():
    """Symbol not in static map but in `symbol_adv_cache.sector`
    → returns cached ETF, promotes to in-memory map for next sync call."""
    from services.sector_tag_service import SectorTagService
    db = _FakeDb({"NEWCO": {"symbol": "NEWCO", "sector": "XLK"}})
    svc = SectorTagService(db=db)
    # NEWCO is not in static map — sanity check
    assert svc.tag_symbol("NEWCO") is None
    result = await svc.tag_symbol_async("NEWCO")
    assert result == "XLK"
    # Promoted to in-memory map
    assert svc.tag_symbol("NEWCO") == "XLK"


@pytest.mark.asyncio
async def test_async_mongo_cache_invalid_etf_ignored():
    """If `symbol_adv_cache.sector` contains a junk value (not a real
    SPDR ETF), the lookup must NOT promote it — falls through to Finnhub."""
    from services.sector_tag_service import SectorTagService
    db = _FakeDb({"WEIRDCO": {"symbol": "WEIRDCO", "sector": "ZZZ"}})
    svc = SectorTagService(db=db)
    # Patch fundamental_data_service so this doesn't hit the network
    with patch("services.fundamental_data_service.get_fundamental_data_service") as get_svc:
        fake_fund = AsyncMock()
        fake_fund.get_company_profile = AsyncMock(return_value=None)
        get_svc.return_value = fake_fund
        result = await svc.tag_symbol_async("WEIRDCO")
    # Finnhub returned nothing → final answer None (junk cache value
    # didn't fool us into accepting "ZZZ").
    assert result is None


@pytest.mark.asyncio
async def test_async_finnhub_fallback_persists():
    """Static + Mongo miss → Finnhub returns industry → mapped to ETF
    → persisted to symbol_adv_cache.sector for next call."""
    from services.sector_tag_service import SectorTagService

    db = _FakeDb()
    svc = SectorTagService(db=db)

    fake_fund = AsyncMock()
    fake_fund.get_company_profile = AsyncMock(
        return_value={"industry": "Software - Infrastructure"}
    )
    with patch(
        "services.fundamental_data_service.get_fundamental_data_service",
        return_value=fake_fund,
    ):
        result = await svc.tag_symbol_async("FAKETECHCO")

    assert result == "XLK"
    # Persisted to Mongo
    assert len(db._cache_col.updates) == 1
    sym, fields = db._cache_col.updates[0]
    assert sym == "FAKETECHCO"
    assert fields["sector"] == "XLK"
    assert fields["sector_source"] == "finnhub_industry"
    assert fields["sector_source_industry"] == "Software - Infrastructure"


@pytest.mark.asyncio
async def test_async_finnhub_unmappable_industry_returns_none():
    """If Finnhub returns an industry that doesn't map, we don't
    persist garbage — caller treats as UNKNOWN sector."""
    from services.sector_tag_service import SectorTagService

    db = _FakeDb()
    svc = SectorTagService(db=db)
    fake_fund = AsyncMock()
    fake_fund.get_company_profile = AsyncMock(
        return_value={"industry": "Cryptocurrency Mining"}
    )
    with patch(
        "services.fundamental_data_service.get_fundamental_data_service",
        return_value=fake_fund,
    ):
        result = await svc.tag_symbol_async("CRYPTOCO")

    assert result is None
    assert len(db._cache_col.updates) == 0


@pytest.mark.asyncio
async def test_async_no_db_no_persist():
    """Without DB, Finnhub fallback still works but doesn't try to persist."""
    from services.sector_tag_service import SectorTagService
    svc = SectorTagService(db=None)
    fake_fund = AsyncMock()
    fake_fund.get_company_profile = AsyncMock(
        return_value={"industry": "Banking"}
    )
    with patch(
        "services.fundamental_data_service.get_fundamental_data_service",
        return_value=fake_fund,
    ):
        result = await svc.tag_symbol_async("PRIVATECO")
    assert result == "XLF"
    # In-memory cache still updated
    assert svc.tag_symbol("PRIVATECO") == "XLF"


@pytest.mark.asyncio
async def test_async_empty_symbol_returns_none():
    from services.sector_tag_service import SectorTagService
    svc = SectorTagService(db=None)
    assert (await svc.tag_symbol_async("")) is None
    assert (await svc.tag_symbol_async(None)) is None
