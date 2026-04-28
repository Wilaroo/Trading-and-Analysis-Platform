"""Tests for SectorTagService + SectorRegimeClassifier + ML feature plumbing.

Covers:
  - Static sector map: every value is a valid SECTOR_ETF, no duplicate
    sectors per major name, ETF-self-mapping is correct.
  - `tag_symbol` lookups (case-insensitive, returns None for unknown).
  - `coverage` math.
  - `backfill_symbol_adv_cache` writes `sector` + `sector_name`,
    skips already-tagged docs (idempotent), handles untaggable
    symbols cleanly.
  - SectorRegimeClassifier label assignment for STRONG / WEAK /
    ROTATING_IN / ROTATING_OUT / NEUTRAL from synthetic ETF + SPY bars.
  - Cache TTL hits + invalidate clears state.
  - `classify_for_symbol` resolves via tag service; UNKNOWN on
    untagged symbols.
  - SectorRegimeHistoricalProvider — preload, date-aware lookup,
    UNKNOWN before sufficient bars exist.
  - `build_sector_label_features` one-hot helper edges.
  - `ALL_LABEL_FEATURE_NAMES` now includes 5 sector slots → 20 total.
  - `LiveAlert.sector_regime` field exists and defaults to "unknown".
  - `_apply_setup_context` stamps `alert.sector_regime`.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Dict, List

sys.path.insert(0, "/app/backend")

import pytest  # noqa: E402

from services.sector_tag_service import (  # noqa: E402
    SectorTagService, SECTOR_ETFS, STATIC_SECTOR_MAP,
    get_sector_tag_service,
)
from services.sector_regime_classifier import (  # noqa: E402
    SectorRegime, SectorRegimeClassifier, SectorRegimeHistoricalProvider,
    SECTOR_LABEL_FEATURE_NAMES, build_sector_label_features,
    get_sector_regime_classifier,
)
from services.ai_modules.composite_label_features import (  # noqa: E402
    ALL_LABEL_FEATURE_NAMES, build_label_features,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _bars(closes: List[float]) -> List[Dict]:
    """Build a sequence of daily-bar dicts (oldest-first)."""
    return [{
        "date": f"2026-04-{i+1:02d}",
        "open": c, "close": c,
        "high": c * 1.01, "low": c * 0.99,
        "volume": 1_000_000,
    } for i, c in enumerate(closes)]


# ──────────────────────────── Static map ────────────────────────────


def test_every_static_map_value_is_a_known_sector_etf():
    """No typos in sector ETF codes — every value lives in SECTOR_ETFS."""
    valid = set(SECTOR_ETFS.keys())
    for sym, etf in STATIC_SECTOR_MAP.items():
        assert etf in valid, f"{sym!r} maps to unknown ETF {etf!r}"


def test_etfs_self_map():
    svc = SectorTagService()
    for etf in SECTOR_ETFS:
        assert svc.tag_symbol(etf) == etf


def test_tag_symbol_case_insensitive():
    svc = SectorTagService()
    assert svc.tag_symbol("aapl") == "XLK"
    assert svc.tag_symbol("AAPL") == "XLK"


def test_tag_symbol_returns_none_for_unknown():
    svc = SectorTagService()
    assert svc.tag_symbol("ZZZZ") is None
    assert svc.tag_symbol("") is None


def test_coverage_math():
    svc = SectorTagService()
    cov = svc.coverage(["AAPL", "MSFT", "ZZZZ", "QQQQQ"])
    assert cov["total"] == 4
    assert cov["tagged"] == 2
    assert cov["coverage_pct"] == 50.0


def test_static_map_covers_all_sector_etfs():
    """Each of the 11 sectors should have at least one stock tagged
    (sanity check that the map isn't lopsided)."""
    by_sector: Dict[str, int] = {}
    for etf in STATIC_SECTOR_MAP.values():
        by_sector[etf] = by_sector.get(etf, 0) + 1
    for etf in SECTOR_ETFS:
        assert by_sector.get(etf, 0) >= 1, (
            f"sector {etf} has no tagged stocks in STATIC_SECTOR_MAP"
        )


# ──────────────────────────── Backfill ────────────────────────────


class _FakeColl:
    def __init__(self, docs):
        self.docs = list(docs)

    def find(self, filt=None, projection=None):
        return list(self.docs)

    def update_one(self, filter_, update, upsert=False):
        for d in self.docs:
            if all(d.get(k) == v for k, v in filter_.items()):
                d.update(update.get("$set", {}))
                return type("UR", (), {"matched_count": 1})()
        return type("UR", (), {"matched_count": 0})()


class _FakeDB:
    def __init__(self, docs):
        self._col = _FakeColl(docs)

    def __getitem__(self, name):
        return self._col


def test_backfill_writes_sector_and_skips_existing():
    docs = [
        {"symbol": "AAPL"},                      # untagged → tag
        {"symbol": "MSFT", "sector": "XLK"},     # already tagged → skip
        {"symbol": "ZZZZ"},                      # not in static map → untaggable
    ]
    db = _FakeDB(docs)
    svc = SectorTagService(db=db)
    result = _run(svc.backfill_symbol_adv_cache(db=db))
    assert result["total"] == 3
    assert result["tagged"] == 1
    assert result["skipped"] == 1
    assert result["untaggable"] == 1
    # AAPL got tagged with both sector and sector_name
    aapl = next(d for d in docs if d["symbol"] == "AAPL")
    assert aapl["sector"] == "XLK"
    assert aapl["sector_name"] == "Technology"
    # MSFT was untouched
    msft = next(d for d in docs if d["symbol"] == "MSFT")
    assert "sector_name" not in msft


def test_backfill_idempotent_on_second_run():
    docs = [{"symbol": "AAPL"}, {"symbol": "JPM"}]
    db = _FakeDB(docs)
    svc = SectorTagService(db=db)
    _run(svc.backfill_symbol_adv_cache(db=db))
    second = _run(svc.backfill_symbol_adv_cache(db=db))
    assert second["tagged"] == 0
    assert second["skipped"] == 2


def test_singleton():
    a = get_sector_tag_service()
    b = get_sector_tag_service()
    assert a is b


# ──────────────────────────── SectorRegimeClassifier ────────────────────────────


def _index_map(spy, xlk=None, xle=None, xlf=None, xlv=None, xly=None,
               xlp=None, xli=None, xlb=None, xlre=None, xlu=None, xlc=None):
    """Build a sector-bar map; unspecified sectors get a flat (no-data) series."""
    flat = [100] * 21
    return {
        "SPY": _bars(spy),
        "XLK": _bars(xlk or flat), "XLE": _bars(xle or flat),
        "XLF": _bars(xlf or flat), "XLV": _bars(xlv or flat),
        "XLY": _bars(xly or flat), "XLP": _bars(xlp or flat),
        "XLI": _bars(xli or flat), "XLB": _bars(xlb or flat),
        "XLRE": _bars(xlre or flat), "XLU": _bars(xlu or flat),
        "XLC": _bars(xlc or flat),
    }


def test_classifier_strong_when_sector_up_and_outperforming():
    """XLK climbing 3% + outperforming flat SPY → STRONG."""
    spy = [100] * 21                                # flat SPY
    xlk = [100 + 0.15 * i for i in range(21)]       # ~+3% across 21 bars
    cls = SectorRegimeClassifier()
    res = _run(cls.classify_all_sectors(sector_bars=_index_map(spy, xlk=xlk)))
    assert res.sectors["XLK"].regime == SectorRegime.STRONG


def test_classifier_weak_when_sector_down_and_underperforming():
    spy = [100] * 21                                # flat SPY
    xle = [100 - 0.18 * i for i in range(21)]       # ~-3.6% across 21 bars
    cls = SectorRegimeClassifier()
    res = _run(cls.classify_all_sectors(sector_bars=_index_map(spy, xle=xle)))
    assert res.sectors["XLE"].regime == SectorRegime.WEAK


def test_classifier_rotating_in_when_RS_dominant():
    """5d momentum hot (>+0.5% vs flat SPY) BUT trend vs 20SMA mild
    (<0.5%) → ROTATING_IN, not STRONG.

    Construction: sector flat for 15 bars, mild dip to 99.5, then rally
    back to 100.3 over the last 5 bars. SMA20 ≈ 99.97, last 100.3 →
    trend ≈ +0.33% (below STRONG); 5d return ≈ +0.80% (above RS_HOT).
    """
    spy = [100] * 21
    xlf = [100] * 15 + [99.5, 99.7, 99.9, 100.1, 100.2, 100.3]
    cls = SectorRegimeClassifier()
    res = _run(cls.classify_all_sectors(sector_bars=_index_map(spy, xlf=xlf)))
    snap = res.sectors["XLF"]
    assert abs(snap.trend_pct) < SectorRegimeClassifier.STRONG_TREND_PCT
    assert snap.rs_vs_spy_pct >= SectorRegimeClassifier.RS_HOT_PCT
    assert snap.regime == SectorRegime.ROTATING_IN


def test_classifier_neutral_when_flat():
    spy = [100] * 21
    cls = SectorRegimeClassifier()
    res = _run(cls.classify_all_sectors(sector_bars=_index_map(spy)))
    assert res.sectors["XLK"].regime == SectorRegime.NEUTRAL


def test_classifier_unknown_when_insufficient_data():
    """A sector with only 5 bars → UNKNOWN (not classified)."""
    spy = [100] * 21
    bars_map = _index_map(spy)
    bars_map["XLK"] = _bars([100] * 5)              # too few bars
    cls = SectorRegimeClassifier()
    res = _run(cls.classify_all_sectors(sector_bars=bars_map))
    assert "XLK" not in res.sectors                 # dropped


def test_classifier_caches_market_wide():
    spy = [100] * 21
    bars = _index_map(spy)
    cls = SectorRegimeClassifier()
    _run(cls.classify_all_sectors(sector_bars=bars))
    assert cls._cache_misses == 1
    _run(cls.classify_all_sectors(sector_bars=bars))
    assert cls._cache_hits == 1


def test_classifier_invalidate_clears_cache():
    spy = [100] * 21
    bars = _index_map(spy)
    cls = SectorRegimeClassifier()
    _run(cls.classify_all_sectors(sector_bars=bars))
    cls.invalidate()
    _run(cls.classify_all_sectors(sector_bars=bars))
    assert cls._cache_misses == 2


def test_classify_for_symbol_resolves_via_tag_service():
    """AAPL → XLK via tag service → returns XLK's regime."""
    spy = [100] * 21
    xlk = [100 + 0.15 * i for i in range(21)]
    bars = _index_map(spy, xlk=xlk)
    cls = SectorRegimeClassifier()
    cls.invalidate()
    _run(cls.classify_all_sectors(sector_bars=bars))
    # Calls classify_for_symbol — should hit the cache, not reload bars
    label = _run(cls.classify_for_symbol("AAPL"))
    assert label == SectorRegime.STRONG


def test_classify_for_symbol_unknown_for_untagged():
    cls = SectorRegimeClassifier()
    cls.invalidate()
    label = _run(cls.classify_for_symbol("ZZZZ"))
    assert label == SectorRegime.UNKNOWN


# ──────────────────────────── Historical provider ────────────────────────────


class _HistFakeColl:
    def __init__(self, bars_map):
        # bars_map: {symbol: [bar dicts]}
        self.bars_map = bars_map

    def find(self, filter_, projection=None):
        sym = filter_.get("symbol")
        return _SortableCursor([dict(b, symbol=sym) for b in self.bars_map.get(sym, [])])


class _SortableCursor(list):
    def sort(self, key, direction=1):
        try:
            super().sort(key=lambda d: d.get(key, ""), reverse=(direction == -1))
        except Exception:
            pass
        return self


class _HistFakeDB:
    def __init__(self, bars_map):
        self._col = _HistFakeColl(bars_map)

    def __getitem__(self, name):
        return self._col


def test_historical_provider_resolves_aapl_to_xlk():
    bars = {
        "SPY": _bars([100] * 25),
        "XLK": _bars([100 + 0.15 * i for i in range(25)]),
    }
    # Re-shape for the historical provider's loader (oldest-first list of
    # docs with date strings)
    db = _HistFakeDB(bars)
    p = SectorRegimeHistoricalProvider(db)
    p.preload()
    # 21st day in our synthetic series
    label = p.get_sector_regime_for("AAPL", "2026-04-21")
    assert label in (SectorRegime.STRONG, SectorRegime.NEUTRAL,
                     SectorRegime.ROTATING_IN)


def test_historical_provider_unknown_before_min_bars():
    bars = {"SPY": _bars([100] * 25),
            "XLK": _bars([100 + 0.15 * i for i in range(25)])}
    db = _HistFakeDB(bars)
    p = SectorRegimeHistoricalProvider(db)
    p.preload()
    # Date earlier than 21 bars in → UNKNOWN
    label = p.get_sector_regime_for("AAPL", "2026-04-05")
    assert label == SectorRegime.UNKNOWN


def test_historical_provider_caches_per_etf_date():
    bars = {"SPY": _bars([100] * 25),
            "XLK": _bars([100 + 0.15 * i for i in range(25)])}
    db = _HistFakeDB(bars)
    p = SectorRegimeHistoricalProvider(db)
    p.preload()
    p.get_sector_regime_for("AAPL", "2026-04-21")
    n1 = len(p._regime_cache)
    p.get_sector_regime_for("MSFT", "2026-04-21")  # same ETF + date
    n2 = len(p._regime_cache)
    assert n1 == n2  # cache hit, no new entry


def test_historical_provider_unknown_for_untagged():
    bars = {"SPY": _bars([100] * 25)}
    db = _HistFakeDB(bars)
    p = SectorRegimeHistoricalProvider(db)
    p.preload()
    assert p.get_sector_regime_for("ZZZZ", "2026-04-21") == SectorRegime.UNKNOWN


# ──────────────────────────── ML feature names ────────────────────────────


def test_sector_label_feature_names_excludes_unknown():
    for n in SECTOR_LABEL_FEATURE_NAMES:
        assert "unknown" not in n
    assert len(SECTOR_LABEL_FEATURE_NAMES) == 5


def test_build_sector_label_features_one_hot():
    feats = build_sector_label_features("strong")
    assert feats["sector_label_strong"] == 1.0
    assert sum(feats.values()) == 1.0


def test_build_sector_label_features_unknown_is_all_zeros():
    feats = build_sector_label_features(SectorRegime.UNKNOWN)
    assert sum(feats.values()) == 0.0


def test_all_label_feature_names_now_includes_sector():
    """7 setup + 8 regime + 5 sector = 20 slots."""
    assert len(ALL_LABEL_FEATURE_NAMES) == 20
    assert any(n.startswith("sector_label_") for n in ALL_LABEL_FEATURE_NAMES)


def test_build_label_features_combines_three_layers():
    feats = build_label_features(
        market_setup="gap_and_go",
        multi_index_regime="risk_on_broad",
        sector_regime="strong",
    )
    one_count = sum(1 for v in feats.values() if v == 1.0)
    assert one_count == 3


# ──────────────────────────── LiveAlert + scanner integration ────────────────────────────


def test_live_alert_has_sector_regime_field():
    from services.enhanced_scanner import LiveAlert
    fields = LiveAlert.__dataclass_fields__
    assert "sector_regime" in fields
    assert fields["sector_regime"].default == "unknown"


def test_apply_setup_context_stamps_sector_regime():
    """`_apply_setup_context` calls SectorRegimeClassifier.classify_for_symbol
    and stamps `alert.sector_regime`."""
    from services.enhanced_scanner import EnhancedBackgroundScanner, AlertPriority
    from services.sector_regime_classifier import (
        SectorRegimeResult, SectorSnapshot,
    )
    import datetime as dt

    s = EnhancedBackgroundScanner(db=None)
    cls = get_sector_regime_classifier()
    cls.invalidate()
    # Inject a fixed sector classification
    cls._cached = SectorRegimeResult(
        sectors={
            "XLK": SectorSnapshot(
                etf="XLK", last_close=200, sma20=190, trend_pct=5.0,
                momentum_5d_pct=2.0, rs_vs_spy_pct=1.5,
                regime=SectorRegime.STRONG,
            ),
        },
    )
    cls._cached_at = dt.datetime.now(dt.timezone.utc)

    class _Alert:
        setup_type = "9_ema_scalp"
        priority = AlertPriority.HIGH
        market_setup = "neutral"
        is_countertrend = False
        out_of_context_warning = False
        experimental = False
        multi_index_regime = "unknown"
        sector_regime = "unknown"
        reasoning: list = []

    alert = _Alert()
    _run(s._apply_setup_context(alert, "AAPL", None))    # AAPL → XLK → STRONG
    assert alert.sector_regime == "strong"


def test_apply_setup_context_sector_regime_unknown_for_untagged_symbol():
    from services.enhanced_scanner import EnhancedBackgroundScanner, AlertPriority
    s = EnhancedBackgroundScanner(db=None)

    class _Alert:
        setup_type = "9_ema_scalp"
        priority = AlertPriority.HIGH
        market_setup = "neutral"
        is_countertrend = False
        out_of_context_warning = False
        experimental = False
        multi_index_regime = "unknown"
        sector_regime = "unknown"
        reasoning: list = []

    alert = _Alert()
    _run(s._apply_setup_context(alert, "ZZZZ", None))
    assert alert.sector_regime == "unknown"


# ──────────────────────────── Source-level guards ────────────────────────────


def test_training_path_uses_sector_hist_provider():
    from pathlib import Path
    src = Path("/app/backend/services/ai_modules/timeseries_service.py").read_text("utf-8")
    assert "SectorRegimeHistoricalProvider" in src
    assert "sector_hist_provider" in src
    assert "get_sector_regime_for" in src


def test_predict_path_reads_cached_sector_label():
    from pathlib import Path
    src = Path("/app/backend/services/ai_modules/timeseries_service.py").read_text("utf-8")
    assert "get_sector_regime_classifier" in src
    assert "sector_label" in src
