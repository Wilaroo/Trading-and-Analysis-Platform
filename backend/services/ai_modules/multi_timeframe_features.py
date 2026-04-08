"""
Multi-Timeframe Context Features for AI Training & Prediction

Provides daily-level context features for intraday models. When a 5-min
model is evaluating a bar, it needs to know the stock's daily context:
Is the daily trend up? What's the daily RSI? How volatile is it on a
daily basis?

Features (8 total):
  mtf_daily_trend          -- Stock's daily close vs 20-SMA, normalized [-1, 1]
  mtf_daily_rsi            -- Stock's daily 14-period RSI, normalized [-1, 1]
  mtf_daily_momentum       -- Stock's daily 5-day return
  mtf_daily_volatility     -- Stock's daily 10-day ATR as % of price
  mtf_daily_bb_position    -- Stock's position in daily Bollinger Bands [0, 1]
  mtf_daily_volume_trend   -- Stock's 5-day volume vs 20-day average
  mtf_daily_higher_tf_align -- Alignment: daily + weekly trend agreement [-1, 1]
  mtf_daily_gap            -- Today's gap from previous close (%)

Usage:
  # During training (with preloaded daily bars):
  provider = MultiTimeframeFeatureProvider(db)
  provider.preload_daily_bars(symbols)  # bulk preload
  feats = provider.get_mtf_features("AAPL", "2026-03-10")

  # During prediction:
  feats = provider.get_mtf_features_from_bars(daily_bars)
"""

import logging
import numpy as np
from typing import Dict, Optional, List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

MTF_FEATURE_NAMES = [
    "mtf_daily_trend",
    "mtf_daily_rsi",
    "mtf_daily_momentum",
    "mtf_daily_volatility",
    "mtf_daily_bb_position",
    "mtf_daily_volume_trend",
    "mtf_daily_higher_tf_align",
    "mtf_daily_gap",
]


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


def compute_mtf_features_from_daily_bars(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    volumes: np.ndarray = None,
    opens: np.ndarray = None,
) -> Dict[str, float]:
    """
    Compute multi-timeframe context features from a stock's own daily bars.
    Arrays should be most-recent-first. Needs at least 25 bars.

    Args:
        closes, highs, lows: Daily OHLC arrays (most recent first)
        volumes: Daily volume array (optional, used for volume trend)
        opens: Daily open array (optional, used for gap calculation)
    """
    feats = {}
    n = len(closes)

    if n < 25:
        return {name: 0.0 for name in MTF_FEATURE_NAMES}

    current = closes[0]

    # 1. Daily trend: price vs 20-SMA, clipped to [-1, 1]
    sma_20 = np.mean(closes[:20])
    if sma_20 > 0:
        dist = (current - sma_20) / sma_20
        feats["mtf_daily_trend"] = max(-1.0, min(1.0, dist / 0.03))
    else:
        feats["mtf_daily_trend"] = 0.0

    # 2. Daily RSI (normalized to [-1, 1])
    rsi = _compute_rsi(closes, 14)
    feats["mtf_daily_rsi"] = (rsi - 50) / 50

    # 3. Daily 5-bar momentum
    if n > 4 and closes[4] > 0:
        feats["mtf_daily_momentum"] = (closes[0] - closes[4]) / closes[4]
    else:
        feats["mtf_daily_momentum"] = 0.0

    # 4. Daily volatility (10-day ATR as % of price)
    atr_vals = []
    for i in range(min(10, n - 1)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i + 1]) if i + 1 < n else highs[i] - lows[i],
            abs(lows[i] - closes[i + 1]) if i + 1 < n else highs[i] - lows[i],
        )
        atr_vals.append(tr)
    atr_10 = np.mean(atr_vals) if atr_vals else 0
    feats["mtf_daily_volatility"] = atr_10 / current if current > 0 else 0

    # 5. Daily Bollinger Band position [0, 1]
    if n >= 20:
        std_20 = np.std(closes[:20])
        if std_20 > 0:
            upper = sma_20 + 2 * std_20
            lower = sma_20 - 2 * std_20
            bb_range = upper - lower
            feats["mtf_daily_bb_position"] = (current - lower) / bb_range if bb_range > 0 else 0.5
        else:
            feats["mtf_daily_bb_position"] = 0.5
    else:
        feats["mtf_daily_bb_position"] = 0.5

    # 6. Volume trend: 5-day avg vs 20-day avg
    if volumes is not None and len(volumes) >= 20:
        avg_vol_5 = np.mean(volumes[:5])
        avg_vol_20 = np.mean(volumes[:20])
        feats["mtf_daily_volume_trend"] = (avg_vol_5 / avg_vol_20) - 1.0 if avg_vol_20 > 0 else 0.0
    else:
        feats["mtf_daily_volume_trend"] = 0.0

    # 7. Higher timeframe alignment: daily + weekly trend agreement
    # Daily trend direction
    daily_above_sma = 1.0 if current > sma_20 else -1.0

    # Approximate weekly: use 50-day SMA as proxy for weekly trend
    if n >= 50:
        sma_50 = np.mean(closes[:50])
        weekly_above_sma = 1.0 if current > sma_50 else -1.0
    else:
        weekly_above_sma = 0.0

    # Alignment: +1 = both up, -1 = both down, 0 = disagreement
    feats["mtf_daily_higher_tf_align"] = daily_above_sma * weekly_above_sma

    # 8. Gap from previous close
    if opens is not None and len(opens) >= 1 and n >= 2:
        prev_close = closes[1]
        today_open = opens[0]
        if prev_close > 0:
            feats["mtf_daily_gap"] = (today_open - prev_close) / prev_close
        else:
            feats["mtf_daily_gap"] = 0.0
    else:
        feats["mtf_daily_gap"] = 0.0

    # Sanitize NaN/Inf
    for key in feats:
        val = feats[key]
        if np.isnan(val) or np.isinf(val):
            feats[key] = 0.0

    return feats


class MultiTimeframeFeatureProvider:
    """
    Provides multi-timeframe context features by loading a stock's daily bars
    alongside its intraday bars during training.

    For training: preloads daily bars for all relevant symbols.
    For prediction: computes from freshly queried daily bars.
    """

    def __init__(self, db=None):
        self._db = db
        # symbol -> {dates, closes, highs, lows, volumes, opens, date_to_idx}
        self._symbol_data = {}
        self._loaded_symbols = set()

    def preload_daily_bars(self, symbols: List[str]) -> int:
        """
        Bulk preload daily bars for a list of symbols.
        Returns total bars loaded.
        """
        if self._db is None:
            return 0

        total = 0
        for symbol in symbols:
            if symbol in self._loaded_symbols:
                continue
            count = self._load_symbol_daily(symbol)
            total += count

        logger.info(f"MTF provider: preloaded daily bars for {len(self._loaded_symbols)} symbols ({total:,} bars)")
        return total

    def _load_symbol_daily(self, symbol: str) -> int:
        """Load daily bars for a single symbol."""
        try:
            cursor = self._db["ib_historical_data"].find(
                {"symbol": symbol, "bar_size": "1 day"},
                {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
            ).sort("date", -1).limit(10000).max_time_ms(30000)

            bars = list(cursor)
            bars.reverse()  # Back to chronological order
            if not bars:
                return 0

            # Deduplicate by date (first 10 chars), keep last per date
            seen = {}
            for b in bars:
                dk = str(b.get("date", ""))[:10]
                if len(dk) == 10:
                    seen[dk] = b
            bars = sorted(seen.values(), key=lambda x: str(x["date"])[:10])
            if len(bars) < 25:
                return 0

            self._symbol_data[symbol] = {
                "dates": [str(b["date"])[:10] for b in bars],
                "closes": np.array([b["close"] for b in bars], dtype=float),
                "highs": np.array([b["high"] for b in bars], dtype=float),
                "lows": np.array([b["low"] for b in bars], dtype=float),
                "volumes": np.array([b.get("volume", 0) for b in bars], dtype=float),
                "opens": np.array([b.get("open", 0) for b in bars], dtype=float),
                "date_to_idx": {str(b["date"])[:10]: i for i, b in enumerate(bars)},
            }
            self._loaded_symbols.add(symbol)
            return len(bars)

        except Exception as e:
            logger.warning(f"MTF provider: failed to load daily bars for {symbol}: {e}")
            return 0

    def get_mtf_features(self, symbol: str, date_str: str) -> Dict[str, float]:
        """
        Get multi-timeframe features for a symbol at a specific date.

        Args:
            symbol: Stock ticker
            date_str: Date string (e.g., "2026-03-10" or with time portion)

        Returns:
            Dict of MTF feature name -> value
        """
        data = self._symbol_data.get(symbol)
        if data is None:
            return {name: 0.0 for name in MTF_FEATURE_NAMES}

        clean_date = date_str[:10] if date_str else ""
        idx = data["date_to_idx"].get(clean_date)

        if idx is None:
            # Find closest previous date
            for i in range(len(data["dates"]) - 1, -1, -1):
                if data["dates"][i] <= clean_date:
                    idx = i
                    break

        if idx is None or idx < 25:
            return {name: 0.0 for name in MTF_FEATURE_NAMES}

        # Build arrays in most-recent-first order
        lookback = min(55, idx + 1)  # Need up to 50 for SMA
        start = idx - lookback + 1
        end = idx + 1

        closes = data["closes"][start:end][::-1]
        highs = data["highs"][start:end][::-1]
        lows = data["lows"][start:end][::-1]
        volumes = data["volumes"][start:end][::-1]
        opens = data["opens"][start:end][::-1]

        return compute_mtf_features_from_daily_bars(closes, highs, lows, volumes, opens)

    async def get_mtf_features_live(self, symbol: str) -> Dict[str, float]:
        """
        Get MTF features for a symbol using most recent daily bars from DB.
        For live prediction.
        """
        if self._db is None:
            return {name: 0.0 for name in MTF_FEATURE_NAMES}

        try:
            import asyncio
            loop = asyncio.get_event_loop()

            def _query():
                bars = list(self._db["ib_historical_data"].find(
                    {"symbol": symbol, "bar_size": "1 day"},
                    {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
                ).sort("date", -1).limit(3000))
                seen = {}
                for b in bars:
                    dk = str(b.get("date", ""))[:10]
                    if len(dk) == 10 and dk not in seen:
                        seen[dk] = b
                real = sorted(seen.values(), key=lambda x: str(x["date"])[:10], reverse=True)
                if len(real) < 25:
                    return {name: 0.0 for name in MTF_FEATURE_NAMES}
                closes = np.array([b["close"] for b in real], dtype=float)
                highs = np.array([b["high"] for b in real], dtype=float)
                lows = np.array([b["low"] for b in real], dtype=float)
                volumes = np.array([b.get("volume", 0) for b in real], dtype=float)
                opens = np.array([b.get("open", 0) for b in real], dtype=float)
                return compute_mtf_features_from_daily_bars(closes, highs, lows, volumes, opens)

            return await loop.run_in_executor(None, _query)

        except Exception as e:
            logger.warning(f"MTF live features failed for {symbol}: {e}")
            return {name: 0.0 for name in MTF_FEATURE_NAMES}
