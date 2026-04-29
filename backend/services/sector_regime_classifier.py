"""
SectorRegimeClassifier — per-sector regime from 11 SPDR sector ETFs.
=====================================================================

Sits one level below `MultiIndexRegimeClassifier` in the operator
mental model:

    Multi-index regime  → Sector regime  → Daily Setup  → Time/Inplay  → Trade

…but is a SOFT gate (feature only, not a hard reject) to preserve the
ML training data flow per the 2026-04-29 architecture decision.

Reads daily bars for **XLK / XLE / XLF / XLV / XLY / XLP / XLI / XLB /
XLRE / XLU / XLC** plus SPY (the relative-strength benchmark) and
classifies each sector into one of 6 buckets:

  - **STRONG**         — sector >0.5% above 20SMA AND > +0.3% relative to SPY
  - **ROTATING_IN**    — sector positive AND outperforming SPY by ≥0.5% over 5d
  - **NEUTRAL**        — sector flat (between -0.5% and +0.5% of 20SMA)
  - **ROTATING_OUT**   — sector negative AND underperforming SPY by ≥0.5% over 5d
  - **WEAK**           — sector <-0.5% below 20SMA AND < -0.3% relative to SPY
  - **UNKNOWN**        — insufficient bars (<21)

`classify_for_symbol(symbol)` resolves the symbol's home sector via
`SectorTagService` then returns that sector's `SectorRegime`. Untagged
symbols return UNKNOWN (alerts still fire — soft gate).

5-min market-wide cache: the regime is daily-bar-derived, one
classification per scan cycle is plenty.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ──────────────────────────── Enum + dataclass ────────────────────────────


class SectorRegime(str, Enum):
    STRONG        = "strong"
    ROTATING_IN   = "rotating_in"
    NEUTRAL       = "neutral"
    ROTATING_OUT  = "rotating_out"
    WEAK          = "weak"
    UNKNOWN       = "unknown"

    @classmethod
    def all_active(cls) -> List["SectorRegime"]:
        return [r for r in cls if r != cls.UNKNOWN]


@dataclass
class SectorSnapshot:
    """Per-sector summary numbers used by the classifier."""
    etf: str
    last_close: float
    sma20: float
    trend_pct: float                # (last - sma20) / sma20  * 100
    momentum_5d_pct: float          # (last - 5d ago) / 5d ago * 100
    rs_vs_spy_pct: float = 0.0      # 5d sector minus 5d SPY % return
    regime: SectorRegime = SectorRegime.NEUTRAL


@dataclass
class SectorRegimeResult:
    """Result of one full sector-regime classification cycle."""
    classified_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    sectors: Dict[str, SectorSnapshot] = field(default_factory=dict)
    spy_5d_return_pct: float = 0.0
    confidence: float = 0.0


# ──────────────────────────── Classifier ────────────────────────────


class SectorRegimeClassifier:
    """Classifies all 11 SPDR sector ETFs in a single pass."""

    SECTOR_ETF_LIST = ("XLK", "XLE", "XLF", "XLV", "XLY", "XLP",
                       "XLI", "XLB", "XLRE", "XLU", "XLC")
    BENCHMARK_SYMBOL = "SPY"
    DAILY_HISTORY_DAYS = 25
    MIN_BARS = 21
    CACHE_TTL_SECONDS = 300

    # Thresholds
    STRONG_TREND_PCT       = 0.5     # sector trend vs 20SMA above this = clearly bid
    WEAK_TREND_PCT         = -0.5
    NEUTRAL_BAND_PCT       = 0.5     # |trend| ≤ 0.5% = neutral
    RS_HOT_PCT             = 0.5     # 5d sector return − 5d SPY return ≥ this = rotating in
    RS_COLD_PCT            = -0.5

    def __init__(self, db=None):
        self.db = db
        self._cached: Optional[SectorRegimeResult] = None
        self._cached_at: Optional[datetime] = None
        self._cache_hits = 0
        self._cache_misses = 0
        self._daily_count: Dict[SectorRegime, int] = {}

    # ───────── Public API ─────────

    async def classify_all_sectors(
        self, sector_bars: Optional[Dict[str, List[Dict]]] = None,
    ) -> SectorRegimeResult:
        """Classify every sector ETF + SPY benchmark once per cache window.

        ``sector_bars`` is an optional pre-loaded mapping
        ``{etf_or_spy: [oldest..newest daily bars]}``; loaded from
        Mongo when not provided.
        """
        now = datetime.now(timezone.utc)
        if (self._cached is not None and self._cached_at is not None and
                (now - self._cached_at).total_seconds() < self.CACHE_TTL_SECONDS):
            self._cache_hits += 1
            return self._cached
        self._cache_misses += 1

        bar_map: Dict[str, List[Dict]] = sector_bars or {}
        symbols_needed = list(self.SECTOR_ETF_LIST) + [self.BENCHMARK_SYMBOL]
        for sym in symbols_needed:
            if sym not in bar_map:
                bar_map[sym] = await self._load_daily_bars(sym)

        # SPY benchmark — derive 5d return for relative-strength scoring
        spy_5d = self._5d_return_pct(bar_map.get(self.BENCHMARK_SYMBOL, []))

        sectors: Dict[str, SectorSnapshot] = {}
        for etf in self.SECTOR_ETF_LIST:
            snap = self._build_sector_snapshot(etf, bar_map.get(etf, []), spy_5d)
            if snap is not None:
                sectors[etf] = snap

        confidence = (len(sectors) / len(self.SECTOR_ETF_LIST)) if self.SECTOR_ETF_LIST else 0.0
        result = SectorRegimeResult(
            classified_at=now.isoformat(),
            sectors=sectors,
            spy_5d_return_pct=spy_5d,
            confidence=confidence,
        )
        # Tally for stats endpoint
        for snap in sectors.values():
            self._daily_count[snap.regime] = self._daily_count.get(snap.regime, 0) + 1
        self._cached = result
        self._cached_at = now
        return result

    async def classify_for_symbol(self, symbol: str) -> SectorRegime:
        """Return the regime of the symbol's home sector. UNKNOWN when
        the symbol can't be resolved through the static map, the Mongo
        cache, OR the Finnhub fallback (the last is gated by API key
        availability — see ``SectorTagService.tag_symbol_async``).
        """
        try:
            from services.sector_tag_service import get_sector_tag_service
            svc = get_sector_tag_service(db=self.db)
            # Fast path: synchronous static-map hit.
            etf = svc.tag_symbol(symbol)
            # Fallback chain (Mongo cache → Finnhub → persist).
            if etf is None:
                etf = await svc.tag_symbol_async(symbol)
        except Exception:
            etf = None
        if etf is None:
            return SectorRegime.UNKNOWN
        result = await self.classify_all_sectors()
        snap = result.sectors.get(etf)
        return snap.regime if snap else SectorRegime.UNKNOWN

    def stats(self) -> Dict:
        total = self._cache_hits + self._cache_misses
        return {
            "classified_today": {r.value: n for r, n in self._daily_count.items()},
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "cache_hit_rate": (self._cache_hits / total) if total else 0.0,
        }

    def invalidate(self) -> None:
        self._cached = None
        self._cached_at = None

    # ───────── Helpers ─────────

    def _build_sector_snapshot(self, etf: str, bars: List[Dict],
                               spy_5d: float) -> Optional[SectorSnapshot]:
        if not bars or len(bars) < self.MIN_BARS:
            return None
        closes = [b.get("close", 0.0) for b in bars[-21:]]
        if any(c <= 0 for c in closes):
            return None
        last = closes[-1]
        sma20 = sum(closes[-21:-1]) / 20
        if sma20 <= 0:
            return None
        trend_pct = ((last - sma20) / sma20) * 100
        sector_5d = self._5d_return_pct(bars)
        rs = sector_5d - spy_5d
        snap = SectorSnapshot(
            etf=etf,
            last_close=last,
            sma20=sma20,
            trend_pct=trend_pct,
            momentum_5d_pct=sector_5d,
            rs_vs_spy_pct=rs,
        )
        snap.regime = self._regime_for(snap)
        return snap

    def _regime_for(self, s: SectorSnapshot) -> SectorRegime:
        # Strong / weak: trend AND relative-strength agree
        if s.trend_pct >= self.STRONG_TREND_PCT and s.rs_vs_spy_pct >= 0.3:
            return SectorRegime.STRONG
        if s.trend_pct <= self.WEAK_TREND_PCT and s.rs_vs_spy_pct <= -0.3:
            return SectorRegime.WEAK
        # Rotating: 5d RS dominant
        if s.rs_vs_spy_pct >= self.RS_HOT_PCT and s.trend_pct >= 0:
            return SectorRegime.ROTATING_IN
        if s.rs_vs_spy_pct <= self.RS_COLD_PCT and s.trend_pct <= 0:
            return SectorRegime.ROTATING_OUT
        # Mild trend (within neutral band) → NEUTRAL
        if abs(s.trend_pct) <= self.NEUTRAL_BAND_PCT:
            return SectorRegime.NEUTRAL
        # Trend present but RS doesn't agree — still tag by trend direction
        return (SectorRegime.STRONG if s.trend_pct > 0 else SectorRegime.WEAK)

    @staticmethod
    def _5d_return_pct(bars: List[Dict]) -> float:
        if not bars or len(bars) < 6:
            return 0.0
        recent = bars[-1].get("close", 0.0)
        five_back = bars[-6].get("close", 0.0)
        if five_back <= 0 or recent <= 0:
            return 0.0
        return ((recent - five_back) / five_back) * 100

    async def _load_daily_bars(self, symbol: str) -> List[Dict]:
        if self.db is None:
            return []
        try:
            cursor = self.db["ib_historical_data"].find(
                {"symbol": symbol.upper(), "bar_size": "1 day"},
                {"_id": 0, "symbol": 1, "date": 1, "open": 1, "high": 1,
                 "low": 1, "close": 1, "volume": 1},
            ).sort("date", -1).limit(self.DAILY_HISTORY_DAYS + 5)
            bars = await cursor.to_list(length=self.DAILY_HISTORY_DAYS + 5)
            seen: Dict[str, Dict] = {}
            for b in bars:
                dk = str(b.get("date", ""))[:10]
                if len(dk) == 10 and dk not in seen:
                    seen[dk] = b
            return sorted(seen.values(), key=lambda x: str(x["date"])[:10])
        except Exception as e:
            logger.warning(f"_load_daily_bars({symbol}) failed: {e}")
            return []


# ──────────────────────────── Historical provider (for training) ────────────────────────────


class SectorRegimeHistoricalProvider:
    """Date-indexed sector regime provider for the per-Trade ML
    training loop.

    Pre-loads daily bars for the 11 SPDR sector ETFs + SPY once, then
    exposes ``get_sector_regime_for(symbol, date_str)`` which:
      1. Tags the symbol via `SectorTagService` to find its home ETF.
      2. Looks up the ETF's bars up to ``date_str``.
      3. Runs the same ``_regime_for`` rules used live.

    Caches per ``(etf, date_str)`` because the same ETF/date pair is
    asked thousands of times during training (once per sample whose
    symbol shares that sector).

    Usage:
        provider = SectorRegimeHistoricalProvider(db)
        provider.preload()                                  # ~50ms
        regime = provider.get_sector_regime_for("AAPL", "2024-09-15")
    """

    SECTOR_ETF_LIST = SectorRegimeClassifier.SECTOR_ETF_LIST
    BENCHMARK_SYMBOL = SectorRegimeClassifier.BENCHMARK_SYMBOL
    MIN_BARS = SectorRegimeClassifier.MIN_BARS

    def __init__(self, db):
        self.db = db
        self._bars: Dict[str, List[Dict]] = {}     # {symbol: [oldest..newest daily bars]}
        self._regime_cache: Dict[Tuple[str, str], SectorRegime] = {}
        self._preloaded = False

    def preload(self) -> None:
        """Synchronously load daily bars for all sector ETFs + SPY.

        Uses a sync PyMongo find (the timeseries training uses sync
        Mongo handles). Fail-safe — sectors with no bars get an empty
        list and yield UNKNOWN at lookup time.
        """
        if self._preloaded:
            return
        if self.db is None:
            self._preloaded = True
            return
        symbols = list(self.SECTOR_ETF_LIST) + [self.BENCHMARK_SYMBOL]
        for sym in symbols:
            try:
                cursor = self.db["ib_historical_data"].find(
                    {"symbol": sym, "bar_size": "1 day"},
                    {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1,
                     "close": 1, "volume": 1},
                ).sort("date", 1)
                bars = list(cursor)
                # Dedup by date prefix
                seen: Dict[str, Dict] = {}
                for b in bars:
                    dk = str(b.get("date", ""))[:10]
                    if len(dk) == 10 and dk not in seen:
                        seen[dk] = b
                self._bars[sym] = sorted(seen.values(),
                                         key=lambda x: str(x["date"])[:10])
            except Exception as e:
                logger.debug(f"SectorRegimeHistoricalProvider load {sym} failed: {e}")
                self._bars[sym] = []
        self._preloaded = True
        logger.info(
            "[SECTOR REGIME HIST] preloaded %d ETFs (sample sizes: %s)",
            len(self._bars),
            ", ".join(f"{s}={len(self._bars.get(s, []))}"
                      for s in symbols[:5]),
        )

    def get_sector_regime_for(self, symbol: str, date_str: str) -> SectorRegime:
        """Resolve the symbol's sector regime as of ``date_str`` (any
        ISO-prefix date string; only the YYYY-MM-DD portion is used)."""
        if not self._preloaded:
            self.preload()
        try:
            from services.sector_tag_service import get_sector_tag_service
            etf = get_sector_tag_service(db=self.db).tag_symbol(symbol)
        except Exception:
            etf = None
        if etf is None:
            return SectorRegime.UNKNOWN
        date_key = str(date_str)[:10]
        cache_key = (etf, date_key)
        if cache_key in self._regime_cache:
            return self._regime_cache[cache_key]

        bars = self._bars.get(etf, [])
        spy_bars = self._bars.get(self.BENCHMARK_SYMBOL, [])
        regime = self._regime_at_date(etf, bars, spy_bars, date_key)
        self._regime_cache[cache_key] = regime
        return regime

    def _regime_at_date(self, etf: str, bars: List[Dict],
                        spy_bars: List[Dict], date_key: str) -> SectorRegime:
        """Evaluate ``_regime_for`` using only bars whose date ≤ date_key."""
        eff_bars = [b for b in bars if str(b.get("date", ""))[:10] <= date_key]
        eff_spy = [b for b in spy_bars if str(b.get("date", ""))[:10] <= date_key]
        if len(eff_bars) < self.MIN_BARS:
            return SectorRegime.UNKNOWN
        spy_5d = SectorRegimeClassifier._5d_return_pct(eff_spy)
        # We borrow the live classifier's `_build_sector_snapshot` logic
        # by instantiating a stub classifier with no DB.
        stub = SectorRegimeClassifier(db=None)
        snap = stub._build_sector_snapshot(etf, eff_bars, spy_5d)
        return snap.regime if snap is not None else SectorRegime.UNKNOWN


# ──────────────────────────── ML feature names ────────────────────────────


SECTOR_LABEL_FEATURE_NAMES: List[str] = [
    f"sector_label_{r.value}" for r in SectorRegime.all_active()
]


def build_sector_label_features(regime) -> Dict[str, float]:
    """One-hot encode the symbol's sector regime for the per-Trade ML
    feature vector. UNKNOWN/None returns all-zeros (the all-zero
    baseline)."""
    feats = {n: 0.0 for n in SECTOR_LABEL_FEATURE_NAMES}
    if regime is None:
        return feats
    if isinstance(regime, str):
        try:
            regime = SectorRegime(regime)
        except ValueError:
            return feats
    if regime != SectorRegime.UNKNOWN:
        feats[f"sector_label_{regime.value}"] = 1.0
    return feats


# ──────────────────────────── Module-level singleton ────────────────────────────


_instance: Optional[SectorRegimeClassifier] = None


def get_sector_regime_classifier(db=None) -> SectorRegimeClassifier:
    global _instance
    if _instance is None:
        _instance = SectorRegimeClassifier(db=db)
    elif db is not None and _instance.db is None:
        _instance.db = db
    return _instance
