"""
MultiIndexRegimeClassifier — broad-market regime label from SPY/QQQ/IWM/DIA.
=============================================================================

The numerical regime features (`services/ai_modules/regime_features.py`)
already feed the per-Trade ML model the granular trend / RSI / momentum
of SPY/QQQ/IWM. What this module adds is a *categorical regime label*
derived from those same indices PLUS DIA, so:

  1. Setup-landscape AI briefings can drop human-readable lines like
     "today SPY is up but IWM is leading — I'm tilting toward IWM-
     correlated names" without having to interpret 24 floats.

  2. The label is one-hot encoded and added to the per-Trade ML feature
     vector as `regime_label_<name>` so the models *also* train on the
     categorical bin (cheap leakage-free signal that their decision
     trees can carve along).

This is a SOFT gate, not a hard gate. The label is metadata + features;
it does not block alerts. (See `/app/memory/ROADMAP.md` 2026-04-29
evening decision: hard gates only at Time / In-Play / Confidence.)

Public API:
    classifier = get_multi_index_regime_classifier(db=db)
    res = await classifier.classify()    # market-wide, no symbol arg
    # res.label  → "risk_on_broad", "bullish_divergence", etc.
    # res.confidence ∈ [0, 1]
    # res.reasoning ['SPY +0.8% above 20SMA, ...', ...]

Caching: results are cached for 5 minutes (the regime moves on the
multi-day timescale). The cache is invalidated by `invalidate()`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ──────────────────────────── ENUMS ────────────────────────────

class MultiIndexRegime(str, Enum):
    """Composite multi-index regime labels.

    9 buckets (8 active + UNKNOWN) chosen for *operator readability*,
    not statistical purity. The ML model gets each as a one-hot feature
    so it can learn its own preferences.
    """
    RISK_ON_BROAD          = "risk_on_broad"          # all 4 indices up, breadth strong
    RISK_ON_GROWTH         = "risk_on_growth"         # QQQ leading, IWM/DIA mild positive
    RISK_ON_SMALLCAP       = "risk_on_smallcap"       # IWM leading, classic risk-on rotation
    RISK_OFF_BROAD         = "risk_off_broad"         # all 4 down
    RISK_OFF_DEFENSIVE     = "risk_off_defensive"     # DIA holding, QQQ/IWM falling
    BULLISH_DIVERGENCE     = "bullish_divergence"     # IWM up, SPY flat/down (early bottom)
    BEARISH_DIVERGENCE     = "bearish_divergence"     # SPY up, IWM down (warning sign)
    MIXED                  = "mixed"                  # no clear leadership
    UNKNOWN                = "unknown"                # insufficient data

    @classmethod
    def all_active(cls) -> List["MultiIndexRegime"]:
        """All regimes except UNKNOWN — used to build one-hot feature names."""
        return [r for r in cls if r != cls.UNKNOWN]


# ──────────────────────────── DATA CLASS ────────────────────────────

@dataclass
class IndexSnapshot:
    """Per-index summary numbers used by the classifier."""
    symbol: str
    last_close: float
    sma20: float
    trend_pct: float          # (last_close - sma20) / sma20  * 100
    momentum_5d_pct: float    # (last - 5d ago) / 5d ago * 100
    breadth_pct: float        # % of last 10 bars closing up (0-100)


@dataclass
class RegimeResult:
    label: MultiIndexRegime
    confidence: float                                       # 0-1
    reasoning: List[str] = field(default_factory=list)
    indices: Dict[str, IndexSnapshot] = field(default_factory=dict)
    classified_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ──────────────────────────── CLASSIFIER ────────────────────────────

class MultiIndexRegimeClassifier:
    """Classifies the *current* multi-index regime once per cache window.

    Reads ~30 daily bars for SPY, QQQ, IWM, DIA from `ib_historical_data`
    (no extra IB calls), summarises each index, then assigns a composite
    label. Caches market-wide for 5 minutes since this is a daily-bar
    derived label.
    """

    INDEX_SYMBOLS = ("SPY", "QQQ", "IWM", "DIA")
    CACHE_TTL_SECONDS = 300        # 5 min market-wide cache
    DAILY_HISTORY_DAYS = 25
    MIN_BARS_FOR_CLASSIFY = 21     # need ≥21 to compute SMA20

    # Thresholds (in % unless otherwise noted)
    STRONG_TREND_PCT      = 1.5    # |trend| ≥ 1.5% of SMA20 = clear trend
    MILD_TREND_PCT        = 0.4    # below this = effectively flat
    DIVERGENCE_GAP_PCT    = 1.0    # SPY vs IWM trend gap to call divergence
    BREADTH_BULL          = 60     # ≥60% up days = strong breadth
    BREADTH_BEAR          = 40     # ≤40% up days = weak breadth

    def __init__(self, db=None):
        self.db = db
        self._cached_result: Optional[RegimeResult] = None
        self._cached_at: Optional[datetime] = None
        self._daily_count: Dict[MultiIndexRegime, int] = {}
        self._cache_hits = 0
        self._cache_misses = 0

    # ───────── Public API ─────────

    async def classify(
        self,
        index_bars: Optional[Dict[str, List[Dict]]] = None,
    ) -> RegimeResult:
        """Classify the current multi-index regime.

        ``index_bars`` is an optional pre-loaded mapping of symbol →
        list-of-daily-bar-dicts (most-recent-LAST). If not provided,
        loads from MongoDB.
        """
        # Cache hit?
        now = datetime.now(timezone.utc)
        if self._cached_result is not None and self._cached_at is not None:
            if (now - self._cached_at).total_seconds() < self.CACHE_TTL_SECONDS:
                self._cache_hits += 1
                return self._cached_result
        self._cache_misses += 1

        bar_map: Dict[str, List[Dict]] = index_bars or {}
        for sym in self.INDEX_SYMBOLS:
            if sym not in bar_map:
                bar_map[sym] = await self._load_daily_bars(sym)

        snapshots: Dict[str, IndexSnapshot] = {}
        for sym, bars in bar_map.items():
            snap = self._summarise_index(sym, bars)
            if snap is not None:
                snapshots[sym] = snap

        if "SPY" not in snapshots or len(snapshots) < 3:
            result = RegimeResult(
                label=MultiIndexRegime.UNKNOWN,
                confidence=0.0,
                reasoning=[
                    f"Insufficient index data: have {sorted(snapshots.keys())}, "
                    f"need at least SPY + 2 others"
                ],
                indices=snapshots,
            )
        else:
            label, conf, reasons = self._assign_label(snapshots)
            result = RegimeResult(
                label=label, confidence=conf, reasoning=reasons, indices=snapshots,
            )

        self._cached_result = result
        self._cached_at = now
        self._daily_count[result.label] = self._daily_count.get(result.label, 0) + 1
        return result

    def stats(self) -> Dict:
        total = self._cache_hits + self._cache_misses
        return {
            "classified_today": {r.value: n for r, n in self._daily_count.items()},
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "cache_hit_rate": (self._cache_hits / total) if total else 0.0,
            "current_label": (
                self._cached_result.label.value if self._cached_result else None
            ),
        }

    def invalidate(self) -> None:
        self._cached_result = None
        self._cached_at = None

    # ───────── Per-index summary ─────────

    @staticmethod
    def _summarise_index(symbol: str, bars: List[Dict]) -> Optional[IndexSnapshot]:
        """Build an IndexSnapshot from oldest-first daily bars."""
        if not bars or len(bars) < MultiIndexRegimeClassifier.MIN_BARS_FOR_CLASSIFY:
            return None
        closes = [b.get("close", 0.0) for b in bars[-21:]]
        if any(c <= 0 for c in closes):
            return None
        last_close = closes[-1]
        sma20 = sum(closes[-21:-1]) / 20  # SMA over the prior 20 bars
        if sma20 <= 0:
            return None
        trend_pct = ((last_close - sma20) / sma20) * 100
        # 5-day momentum
        if len(bars) >= 6:
            five_back = bars[-6].get("close", 0.0)
            mom_pct = ((last_close - five_back) / five_back) * 100 if five_back > 0 else 0.0
        else:
            mom_pct = 0.0
        # Breadth: % of last 10 bars closing up
        recent = bars[-11:] if len(bars) >= 11 else bars
        ups = 0
        comparisons = 0
        for prev, cur in zip(recent[:-1], recent[1:]):
            pc = prev.get("close", 0.0)
            cc = cur.get("close", 0.0)
            if pc > 0 and cc > 0:
                comparisons += 1
                if cc > pc:
                    ups += 1
        breadth = (ups / comparisons * 100) if comparisons > 0 else 50.0
        return IndexSnapshot(
            symbol=symbol,
            last_close=last_close,
            sma20=sma20,
            trend_pct=trend_pct,
            momentum_5d_pct=mom_pct,
            breadth_pct=breadth,
        )

    # ───────── Label assignment ─────────

    def _assign_label(
        self, snaps: Dict[str, IndexSnapshot],
    ) -> Tuple[MultiIndexRegime, float, List[str]]:
        """Apply rule-based labelling. Returns (label, confidence, reasons)."""
        spy = snaps.get("SPY")
        qqq = snaps.get("QQQ")
        iwm = snaps.get("IWM")
        dia = snaps.get("DIA")

        # Trend signs (positive / negative / flat) per index
        def _sign(s: Optional[IndexSnapshot]) -> int:
            if s is None or abs(s.trend_pct) < self.MILD_TREND_PCT:
                return 0
            return 1 if s.trend_pct > 0 else -1

        spy_sign = _sign(spy)
        qqq_sign = _sign(qqq)
        iwm_sign = _sign(iwm)
        dia_sign = _sign(dia)
        signs_present = [s for s in (spy_sign, qqq_sign, iwm_sign, dia_sign) if s is not None]
        positives = sum(1 for s in signs_present if s == 1)
        negatives = sum(1 for s in signs_present if s == -1)
        n = len(signs_present)

        reasons: List[str] = []
        for label, snap in (("SPY", spy), ("QQQ", qqq), ("IWM", iwm), ("DIA", dia)):
            if snap is not None:
                reasons.append(
                    f"{label}: {snap.trend_pct:+.2f}% vs 20SMA, 5d {snap.momentum_5d_pct:+.2f}%, "
                    f"breadth {snap.breadth_pct:.0f}%"
                )
            else:
                reasons.append(f"{label}: no data")

        # Detect cross-index divergence first (more specific)
        if spy is not None and iwm is not None:
            gap = spy.trend_pct - iwm.trend_pct
            # IWM clearly outperforming SPY — small-cap leadership
            if gap <= -self.DIVERGENCE_GAP_PCT and iwm.trend_pct > 0 and spy_sign <= 0:
                reasons.append(
                    f"Divergence: IWM trend {iwm.trend_pct:+.1f}% > SPY {spy.trend_pct:+.1f}% "
                    "(small-cap risk-on)"
                )
                conf = min(abs(gap) / 3.0, 1.0)
                return MultiIndexRegime.BULLISH_DIVERGENCE, conf, reasons
            # SPY up but IWM rolling — distribution warning
            if gap >= self.DIVERGENCE_GAP_PCT and spy.trend_pct > 0 and iwm_sign <= 0:
                reasons.append(
                    f"Divergence: SPY trend {spy.trend_pct:+.1f}% > IWM {iwm.trend_pct:+.1f}% "
                    "(narrow rally / distribution risk)"
                )
                conf = min(abs(gap) / 3.0, 1.0)
                return MultiIndexRegime.BEARISH_DIVERGENCE, conf, reasons

        # Broad regimes
        if positives == n and n >= 3:
            # All up — distinguish growth-led vs smallcap-led vs broad
            if iwm is not None and qqq is not None and iwm.trend_pct > qqq.trend_pct + 0.3:
                conf = self._broad_confidence(snaps)
                reasons.append(
                    f"All indices up; IWM {iwm.trend_pct:+.1f}% leads QQQ {qqq.trend_pct:+.1f}%"
                )
                return MultiIndexRegime.RISK_ON_SMALLCAP, conf, reasons
            if qqq is not None and spy is not None and qqq.trend_pct > spy.trend_pct + 0.3:
                conf = self._broad_confidence(snaps)
                reasons.append(
                    f"All indices up; QQQ {qqq.trend_pct:+.1f}% leads SPY {spy.trend_pct:+.1f}%"
                )
                return MultiIndexRegime.RISK_ON_GROWTH, conf, reasons
            conf = self._broad_confidence(snaps)
            reasons.append("All indices up with similar magnitudes — broad participation")
            return MultiIndexRegime.RISK_ON_BROAD, conf, reasons

        if negatives == n and n >= 3:
            # All down — distinguish defensive (DIA holds best) vs broad
            if dia is not None and iwm is not None and dia.trend_pct - iwm.trend_pct > 1.0:
                conf = self._broad_confidence(snaps)
                reasons.append(
                    f"All down but DIA {dia.trend_pct:+.1f}% holds vs IWM {iwm.trend_pct:+.1f}%"
                )
                return MultiIndexRegime.RISK_OFF_DEFENSIVE, conf, reasons
            conf = self._broad_confidence(snaps)
            reasons.append("All indices down — broad selling")
            return MultiIndexRegime.RISK_OFF_BROAD, conf, reasons

        # Majority cases without unanimous direction
        if positives >= 3 and qqq is not None and qqq_sign == 1:
            reasons.append(f"{positives}/{n} indices up; growth (QQQ) participating")
            return MultiIndexRegime.RISK_ON_GROWTH, 0.6, reasons
        if negatives >= 3 and dia is not None and dia_sign == -1:
            reasons.append(f"{negatives}/{n} indices down")
            return MultiIndexRegime.RISK_OFF_BROAD, 0.6, reasons

        # Default: mixed
        reasons.append(
            f"No clear leadership: {positives} up, {negatives} down, "
            f"{n - positives - negatives} flat"
        )
        return MultiIndexRegime.MIXED, 0.5, reasons

    @staticmethod
    def _broad_confidence(snaps: Dict[str, IndexSnapshot]) -> float:
        """Confidence proportional to mean abs trend across indices."""
        trends = [abs(s.trend_pct) for s in snaps.values()]
        if not trends:
            return 0.5
        avg = sum(trends) / len(trends)
        # Saturate at 3% mean trend
        return min(0.5 + (avg / 6.0), 1.0)

    # ───────── Helpers ─────────

    async def _load_daily_bars(self, symbol: str) -> List[Dict]:
        """Load up to N daily bars (oldest-first) for the given symbol."""
        if self.db is None:
            return []
        try:
            cursor = self.db["ib_historical_data"].find(
                {"symbol": symbol.upper(), "bar_size": "1 day"},
                {"_id": 0, "symbol": 1, "date": 1, "open": 1, "high": 1,
                 "low": 1, "close": 1, "volume": 1},
            ).sort("date", -1).limit(self.DAILY_HISTORY_DAYS + 5)
            bars = await cursor.to_list(length=self.DAILY_HISTORY_DAYS + 5)
            # Deduplicate by date (date string up to first 10 chars)
            seen: Dict[str, Dict] = {}
            for b in bars:
                dk = str(b.get("date", ""))[:10]
                if len(dk) == 10 and dk not in seen:
                    seen[dk] = b
            deduped = sorted(seen.values(), key=lambda x: str(x["date"])[:10])
            return deduped
        except Exception as e:
            logger.warning(f"_load_daily_bars({symbol}) failed: {e}")
            return []


# ──────────────────────────── ONE-HOT FEATURE NAMES ────────────────────────────

# These are the names emitted into the per-Trade ML feature vector when
# the model expects regime-label features. Built from the enum so they
# stay in sync.
REGIME_LABEL_FEATURE_NAMES: List[str] = [
    f"regime_label_{r.value}" for r in MultiIndexRegime.all_active()
]


def build_regime_label_features(label: MultiIndexRegime | str) -> Dict[str, float]:
    """Return a {feature_name: 0.0/1.0} dict for the given regime label.

    UNKNOWN/unrecognised labels yield an all-zeros dict (no feature
    fires). Caller can mix this into the combined feature dict before
    aligning with ``model._feature_names``.
    """
    if isinstance(label, str):
        try:
            label = MultiIndexRegime(label)
        except ValueError:
            label = MultiIndexRegime.UNKNOWN
    feats = {name: 0.0 for name in REGIME_LABEL_FEATURE_NAMES}
    if label != MultiIndexRegime.UNKNOWN:
        feats[f"regime_label_{label.value}"] = 1.0
    return feats


def derive_regime_label_from_features(regime_feats: Dict[str, float]) -> MultiIndexRegime:
    """Derive a `MultiIndexRegime` label from already-computed numerical
    regime features (the 24-feature output of
    `services.ai_modules.regime_features.compute_regime_features_from_bars`).

    Used at training time so each historical sample gets a categorical
    label without re-loading SPY/QQQ/IWM/DIA bars.

    The mapping mirrors `MultiIndexRegimeClassifier._assign_label` but
    works off the *trend / momentum / breadth* features already in the
    dict. Note: training does not yet have DIA features (regime_features
    only loads SPY/QQQ/IWM), so any logic that needs DIA falls through
    to the SPY/QQQ/IWM-only branches.
    """
    spy_trend = regime_feats.get("regime_spy_trend", 0.0) * 2.0  # un-normalize: feat is ÷0.02
    qqq_trend = regime_feats.get("regime_qqq_trend", 0.0) * 2.0
    iwm_trend = regime_feats.get("regime_iwm_trend", 0.0) * 2.0
    rotation_iwm_spy = regime_feats.get("regime_rotation_iwm_spy", 0.0)

    # All features can be 0 if data was insufficient at training time
    if spy_trend == 0.0 and qqq_trend == 0.0 and iwm_trend == 0.0:
        return MultiIndexRegime.UNKNOWN

    cls = MultiIndexRegimeClassifier
    mild = cls.MILD_TREND_PCT
    div_gap = cls.DIVERGENCE_GAP_PCT

    def _sign(t: float) -> int:
        if abs(t) < mild:
            return 0
        return 1 if t > 0 else -1

    spy_s, qqq_s, iwm_s = _sign(spy_trend), _sign(qqq_trend), _sign(iwm_trend)

    # Divergences first
    gap = spy_trend - iwm_trend
    if gap <= -div_gap and iwm_trend > 0 and spy_s <= 0:
        return MultiIndexRegime.BULLISH_DIVERGENCE
    if gap >= div_gap and spy_trend > 0 and iwm_s <= 0:
        return MultiIndexRegime.BEARISH_DIVERGENCE

    positives = sum(1 for s in (spy_s, qqq_s, iwm_s) if s == 1)
    negatives = sum(1 for s in (spy_s, qqq_s, iwm_s) if s == -1)

    # All-up branch
    if positives == 3:
        if iwm_trend > qqq_trend + 0.3:
            return MultiIndexRegime.RISK_ON_SMALLCAP
        if qqq_trend > spy_trend + 0.3:
            return MultiIndexRegime.RISK_ON_GROWTH
        return MultiIndexRegime.RISK_ON_BROAD

    # All-down branch (no DIA — falls to broad)
    if negatives == 3:
        return MultiIndexRegime.RISK_OFF_BROAD

    # Majorities
    if positives >= 2 and qqq_s == 1:
        return MultiIndexRegime.RISK_ON_GROWTH
    if positives >= 2 and rotation_iwm_spy > 0.01:
        return MultiIndexRegime.RISK_ON_SMALLCAP
    if negatives >= 2:
        return MultiIndexRegime.RISK_OFF_BROAD

    return MultiIndexRegime.MIXED


# ──────────────────────────── Module-level singleton ────────────────────────────

_classifier_instance: Optional[MultiIndexRegimeClassifier] = None


def get_multi_index_regime_classifier(db=None) -> MultiIndexRegimeClassifier:
    """Singleton accessor — pass `db` once on first call."""
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = MultiIndexRegimeClassifier(db=db)
    elif db is not None and _classifier_instance.db is None:
        _classifier_instance.db = db
    return _classifier_instance
