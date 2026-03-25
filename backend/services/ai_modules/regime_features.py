"""
Market Regime Features for AI Training & Prediction

Computes regime-context features from SPY daily bars that get added to every
training sample and prediction. This gives models awareness of the broader
market environment (trending, range-bound, volatile, etc.).

Features (6 total):
  regime_spy_trend       — SPY above/below 20-SMA (1 = above, -1 = below)
  regime_spy_rsi         — SPY 14-period RSI, normalized to [-1, 1]
  regime_spy_momentum    — SPY 5-bar return
  regime_volatility      — SPY 10-day realized volatility (ATR-based)
  regime_vol_expansion   — Volatility expanding? (5d ATR / 20d ATR ratio)
  regime_breadth_proxy   — % of last 10 bars that closed up

Usage:
  # During training:
  provider = RegimeFeatureProvider(db)
  provider.preload_spy_daily()
  feats = provider.get_regime_features_for_date("2026-03-10")

  # During prediction (live):
  feats = await provider.get_current_regime_features()
"""

import logging
import numpy as np
from typing import Dict, Optional, List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

REGIME_FEATURE_NAMES = [
    "regime_spy_trend",
    "regime_spy_rsi",
    "regime_spy_momentum",
    "regime_volatility",
    "regime_vol_expansion",
    "regime_breadth_proxy",
]


def _compute_rsi(closes: np.ndarray, period: int = 14) -> float:
    """Compute RSI from close prices (most recent first)."""
    if len(closes) < period + 1:
        return 50.0
    # closes is most-recent-first, reverse for chronological
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


def compute_regime_features_from_bars(
    spy_closes: np.ndarray,
    spy_highs: np.ndarray,
    spy_lows: np.ndarray,
) -> Dict[str, float]:
    """
    Compute regime features from SPY OHLC arrays (most-recent-first order).
    Needs at least 25 bars.
    """
    feats = {}
    n = len(spy_closes)

    if n < 25:
        # Not enough data — return neutral defaults
        return {name: 0.0 for name in REGIME_FEATURE_NAMES}

    # 1. SPY Trend: price vs 20-SMA
    sma_20 = np.mean(spy_closes[:20])
    current = spy_closes[0]
    if sma_20 > 0:
        dist = (current - sma_20) / sma_20
        # Clip to [-1, 1], scale so ±2% → ±1
        feats["regime_spy_trend"] = max(-1.0, min(1.0, dist / 0.02))
    else:
        feats["regime_spy_trend"] = 0.0

    # 2. SPY RSI (normalized to [-1, 1] where 50 → 0)
    rsi = _compute_rsi(spy_closes, 14)
    feats["regime_spy_rsi"] = (rsi - 50) / 50  # [-1, 1]

    # 3. SPY 5-bar momentum (return)
    if spy_closes[4] > 0:
        feats["regime_spy_momentum"] = (spy_closes[0] - spy_closes[4]) / spy_closes[4]
    else:
        feats["regime_spy_momentum"] = 0.0

    # 4. Realized volatility (10-day ATR as % of price)
    atr_vals = []
    for i in range(min(10, n - 1)):
        tr = max(
            spy_highs[i] - spy_lows[i],
            abs(spy_highs[i] - spy_closes[i + 1]) if i + 1 < n else spy_highs[i] - spy_lows[i],
            abs(spy_lows[i] - spy_closes[i + 1]) if i + 1 < n else spy_highs[i] - spy_lows[i],
        )
        atr_vals.append(tr)
    atr_10 = np.mean(atr_vals) if atr_vals else 0
    feats["regime_volatility"] = atr_10 / current if current > 0 else 0

    # 5. Volatility expansion (5d ATR / 20d ATR)
    atr_5 = np.mean(atr_vals[:5]) if len(atr_vals) >= 5 else atr_10
    atr_20_vals = []
    for i in range(min(20, n - 1)):
        tr = max(
            spy_highs[i] - spy_lows[i],
            abs(spy_highs[i] - spy_closes[i + 1]) if i + 1 < n else spy_highs[i] - spy_lows[i],
            abs(spy_lows[i] - spy_closes[i + 1]) if i + 1 < n else spy_highs[i] - spy_lows[i],
        )
        atr_20_vals.append(tr)
    atr_20 = np.mean(atr_20_vals) if atr_20_vals else atr_10
    feats["regime_vol_expansion"] = (atr_5 / atr_20) if atr_20 > 0 else 1.0

    # 6. Breadth proxy: % of last 10 bars that closed up
    up_count = 0
    for i in range(min(10, n - 1)):
        if spy_closes[i] > spy_closes[i + 1]:
            up_count += 1
    feats["regime_breadth_proxy"] = (up_count / min(10, n - 1)) * 2 - 1  # [-1, 1]

    return feats


class RegimeFeatureProvider:
    """
    Provides regime features for training (historical) and prediction (live).

    For training: preloads SPY daily bars and creates a date→index lookup.
    For prediction: computes from most recent SPY bars.
    """

    def __init__(self, db=None):
        self._db = db
        # SPY daily bar data: chronological order
        self._spy_dates: List[str] = []
        self._spy_closes: np.ndarray = np.array([])
        self._spy_highs: np.ndarray = np.array([])
        self._spy_lows: np.ndarray = np.array([])
        self._date_to_idx: Dict[str, int] = {}
        self._loaded = False

    def preload_spy_daily(self) -> int:
        """
        Load SPY daily bars from ib_historical_data.
        Returns the number of bars loaded.
        Must be called before get_regime_features_for_date().
        """
        if self._db is None:
            logger.warning("No DB connection for regime feature provider")
            return 0

        try:
            # Only real daily bars (date string length == 10)
            pipeline = [
                {"$match": {"symbol": "SPY", "bar_size": "1 day"}},
                {"$addFields": {"_dateLen": {"$strLenCP": {"$toString": "$date"}}}},
                {"$match": {"_dateLen": 10}},
                {"$sort": {"date": 1}},  # Chronological
                {"$project": {"_id": 0, "date": 1, "close": 1, "high": 1, "low": 1}},
            ]
            bars = list(self._db["ib_historical_data"].aggregate(pipeline, allowDiskUse=True))

            if not bars:
                logger.warning("No SPY daily bars found for regime features")
                return 0

            self._spy_dates = [b["date"] for b in bars]
            self._spy_closes = np.array([b["close"] for b in bars], dtype=float)
            self._spy_highs = np.array([b["high"] for b in bars], dtype=float)
            self._spy_lows = np.array([b["low"] for b in bars], dtype=float)
            self._date_to_idx = {d: i for i, d in enumerate(self._spy_dates)}
            self._loaded = True

            logger.info(f"Regime feature provider: loaded {len(bars)} SPY daily bars "
                        f"({self._spy_dates[0]} to {self._spy_dates[-1]})")
            return len(bars)

        except Exception as e:
            logger.error(f"Failed to preload SPY bars for regime: {e}")
            return 0

    def get_regime_features_for_date(self, date_str: str) -> Dict[str, float]:
        """
        Get regime features for a specific date during training.

        Args:
            date_str: Date string like "2026-03-10" (or with time for intraday).
                      For intraday bars, extracts just the date portion.

        Returns:
            Dict of regime feature name → value.
        """
        if not self._loaded:
            return {name: 0.0 for name in REGIME_FEATURE_NAMES}

        # Extract date portion (handle both "2026-03-10" and "2026-03-10T09:30:00-04:00")
        clean_date = date_str[:10] if date_str else ""

        idx = self._date_to_idx.get(clean_date)
        if idx is None:
            # Try to find the closest previous date
            for i in range(len(self._spy_dates) - 1, -1, -1):
                if self._spy_dates[i] <= clean_date:
                    idx = i
                    break

        if idx is None or idx < 25:
            return {name: 0.0 for name in REGIME_FEATURE_NAMES}

        # Build arrays in most-recent-first order (from idx going back)
        lookback = min(30, idx + 1)
        spy_c = self._spy_closes[idx - lookback + 1: idx + 1][::-1]
        spy_h = self._spy_highs[idx - lookback + 1: idx + 1][::-1]
        spy_l = self._spy_lows[idx - lookback + 1: idx + 1][::-1]

        return compute_regime_features_from_bars(spy_c, spy_h, spy_l)

    async def get_current_regime_features(self) -> Dict[str, float]:
        """
        Get regime features for the current moment (for live predictions).
        Uses the most recent SPY daily bars from DB.
        """
        if self._db is None:
            return {name: 0.0 for name in REGIME_FEATURE_NAMES}

        try:
            import asyncio
            loop = asyncio.get_event_loop()

            def _query():
                bars = list(self._db["ib_historical_data"].find(
                    {"symbol": "SPY", "bar_size": "1 day"},
                    {"_id": 0, "date": 1, "close": 1, "high": 1, "low": 1}
                ).sort("date", -1).limit(30))
                return bars

            bars = await loop.run_in_executor(None, _query)

            if not bars or len(bars) < 25:
                return {name: 0.0 for name in REGIME_FEATURE_NAMES}

            # Filter to real daily bars (date length 10) — already sorted desc
            real_bars = [b for b in bars if len(str(b.get("date", ""))) == 10]
            if len(real_bars) < 25:
                return {name: 0.0 for name in REGIME_FEATURE_NAMES}

            # Already most-recent-first from the query
            spy_c = np.array([b["close"] for b in real_bars], dtype=float)
            spy_h = np.array([b["high"] for b in real_bars], dtype=float)
            spy_l = np.array([b["low"] for b in real_bars], dtype=float)

            return compute_regime_features_from_bars(spy_c, spy_h, spy_l)

        except Exception as e:
            logger.warning(f"Failed to get current regime features: {e}")
            return {name: 0.0 for name in REGIME_FEATURE_NAMES}
