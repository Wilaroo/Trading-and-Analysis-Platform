"""v19.34.211 — Dynamic Universe Builder.

Validates composition logic with every external source mocked:
  * qualification gate (movers/catalysts must be in qualified universe;
    held/watchlist exempt)
  * regime tilt (aligned mover lists outscore counter-regime lists)
  * priority selection (pure-core names excluded; held ranks top)
  * graceful degradation (empty movers → degraded flag, non-empty universe)
  * persistence shape + freshness logic
"""
from datetime import datetime, timedelta, timezone

import pytest

import services.dynamic_universe_builder as dub
from services.dynamic_universe_builder import DynamicUniverseBuilder


# ── fake Mongo ────────────────────────────────────────────────────────────
class _FakeColl:
    def __init__(self):
        self.docs = {}

    def update_one(self, flt, update, upsert=False):
        _id = flt["_id"]
        self.docs[_id] = dict(update["$set"])

    def find_one(self, flt):
        return self.docs.get(flt["_id"])


class _FakeDB:
    def __init__(self):
        self._colls = {}

    def __getitem__(self, name):
        return self._colls.setdefault(name, _FakeColl())


def _async(value):
    async def _f(*a, **k):
        return value
    return _f


def _patch_sources(monkeypatch, *, regime="CONFIRMED_UP", movers=None, degraded=False,
                   core=None, qualified=None, earnings=None, news=None,
                   held=None, watchlist=None):
    monkeypatch.setattr(DynamicUniverseBuilder, "_regime", _async((regime, 70.0)))
    monkeypatch.setattr(DynamicUniverseBuilder, "_ib_movers",
                        _async((movers or {}, degraded)))
    monkeypatch.setattr(DynamicUniverseBuilder, "_catalysts",
                        _async((earnings or [], news or [])))
    monkeypatch.setattr(DynamicUniverseBuilder, "_push_to_gameplan", _async(None))
    monkeypatch.setattr(DynamicUniverseBuilder, "_liquid_core",
                        lambda self, limit: list(core or []))
    monkeypatch.setattr(DynamicUniverseBuilder, "_qualified_set",
                        lambda self: set(qualified or []))
    monkeypatch.setattr(DynamicUniverseBuilder, "_held_symbols",
                        lambda self: list(held or []))
    monkeypatch.setattr(DynamicUniverseBuilder, "_watchlist_symbols",
                        lambda self: list(watchlist or []))


@pytest.mark.asyncio
async def test_full_build_scoring_gate_and_priority(monkeypatch):
    _patch_sources(
        monkeypatch,
        regime="CONFIRMED_UP",
        core=["CORE1", "CORE2"],
        qualified={"NVDA", "TSLA", "PLTR", "CORE1", "CORE2"},
        movers={
            "NVDA": ["TOP_PERC_GAIN"],   # aligned (uptrend) → 40
            "TSLA": ["TOP_PERC_LOSE"],   # counter → 12
            "JUNK": ["TOP_PERC_GAIN"],   # NOT qualified → gated out
        },
        earnings=["PLTR"],               # +30
        held=["AMD"],                    # +100, exempt from gate
        watchlist=["SOFI"],              # +60, exempt
    )
    b = DynamicUniverseBuilder(db=_FakeDB())
    doc = await b.build()

    smap = {d["symbol"]: d for d in doc["symbols"]}
    # gate: unqualified mover dropped
    assert "JUNK" not in smap
    # held exempt + top score
    assert smap["AMD"]["score"] == dub.W_HELD
    assert doc["priority_symbols"][0] == "AMD"
    # regime tilt: aligned gainer outscores counter-regime loser
    assert smap["NVDA"]["score"] == dub.W_MOVER_ALIGNED
    assert smap["TSLA"]["score"] == dub.W_MOVER_COUNTER
    assert smap["NVDA"]["score"] > smap["TSLA"]["score"]
    # catalyst + exempt watchlist present
    assert "catalyst:earnings" in smap["PLTR"]["sources"]
    assert smap["SOFI"]["score"] == dub.W_WATCHLIST
    # pure-core names excluded from priority
    assert "CORE1" not in doc["priority_symbols"]
    assert "CORE2" not in doc["priority_symbols"]
    # held/watchlist/catalyst/movers all in priority
    for s in ("AMD", "SOFI", "PLTR", "NVDA", "TSLA"):
        assert s in doc["priority_symbols"]
    assert doc["degraded"] is False
    assert doc["counts"]["held"] == 1 and doc["counts"]["catalysts"] == 1


@pytest.mark.asyncio
async def test_regime_down_tilts_to_losers(monkeypatch):
    _patch_sources(
        monkeypatch,
        regime="CONFIRMED_DOWN",
        core=[],
        qualified={"AAA", "BBB"},
        movers={"AAA": ["TOP_PERC_LOSE"], "BBB": ["TOP_PERC_GAIN"]},
    )
    b = DynamicUniverseBuilder(db=_FakeDB())
    doc = await b.build()
    smap = {d["symbol"]: d["score"] for d in doc["symbols"]}
    assert smap["AAA"] == dub.W_MOVER_ALIGNED   # loser aligned in downtrend
    assert smap["BBB"] == dub.W_MOVER_COUNTER


@pytest.mark.asyncio
async def test_graceful_degradation_empty_movers(monkeypatch):
    _patch_sources(
        monkeypatch,
        movers={}, degraded=True,
        core=["CORE1"], qualified={"CORE1", "ZZ"},
        earnings=["ZZ"], held=["HELD1"],
    )
    b = DynamicUniverseBuilder(db=_FakeDB())
    doc = await b.build()
    assert doc["degraded"] is True
    # still produced a non-empty universe from core + catalyst + held
    syms = {d["symbol"] for d in doc["symbols"]}
    assert {"CORE1", "ZZ", "HELD1"} <= syms
    assert "HELD1" in doc["priority_symbols"]


def test_mover_points_mapping():
    f = DynamicUniverseBuilder._mover_points
    assert f("MOST_ACTIVE", "CONFIRMED_UP") == dub.W_MOVER_NEUTRAL
    assert f("HOT_BY_VOLUME", "CONFIRMED_DOWN") == dub.W_MOVER_NEUTRAL
    assert f("TOP_PERC_GAIN", "CONFIRMED_UP") == dub.W_MOVER_ALIGNED
    assert f("TOP_PERC_GAIN", "CONFIRMED_DOWN") == dub.W_MOVER_COUNTER
    assert f("GAP_DOWN", "CONFIRMED_DOWN") == dub.W_MOVER_ALIGNED
    assert f("TOP_PERC_LOSE", "HOLD") == dub.W_MOVER_NEUTRAL


@pytest.mark.asyncio
async def test_freshness_and_reads(monkeypatch):
    _patch_sources(monkeypatch, core=["C1"], qualified={"C1"})
    b = DynamicUniverseBuilder(db=_FakeDB())
    assert b.is_fresh() is False           # nothing built yet
    await b.build()
    assert b.is_fresh() is True            # just built
    assert b.get_universe_symbols() == ["C1"]
    # stale doc → not fresh
    doc = b.get_doc()
    doc["built_at"] = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    assert b.is_fresh(ttl_min=45) is False


@pytest.mark.asyncio
async def test_maybe_rebuild_skips_when_fresh(monkeypatch):
    _patch_sources(monkeypatch, core=["C1"], qualified={"C1"})
    b = DynamicUniverseBuilder(db=_FakeDB())
    first = await b.maybe_rebuild()
    assert first is not None
    second = await b.maybe_rebuild()       # fresh → no-op
    assert second is None


@pytest.mark.asyncio
async def test_duplicate_catalyst_counts_once(monkeypatch):
    # v19.34.211b — earnings feed lists VSCO 3x; must score 30 once, not 90.
    _patch_sources(
        monkeypatch,
        regime="HOLD",
        core=[],
        qualified={"VSCO"},
        earnings=["VSCO", "VSCO", "VSCO"],
    )
    b = DynamicUniverseBuilder(db=_FakeDB())
    doc = await b.build()
    smap = {d["symbol"]: d for d in doc["symbols"]}
    assert smap["VSCO"]["score"] == dub.W_CATALYST_EARNINGS  # 30, not 90
    assert smap["VSCO"]["sources"] == ["catalyst:earnings"]


@pytest.mark.asyncio
async def test_earnings_plus_news_each_count_once(monkeypatch):
    _patch_sources(
        monkeypatch,
        regime="HOLD", core=[], qualified={"ABC"},
        earnings=["ABC", "ABC"], news=["ABC", "ABC", "ABC"],
    )
    b = DynamicUniverseBuilder(db=_FakeDB())
    doc = await b.build()
    smap = {d["symbol"]: d for d in doc["symbols"]}
    # earnings(30) once + news(18) once = 48
    assert smap["ABC"]["score"] == dub.W_CATALYST_EARNINGS + dub.W_CATALYST_NEWS
    assert set(smap["ABC"]["sources"]) == {"catalyst:earnings", "catalyst:news"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
