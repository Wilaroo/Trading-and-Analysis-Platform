"""
Market Regime Features for AI Training & Prediction

Computes regime-context features from SPY, QQQ, and IWM daily bars that get
added to every training sample and prediction. This gives models awareness
of the broader market environment (trending, range-bound, volatile, etc.)
across large-cap (SPY), growth/tech (QQQ), and small-cap (IWM) segments.

Features (24 total):

  Per-index features (6 each x 3 = 18):
    regime_{idx}_trend       -- Price vs 20-SMA, normalized [-1, 1]
    regime_{idx}_rsi         -- 14-period RSI, normalized [-1, 1]
    regime_{idx}_momentum    -- 5-bar return
    regime_{idx}_volatility  -- 10-day ATR as % of price
    regime_{idx}_vol_expansion -- 5d ATR / 20d ATR ratio
    regime_{idx}_breadth     -- % of last 10 bars up, normalized [-1, 1]

  Cross-correlation features (3):
    regime_corr_spy_qqq      -- 10-day return correlation SPY vs QQQ
    regime_corr_spy_iwm      -- 10-day return correlation SPY vs IWM
    regime_corr_qqq_iwm      -- 10-day return correlation QQQ vs IWM

  Rotation / divergence features (3):
    regime_rotation_qqq_spy  -- QQQ/SPY 10-day relative performance (growth vs market)
    regime_rotation_iwm_spy  -- IWM/SPY 10-day relative performance (small vs large)
    regime_rotation_qqq_iwm  -- QQQ/IWM 10-day relative performance (growth vs value)

Usage:
  # During training:
  provider = RegimeFeatureProvider(db)
  provider.preload_index_daily()
  feats = provider.get_regime_features_for_date("2026-03-10")

  # During prediction (live):
  feats = await provider.get_current_regime_features()
"""

import logging
import numpy as np
from typing import Dict, Optional, List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Index symbols we track
REGIME_INDEXES = ["spy", "qqq", "iwm"]

# Per-index feature suffixes
_PER_INDEX_SUFFIXES = ["trend", "rsi", "momentum", "volatility", "vol_expansion", "breadth"]

# Build the full feature name list
REGIME_FEATURE_NAMES = []
for idx in REGIME_INDEXES:
    for suffix in _PER_INDEX_SUFFIXES:
        REGIME_FEATURE_NAMES.append(f"regime_{idx}_{suffix}")

# Cross-correlation features
REGIME_FEATURE_NAMES.extend([
    "regime_corr_spy_qqq",
    "regime_corr_spy_iwm",
    "regime_corr_qqq_iwm",
])

# Rotation / relative strength features
REGIME_FEATURE_NAMES.extend([
    "regime_rotation_qqq_spy",
    "regime_rotation_iwm_spy",
    "regime_rotation_qqq_iwm",
])


def _compute_rsi(closes: np.ndarray, period: int = 14) -> float:
    """Compute RSI from close prices (most recent first)."""
    if len(closes) < period + 1:
        return 50.0
    c = closes[:period + 1][::-1]
    deltas = np.diff(c)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains) if len(gains) > 0 else 0
    avg_loss = np.mean(losses) if len(losses) > 0 else 0.0001
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _compute_atr_values(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> List[float]:
    """Compute true range values for `period` bars (most-recent-first arrays)."""
    n = len(closes)
    vals = []
    for i in range(min(period, n - 1)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i + 1]) if i + 1 < n else highs[i] - lows[i],
            abs(lows[i] - closes[i + 1]) if i + 1 < n else highs[i] - lows[i],
        )
        vals.append(tr)
    return vals


def _compute_return_series(closes: np.ndarray, length: int) -> np.ndarray:
    """Compute bar-to-bar returns for the most recent `length` bars (most-recent-first)."""
    if len(closes) < length + 1:
        length = len(closes) - 1
    if length < 1:
        return np.array([0.0])
    returns = []
    for i in range(length):
        prev = closes[i + 1]
        if prev > 0:
            returns.append((closes[i] - prev) / prev)
        else:
            returns.append(0.0)
    return np.array(returns)


def compute_single_index_features(
    prefix: str,
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
) -> Dict[str, float]:
    """
    Compute the 6 regime features for a single index.

    Args:
        prefix: Feature name prefix (e.g., "regime_spy")
        closes, highs, lows: Arrays in most-recent-first order, at least 25 bars.
    """
    feats = {}
    n = len(closes)

    if n < 25:
        for suffix in _PER_INDEX_SUFFIXES:
            feats[f"{prefix}_{suffix}"] = 0.0
        return feats

    current = closes[0]

    # 1. Trend: price vs 20-SMA, clipped to [-1, 1]
    sma_20 = np.mean(closes[:20])
    if sma_20 > 0:
        dist = (current - sma_20) / sma_20
        feats[f"{prefix}_trend"] = max(-1.0, min(1.0, dist / 0.02))
    else:
        feats[f"{prefix}_trend"] = 0.0

    # 2. RSI (normalized to [-1, 1])
    rsi = _compute_rsi(closes, 14)
    feats[f"{prefix}_rsi"] = (rsi - 50) / 50

    # 3. 5-bar momentum
    if n > 4 and closes[4] > 0:
        feats[f"{prefix}_momentum"] = (closes[0] - closes[4]) / closes[4]
    else:
        feats[f"{prefix}_momentum"] = 0.0

    # 4. Realized volatility (10-day ATR as % of price)
    atr_vals = _compute_atr_values(highs, lows, closes, 10)
    atr_10 = np.mean(atr_vals) if atr_vals else 0
    feats[f"{prefix}_volatility"] = atr_10 / current if current > 0 else 0

    # 5. Volatility expansion (5d ATR / 20d ATR)
    atr_5 = np.mean(atr_vals[:5]) if len(atr_vals) >= 5 else atr_10
    atr_20_vals = _compute_atr_values(highs, lows, closes, 20)
    atr_20 = np.mean(atr_20_vals) if atr_20_vals else atr_10
    feats[f"{prefix}_vol_expansion"] = (atr_5 / atr_20) if atr_20 > 0 else 1.0

    # 6. Breadth proxy: % of last 10 bars that closed up, normalized [-1, 1]
    up_count = 0
    bar_count = min(10, n - 1)
    for i in range(bar_count):
        if closes[i] > closes[i + 1]:
            up_count += 1
    feats[f"{prefix}_breadth"] = (up_count / bar_count) * 2 - 1 if bar_count > 0 else 0.0

    return feats


def compute_cross_features(
    spy_closes: np.ndarray,
    qqq_closes: np.ndarray,
    iwm_closes: np.ndarray,
) -> Dict[str, float]:
    """
    Compute cross-correlation and rotation features between the 3 indexes.
    All arrays are most-recent-first, at least 11 bars.
    """
    feats = {}

    # Return series for correlation (10-bar)
    spy_ret = _compute_return_series(spy_closes, 10)
    qqq_ret = _compute_return_series(qqq_closes, 10)
    iwm_ret = _compute_return_series(iwm_closes, 10)

    def _safe_corr(a: np.ndarray, b: np.ndarray) -> float:
        if len(a) < 3 or len(b) < 3:
            return 0.0
        min_len = min(len(a), len(b))
        a, b = a[:min_len], b[:min_len]
        if np.std(a) == 0 or np.std(b) == 0:
            return 0.0
        corr = np.corrcoef(a, b)[0, 1]
        return 0.0 if np.isnan(corr) else float(corr)

    feats["regime_corr_spy_qqq"] = _safe_corr(spy_ret, qqq_ret)
    feats["regime_corr_spy_iwm"] = _safe_corr(spy_ret, iwm_ret)
    feats["regime_corr_qqq_iwm"] = _safe_corr(qqq_ret, iwm_ret)

    # Rotation / relative strength: 10-bar cumulative return difference
    def _cum_return(closes: np.ndarray, period: int) -> float:
        if len(closes) <= period or closes[period] == 0:
            return 0.0
        return (closes[0] - closes[period]) / closes[period]

    spy_10 = _cum_return(spy_closes, 10)
    qqq_10 = _cum_return(qqq_closes, 10)
    iwm_10 = _cum_return(iwm_closes, 10)

    feats["regime_rotation_qqq_spy"] = qqq_10 - spy_10  # Positive = growth leading
    feats["regime_rotation_iwm_spy"] = iwm_10 - spy_10  # Positive = small-cap leading
    feats["regime_rotation_qqq_iwm"] = qqq_10 - iwm_10  # Positive = growth > value

    return feats


def compute_regime_features_from_bars(
    spy_closes: np.ndarray,
    spy_highs: np.ndarray,
    spy_lows: np.ndarray,
    qqq_closes: np.ndarray = None,
    qqq_highs: np.ndarray = None,
    qqq_lows: np.ndarray = None,
    iwm_closes: np.ndarray = None,
    iwm_highs: np.ndarray = None,
    iwm_lows: np.ndarray = None,
) -> Dict[str, float]:
    """
    Compute all regime features from index OHLC arrays (most-recent-first order).
    Needs at least 25 bars per index.

    Backward compatible: if QQQ/IWM arrays are not provided, their features
    and cross features default to 0.0.
    """
    feats = {}

    # SPY features (always available)
    feats.update(compute_single_index_features("regime_spy", spy_closes, spy_highs, spy_lows))

    # QQQ features
    if qqq_closes is not None and len(qqq_closes) >= 25:
        feats.update(compute_single_index_features("regime_qqq", qqq_closes, qqq_highs, qqq_lows))
    else:
        for suffix in _PER_INDEX_SUFFIXES:
            feats[f"regime_qqq_{suffix}"] = 0.0

    # IWM features
    if iwm_closes is not None and len(iwm_closes) >= 25:
        feats.update(compute_single_index_features("regime_iwm", iwm_closes, iwm_highs, iwm_lows))
    else:
        for suffix in _PER_INDEX_SUFFIXES:
            feats[f"regime_iwm_{suffix}"] = 0.0

    # Cross-correlation and rotation features
    if (qqq_closes is not None and len(qqq_closes) >= 11 and
            iwm_closes is not None and len(iwm_closes) >= 11):
        feats.update(compute_cross_features(spy_closes, qqq_closes, iwm_closes))
    else:
        feats["regime_corr_spy_qqq"] = 0.0
        feats["regime_corr_spy_iwm"] = 0.0
        feats["regime_corr_qqq_iwm"] = 0.0
        feats["regime_rotation_qqq_spy"] = 0.0
        feats["regime_rotation_iwm_spy"] = 0.0
        feats["regime_rotation_qqq_iwm"] = 0.0

    return feats


class RegimeFeatureProvider:
    """
    Provides regime features for training (historical) and prediction (live).

    For training: preloads SPY, QQQ, IWM daily bars and creates date->index lookups.
    For prediction: computes from most recent bars of all 3 indexes.
    """

    # Symbols to load
    INDEX_SYMBOLS = {"spy": "SPY", "qqq": "QQQ", "iwm": "IWM"}

    def __init__(self, db=None):
        self._db = db
        self._loaded = False
        # Per-index data storage
        self._data = {}  # key -> {"dates": [], "closes": np.array, "highs": np.array, "lows": np.array, "date_to_idx": {}}
        for key in self.INDEX_SYMBOLS:
            self._data[key] = {
                "dates": [],
                "closes": np.array([]),
                "highs": np.array([]),
                "lows": np.array([]),
                "date_to_idx": {},
            }

    def preload_index_daily(self) -> int:
        """
        Load daily bars for SPY, QQQ, and IWM from ib_historical_data.
        Returns total number of bars loaded across all indexes.
        """
        if self._db is None:
            logger.warning("No DB connection for regime feature provider")
            return 0

        total = 0
        for key, symbol in self.INDEX_SYMBOLS.items():
            count = self._load_single_index(key, symbol)
            total += count

        self._loaded = any(
            len(self._data[k]["dates"]) >= 25 for k in self.INDEX_SYMBOLS
        )
        return total

    # Backward-compatible alias
    def preload_spy_daily(self) -> int:
        """Backward-compatible alias that loads all indexes."""
        return self.preload_index_daily()

    def _load_single_index(self, key: str, symbol: str) -> int:
        """Load daily bars for a single index symbol."""
        try:
            bars = list(self._db["ib_historical_data"].find(
                {"symbol": symbol, "bar_size": "1 day"},
                {"_id": 0, "date": 1, "close": 1, "high": 1, "low": 1},
            ).sort("date", -1).limit(10000).max_time_ms(30000))
            bars.reverse()  # Back to chronological order

            if not bars:
                logger.warning(f"No {symbol} daily bars found for regime features")
                return 0

            # Deduplicate by date (take first 10 chars as date key, keep last per date)
            seen = {}
            for b in bars:
                date_key = str(b.get("date", ""))[:10]
                if len(date_key) == 10:
                    seen[date_key] = b

            deduped = sorted(seen.values(), key=lambda x: str(x["date"])[:10])
            if not deduped:
                logger.warning(f"No valid {symbol} daily bars after dedup")
                return 0

            self._data[key]["dates"] = [str(b["date"])[:10] for b in deduped]
            self._data[key]["closes"] = np.array([b["close"] for b in deduped], dtype=float)
            self._data[key]["highs"] = np.array([b["high"] for b in deduped], dtype=float)
            self._data[key]["lows"] = np.array([b["low"] for b in deduped], dtype=float)
            self._data[key]["date_to_idx"] = {d: i for i, d in enumerate(self._data[key]["dates"])}

            logger.info(
                f"Regime provider: loaded {len(deduped)} {symbol} daily bars "
                f"({self._data[key]['dates'][0]} to {self._data[key]['dates'][-1]})"
            )
            return len(deduped)

        except Exception as e:
            logger.error(f"Failed to preload {symbol} bars for regime: {e}")
            return 0

    def _get_index_window(self, key: str, date_str: str, lookback: int = 30):
        """
        Get most-recent-first OHLC arrays for an index at a given date.
        Returns (closes, highs, lows) or (None, None, None) if unavailable.
        """
        data = self._data[key]
        if not data["dates"]:
            return None, None, None

        clean_date = date_str[:10] if date_str else ""
        idx = data["date_to_idx"].get(clean_date)

        if idx is None:
            # Find closest previous date
            for i in range(len(data["dates"]) - 1, -1, -1):
                if data["dates"][i] <= clean_date:
                    idx = i
                    break

        if idx is None or idx < lookback - 1:
            return None, None, None

        window = min(lookback, idx + 1)
        c = data["closes"][idx - window + 1: idx + 1][::-1]
        h = data["highs"][idx - window + 1: idx + 1][::-1]
        lo = data["lows"][idx - window + 1: idx + 1][::-1]
        return c, h, lo

    def get_regime_features_for_date(self, date_str: str) -> Dict[str, float]:
        """
        Get regime features for a specific date during training.

        Args:
            date_str: Date string like "2026-03-10" (or with time for intraday).

        Returns:
            Dict of all 24 regime feature name -> value.
        """
        if not self._loaded:
            return {name: 0.0 for name in REGIME_FEATURE_NAMES}

        spy_c, spy_h, spy_l = self._get_index_window("spy", date_str)
        qqq_c, qqq_h, qqq_l = self._get_index_window("qqq", date_str)
        iwm_c, iwm_h, iwm_l = self._get_index_window("iwm", date_str)

        if spy_c is None or len(spy_c) < 25:
            return {name: 0.0 for name in REGIME_FEATURE_NAMES}

        return compute_regime_features_from_bars(
            spy_c, spy_h, spy_l,
            qqq_c, qqq_h, qqq_l,
            iwm_c, iwm_h, iwm_l,
        )

    async def get_current_regime_features(self) -> Dict[str, float]:
        """
        Get regime features for the current moment (for live predictions).
        Uses the most recent daily bars from DB for SPY, QQQ, IWM.
        """
        if self._db is None:
            return {name: 0.0 for name in REGIME_FEATURE_NAMES}

        try:
            import asyncio
            loop = asyncio.get_event_loop()

            def _query_index(symbol: str):
                pipeline = [
                    {"$match": {"symbol": symbol, "bar_size": "1 day"}},
                    {"$addFields": {"date_key": {"$substr": [{"$toString": "$date"}, 0, 10]}}},
                    {"$sort": {"date": -1}},
                    {"$group": {
                        "_id": "$date_key",
                        "close": {"$first": "$close"},
                        "high": {"$first": "$high"},
                        "low": {"$first": "$low"},
                    }},
                    {"$sort": {"_id": -1}},
                    {"$limit": 30},
                ]
                try:
                    real_bars = list(self._db["ib_historical_data"].aggregate(pipeline, allowDiskUse=True))
                except Exception:
                    return None, None, None
                if len(real_bars) < 25:
                    return None, None, None
                c = np.array([b["close"] for b in real_bars], dtype=float)
                h = np.array([b["high"] for b in real_bars], dtype=float)
                lo = np.array([b["low"] for b in real_bars], dtype=float)
                return c, h, lo

            def _query_all():
                results = {}
                for key, symbol in self.INDEX_SYMBOLS.items():
                    results[key] = _query_index(symbol)
                return results

            results = await loop.run_in_executor(None, _query_all)

            spy_c, spy_h, spy_l = results.get("spy", (None, None, None))
            qqq_c, qqq_h, qqq_l = results.get("qqq", (None, None, None))
            iwm_c, iwm_h, iwm_l = results.get("iwm", (None, None, None))

            if spy_c is None:
                return {name: 0.0 for name in REGIME_FEATURE_NAMES}

            return compute_regime_features_from_bars(
                spy_c, spy_h, spy_l,
                qqq_c, qqq_h, qqq_l,
                iwm_c, iwm_h, iwm_l,
            )

        except Exception as e:
            logger.warning(f"Failed to get current regime features: {e}")
            return {name: 0.0 for name in REGIME_FEATURE_NAMES}
