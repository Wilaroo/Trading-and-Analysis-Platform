"""
Time-Series Feature Engineering for Trading

Extracts predictive features from OHLCV data for ML models.
Features are designed for directional forecasting (up/down/flat).

Feature Categories:
1. Price Action Features - returns, gaps, ranges
2. Volume Features - RVOL, volume trends
3. Technical Indicators - RSI, MACD, Bollinger Bands
4. Pattern Features - candle patterns, support/resistance
5. Time Features - time of day, day of week
"""

import logging
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class FeatureSet:
    """Complete feature set for a single prediction"""
    symbol: str = ""
    timestamp: str = ""
    
    # Feature vector
    features: Dict[str, float] = field(default_factory=dict)
    
    # Target (for training)
    target: Optional[float] = None  # 1=up, 0=down, 0.5=flat
    target_return: Optional[float] = None  # Actual return
    
    # Metadata
    feature_count: int = 0
    bars_used: int = 0
    
    def to_vector(self, feature_names: List[str] = None) -> List[float]:
        """Convert to feature vector for model"""
        if feature_names:
            return [self.features.get(f, 0.0) for f in feature_names]
        return list(self.features.values())
    
    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "features": self.features,
            "target": self.target,
            "target_return": self.target_return,
            "feature_count": self.feature_count,
            "bars_used": self.bars_used
        }


class TimeSeriesFeatureEngineer:
    """
    Extracts features from OHLCV bars for ML models.
    
    Designed for LightGBM directional forecasting.
    """
    
    # Feature names for model training (must be consistent)
    FEATURE_NAMES = [
        # Price action (12 features)
        "return_1", "return_3", "return_5", "return_10",
        "gap_open", "range_pct", "body_pct", "upper_wick_pct", "lower_wick_pct",
        "high_from_open", "low_from_open", "close_position",
        
        # Volume (6 features)
        "rvol_1", "rvol_5", "rvol_10",
        "volume_trend_3", "volume_trend_5", "volume_price_corr",
        
        # Momentum (8 features)
        "rsi_14", "rsi_change", "macd_hist", "macd_signal_cross",
        "stoch_k", "stoch_d", "williams_r", "cci",
        
        # Volatility (6 features)
        "atr_pct", "bb_position", "bb_width", "keltner_position",
        "volatility_10", "volatility_ratio",
        
        # Trend (6 features)
        "ema_9_distance", "ema_21_distance", "sma_50_distance",
        "trend_strength", "higher_highs", "lower_lows",
        
        # Pattern (4 features)
        "doji", "hammer", "engulfing", "inside_bar",
        
        # Time (4 features)
        "hour_sin", "hour_cos", "day_of_week", "is_power_hour"
    ]
    
    def __init__(self, lookback: int = 50):
        self.lookback = lookback
        
    def extract_features(
        self,
        bars: List[Dict],
        symbol: str = "",
        include_target: bool = False,
        forecast_horizon: int = 5
    ) -> Optional[FeatureSet]:
        """
        Extract features from OHLCV bars.
        
        Args:
            bars: List of OHLCV bars (most recent first)
            symbol: Ticker symbol
            include_target: Calculate target from future bars (for training)
            forecast_horizon: Bars ahead for target calculation
            
        Returns:
            FeatureSet with all extracted features
        """
        if not bars or len(bars) < 20:
            logger.warning(f"Insufficient bars for feature extraction: {len(bars) if bars else 0}")
            return None
            
        try:
            # Convert bars to numpy arrays
            opens = np.array([b.get("open", 0) for b in bars], dtype=float)
            highs = np.array([b.get("high", 0) for b in bars], dtype=float)
            lows = np.array([b.get("low", 0) for b in bars], dtype=float)
            closes = np.array([b.get("close", 0) for b in bars], dtype=float)
            volumes = np.array([b.get("volume", 0) for b in bars], dtype=float)
            
            # Replace zeros to avoid division errors
            closes = np.where(closes == 0, 1, closes)
            opens = np.where(opens == 0, closes, opens)
            volumes = np.where(volumes == 0, 1, volumes)
            
            features = {}
            
            # ==================== PRICE ACTION FEATURES ====================
            features.update(self._price_action_features(opens, highs, lows, closes))
            
            # ==================== VOLUME FEATURES ====================
            features.update(self._volume_features(volumes, closes))
            
            # ==================== MOMENTUM FEATURES ====================
            features.update(self._momentum_features(closes, highs, lows))
            
            # ==================== VOLATILITY FEATURES ====================
            features.update(self._volatility_features(highs, lows, closes))
            
            # ==================== TREND FEATURES ====================
            features.update(self._trend_features(closes, highs, lows))
            
            # ==================== PATTERN FEATURES ====================
            features.update(self._pattern_features(opens, highs, lows, closes))
            
            # ==================== TIME FEATURES ====================
            features.update(self._time_features(bars))
            
            # Create feature set
            feature_set = FeatureSet(
                symbol=symbol,
                timestamp=datetime.now(timezone.utc).isoformat(),
                features=features,
                feature_count=len(features),
                bars_used=len(bars)
            )
            
            # Calculate target if requested (for training)
            if include_target and len(bars) > forecast_horizon:
                # Target: direction over forecast_horizon bars
                current_price = closes[0]
                future_price = closes[forecast_horizon] if len(closes) > forecast_horizon else closes[-1]
                
                # Calculate return
                target_return = (current_price - future_price) / future_price  # Note: bars are recent-first
                
                # Classify: up (>0.5%), down (<-0.5%), flat
                if target_return > 0.005:
                    target = 1.0  # Up
                elif target_return < -0.005:
                    target = 0.0  # Down
                else:
                    target = 0.5  # Flat
                    
                feature_set.target = target
                feature_set.target_return = target_return
                
            return feature_set
            
        except Exception as e:
            logger.error(f"Feature extraction error: {e}")
            return None
            
    def _price_action_features(
        self,
        opens: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray
    ) -> Dict[str, float]:
        """Extract price action features"""
        features = {}
        
        # Returns at different lookbacks
        features["return_1"] = (closes[0] - closes[1]) / closes[1] if len(closes) > 1 else 0
        features["return_3"] = (closes[0] - closes[3]) / closes[3] if len(closes) > 3 else 0
        features["return_5"] = (closes[0] - closes[5]) / closes[5] if len(closes) > 5 else 0
        features["return_10"] = (closes[0] - closes[10]) / closes[10] if len(closes) > 10 else 0
        
        # Gap from previous close
        features["gap_open"] = (opens[0] - closes[1]) / closes[1] if len(closes) > 1 else 0
        
        # Current bar metrics
        range_size = highs[0] - lows[0]
        body_size = abs(closes[0] - opens[0])
        
        features["range_pct"] = range_size / closes[0] if closes[0] > 0 else 0
        features["body_pct"] = body_size / range_size if range_size > 0 else 0
        
        # Wick analysis
        if closes[0] >= opens[0]:  # Bullish bar
            upper_wick = highs[0] - closes[0]
            lower_wick = opens[0] - lows[0]
        else:  # Bearish bar
            upper_wick = highs[0] - opens[0]
            lower_wick = closes[0] - lows[0]
            
        features["upper_wick_pct"] = upper_wick / range_size if range_size > 0 else 0
        features["lower_wick_pct"] = lower_wick / range_size if range_size > 0 else 0
        
        # Position within bar
        features["high_from_open"] = (highs[0] - opens[0]) / opens[0] if opens[0] > 0 else 0
        features["low_from_open"] = (opens[0] - lows[0]) / opens[0] if opens[0] > 0 else 0
        features["close_position"] = (closes[0] - lows[0]) / range_size if range_size > 0 else 0.5
        
        return features
        
    def _volume_features(
        self,
        volumes: np.ndarray,
        closes: np.ndarray
    ) -> Dict[str, float]:
        """Extract volume features"""
        features = {}
        
        # Relative volume at different lookbacks
        avg_1 = np.mean(volumes[1:6]) if len(volumes) > 5 else volumes[0]
        avg_5 = np.mean(volumes[1:11]) if len(volumes) > 10 else avg_1
        avg_10 = np.mean(volumes[1:21]) if len(volumes) > 20 else avg_5
        
        features["rvol_1"] = volumes[0] / avg_1 if avg_1 > 0 else 1
        features["rvol_5"] = volumes[0] / avg_5 if avg_5 > 0 else 1
        features["rvol_10"] = volumes[0] / avg_10 if avg_10 > 0 else 1
        
        # Volume trend (slope)
        if len(volumes) >= 3:
            features["volume_trend_3"] = (volumes[0] - volumes[2]) / volumes[2] if volumes[2] > 0 else 0
        else:
            features["volume_trend_3"] = 0
            
        if len(volumes) >= 5:
            features["volume_trend_5"] = (volumes[0] - volumes[4]) / volumes[4] if volumes[4] > 0 else 0
        else:
            features["volume_trend_5"] = 0
            
        # Volume-price correlation
        if len(volumes) >= 10 and len(closes) >= 10:
            vol_returns = np.diff(volumes[:10])
            price_returns = np.diff(closes[:10])
            if len(vol_returns) > 0 and np.std(vol_returns) > 0 and np.std(price_returns) > 0:
                features["volume_price_corr"] = np.corrcoef(vol_returns, price_returns)[0, 1]
            else:
                features["volume_price_corr"] = 0
        else:
            features["volume_price_corr"] = 0
            
        # Handle NaN
        for key in features:
            if np.isnan(features[key]) or np.isinf(features[key]):
                features[key] = 0
                
        return features
        
    def _momentum_features(
        self,
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray
    ) -> Dict[str, float]:
        """Extract momentum features"""
        features = {}
        
        # RSI (14-period)
        if len(closes) >= 15:
            deltas = np.diff(closes[:15])
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)
            avg_gain = np.mean(gains) if len(gains) > 0 else 0
            avg_loss = np.mean(losses) if len(losses) > 0 else 0
            
            if avg_loss > 0:
                rs = avg_gain / avg_loss
                features["rsi_14"] = 100 - (100 / (1 + rs))
            else:
                features["rsi_14"] = 100 if avg_gain > 0 else 50
        else:
            features["rsi_14"] = 50
            
        # RSI change
        features["rsi_change"] = 0  # Would need historical RSI
        
        # MACD (simplified)
        if len(closes) >= 26:
            ema_12 = self._ema(closes[:26], 12)
            ema_26 = self._ema(closes[:26], 26)
            macd_line = ema_12 - ema_26
            signal_line = self._ema(np.array([macd_line] * 9), 9)  # Simplified
            
            features["macd_hist"] = (macd_line - signal_line) / closes[0] if closes[0] > 0 else 0
            features["macd_signal_cross"] = 1 if macd_line > signal_line else -1
        else:
            features["macd_hist"] = 0
            features["macd_signal_cross"] = 0
            
        # Stochastic
        if len(closes) >= 14:
            lowest_low = np.min(lows[:14])
            highest_high = np.max(highs[:14])
            range_hl = highest_high - lowest_low
            
            if range_hl > 0:
                features["stoch_k"] = ((closes[0] - lowest_low) / range_hl) * 100
            else:
                features["stoch_k"] = 50
            features["stoch_d"] = features["stoch_k"]  # Simplified (should be SMA of K)
        else:
            features["stoch_k"] = 50
            features["stoch_d"] = 50
            
        # Williams %R
        if len(closes) >= 14:
            highest_high = np.max(highs[:14])
            lowest_low = np.min(lows[:14])
            range_hl = highest_high - lowest_low
            
            if range_hl > 0:
                features["williams_r"] = ((highest_high - closes[0]) / range_hl) * -100
            else:
                features["williams_r"] = -50
        else:
            features["williams_r"] = -50
            
        # CCI
        if len(closes) >= 20:
            typical_price = (highs[:20] + lows[:20] + closes[:20]) / 3
            sma_tp = np.mean(typical_price)
            mean_deviation = np.mean(np.abs(typical_price - sma_tp))
            
            if mean_deviation > 0:
                features["cci"] = (typical_price[0] - sma_tp) / (0.015 * mean_deviation)
            else:
                features["cci"] = 0
        else:
            features["cci"] = 0
            
        # Handle NaN/Inf
        for key in features:
            if np.isnan(features[key]) or np.isinf(features[key]):
                features[key] = 0
                
        return features
        
    def _volatility_features(
        self,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray
    ) -> Dict[str, float]:
        """Extract volatility features"""
        features = {}
        
        # ATR (14-period)
        if len(closes) >= 15:
            # True Range = max(H-L, |H-Prev_C|, |L-Prev_C|)
            prev_closes = closes[1:15]  # Previous closes (14 values)
            curr_highs = highs[:14]      # Current highs (14 values)
            curr_lows = lows[:14]        # Current lows (14 values)
            
            tr = np.maximum(
                curr_highs - curr_lows,
                np.maximum(
                    np.abs(curr_highs - prev_closes),
                    np.abs(curr_lows - prev_closes)
                )
            )
            atr = np.mean(tr)
            features["atr_pct"] = atr / closes[0] if closes[0] > 0 else 0
        else:
            features["atr_pct"] = 0.02  # Default 2%
            
        # Bollinger Bands position
        if len(closes) >= 20:
            sma_20 = np.mean(closes[:20])
            std_20 = np.std(closes[:20])
            
            if std_20 > 0:
                upper_band = sma_20 + 2 * std_20
                lower_band = sma_20 - 2 * std_20
                bb_width = (upper_band - lower_band) / sma_20
                bb_position = (closes[0] - lower_band) / (upper_band - lower_band) if upper_band > lower_band else 0.5
            else:
                bb_width = 0
                bb_position = 0.5
                
            features["bb_position"] = bb_position
            features["bb_width"] = bb_width
        else:
            features["bb_position"] = 0.5
            features["bb_width"] = 0.04
            
        # Keltner Channel position (simplified)
        features["keltner_position"] = features["bb_position"]  # Similar concept
        
        # Historical volatility
        if len(closes) >= 11:
            returns = np.diff(np.log(closes[:11]))
            features["volatility_10"] = np.std(returns) * np.sqrt(252) if len(returns) > 0 else 0
        else:
            features["volatility_10"] = 0.2
            
        # Volatility ratio (current vs average)
        if len(closes) >= 21:
            recent_vol = np.std(np.diff(np.log(closes[:6]))) if len(closes) >= 6 else 0
            avg_vol = np.std(np.diff(np.log(closes[:21]))) if len(closes) >= 21 else recent_vol
            features["volatility_ratio"] = recent_vol / avg_vol if avg_vol > 0 else 1
        else:
            features["volatility_ratio"] = 1
            
        # Handle NaN/Inf
        for key in features:
            if np.isnan(features[key]) or np.isinf(features[key]):
                features[key] = 0
                
        return features
        
    def _trend_features(
        self,
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray
    ) -> Dict[str, float]:
        """Extract trend features"""
        features = {}
        
        # EMA distances
        if len(closes) >= 9:
            ema_9 = self._ema(closes[:9], 9)
            features["ema_9_distance"] = (closes[0] - ema_9) / ema_9 if ema_9 > 0 else 0
        else:
            features["ema_9_distance"] = 0
            
        if len(closes) >= 21:
            ema_21 = self._ema(closes[:21], 21)
            features["ema_21_distance"] = (closes[0] - ema_21) / ema_21 if ema_21 > 0 else 0
        else:
            features["ema_21_distance"] = 0
            
        if len(closes) >= 50:
            sma_50 = np.mean(closes[:50])
            features["sma_50_distance"] = (closes[0] - sma_50) / sma_50 if sma_50 > 0 else 0
        else:
            features["sma_50_distance"] = 0
            
        # Trend strength (ADX-like, simplified)
        if len(closes) >= 14:
            up_moves = np.diff(highs[:14])
            down_moves = -np.diff(lows[:14])
            
            plus_dm = np.where((up_moves > down_moves) & (up_moves > 0), up_moves, 0)
            minus_dm = np.where((down_moves > up_moves) & (down_moves > 0), down_moves, 0)
            
            sum_dm = np.sum(plus_dm) + np.sum(minus_dm)
            if sum_dm > 0:
                features["trend_strength"] = abs(np.sum(plus_dm) - np.sum(minus_dm)) / sum_dm
            else:
                features["trend_strength"] = 0
        else:
            features["trend_strength"] = 0
            
        # Higher highs / Lower lows count
        if len(highs) >= 5:
            hh_count = sum(1 for i in range(4) if highs[i] > highs[i+1])
            ll_count = sum(1 for i in range(4) if lows[i] < lows[i+1])
            features["higher_highs"] = hh_count / 4
            features["lower_lows"] = ll_count / 4
        else:
            features["higher_highs"] = 0.5
            features["lower_lows"] = 0.5
            
        # Handle NaN/Inf
        for key in features:
            if np.isnan(features[key]) or np.isinf(features[key]):
                features[key] = 0
                
        return features
        
    def _pattern_features(
        self,
        opens: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray
    ) -> Dict[str, float]:
        """Extract candle pattern features"""
        features = {}
        
        # Current bar analysis
        body = abs(closes[0] - opens[0])
        range_size = highs[0] - lows[0]
        
        # Doji (small body relative to range)
        features["doji"] = 1 if range_size > 0 and body / range_size < 0.1 else 0
        
        # Hammer (long lower wick, small upper wick)
        if range_size > 0:
            lower_wick = min(opens[0], closes[0]) - lows[0]
            upper_wick = highs[0] - max(opens[0], closes[0])
            features["hammer"] = 1 if lower_wick > 2 * body and upper_wick < body else 0
        else:
            features["hammer"] = 0
            
        # Engulfing (requires previous bar)
        if len(closes) >= 2:
            prev_body = abs(closes[1] - opens[1])
            curr_body = body
            
            bullish_engulf = (closes[0] > opens[0] and  # Current is bullish
                            closes[1] < opens[1] and  # Previous is bearish
                            curr_body > prev_body)     # Current body larger
            bearish_engulf = (closes[0] < opens[0] and  # Current is bearish
                            closes[1] > opens[1] and  # Previous is bullish
                            curr_body > prev_body)     # Current body larger
            
            features["engulfing"] = 1 if bullish_engulf else (-1 if bearish_engulf else 0)
        else:
            features["engulfing"] = 0
            
        # Inside bar
        if len(highs) >= 2:
            features["inside_bar"] = 1 if highs[0] < highs[1] and lows[0] > lows[1] else 0
        else:
            features["inside_bar"] = 0
            
        return features
        
    def _time_features(self, bars: List[Dict]) -> Dict[str, float]:
        """Extract time-based features"""
        features = {}
        
        # Try to get timestamp from first bar
        timestamp = bars[0].get("timestamp", "") if bars else ""
        
        try:
            if timestamp:
                if isinstance(timestamp, str):
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                else:
                    dt = timestamp
                    
                hour = dt.hour
                
                # Cyclical encoding for hour
                features["hour_sin"] = np.sin(2 * np.pi * hour / 24)
                features["hour_cos"] = np.cos(2 * np.pi * hour / 24)
                
                # Day of week (0=Monday, 4=Friday)
                features["day_of_week"] = dt.weekday() / 4  # Normalize to 0-1
                
                # Power hour (last hour of trading, 3-4 PM ET, roughly 19-20 UTC)
                features["is_power_hour"] = 1 if 19 <= hour <= 20 else 0
            else:
                # Defaults
                features["hour_sin"] = 0
                features["hour_cos"] = 1
                features["day_of_week"] = 0.5
                features["is_power_hour"] = 0
        except Exception:
            features["hour_sin"] = 0
            features["hour_cos"] = 1
            features["day_of_week"] = 0.5
            features["is_power_hour"] = 0
            
        return features
        
    def _ema(self, data: np.ndarray, period: int) -> float:
        """Calculate EMA"""
        if len(data) < period:
            return np.mean(data) if len(data) > 0 else 0
            
        multiplier = 2 / (period + 1)
        ema = data[-1]  # Start from oldest
        
        for price in reversed(data[:-1]):
            ema = (price * multiplier) + (ema * (1 - multiplier))
            
        return ema
        
    def get_feature_names(self) -> List[str]:
        """Get ordered list of feature names"""
        return self.FEATURE_NAMES.copy()

    # =====================================================================
    # VECTORIZED BULK EXTRACTION — computes all features for entire symbol
    # in one pass. Used by training only. Live prediction still uses
    # extract_features() above.
    # =====================================================================

    @staticmethod
    def _ema_series(arr, period):
        """Compute EMA for entire array. O(n) single pass."""
        alpha = 2.0 / (period + 1)
        result = np.empty_like(arr, dtype=np.float64)
        result[0] = arr[0]
        for i in range(1, len(arr)):
            result[i] = alpha * arr[i] + (1 - alpha) * result[i - 1]
        return result

    @staticmethod
    def _rsi_series(closes, period=14):
        """Compute RSI for entire array. Returns array of same length."""
        n = len(closes)
        rsi = np.full(n, 50.0, dtype=np.float64)
        if n < period + 1:
            return rsi
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])
        if avg_loss > 0:
            rsi[period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
        elif avg_gain > 0:
            rsi[period] = 100.0
        for i in range(period + 1, n):
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
            if avg_loss > 0:
                rsi[i] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
            elif avg_gain > 0:
                rsi[i] = 100.0
        return rsi

    def extract_features_bulk(self, bars: List[Dict]) -> Optional[np.ndarray]:
        """
        Vectorized feature extraction for an entire symbol's bar history.

        Computes all 46 features for every valid window in one pass instead
        of calling extract_features() per window.

        Args:
            bars: OHLCV bars in chronological order (oldest first)

        Returns:
            numpy array of shape (n_valid_windows, 46) or None
        """
        from numpy.lib.stride_tricks import sliding_window_view

        n = len(bars)
        lb = self.lookback  # 50
        if n < lb + 1:
            return None

        # Suppress divide-by-zero warnings — guarded by np.where/np.divide already
        with np.errstate(divide='ignore', invalid='ignore'):
            return self._extract_features_bulk_inner(bars, n, lb, sliding_window_view)

    def _extract_features_bulk_inner(self, bars, n, lb, sliding_window_view):
        """Inner implementation (separated so np.errstate context covers all math)."""

        # Convert all bars to arrays ONCE
        opens = np.array([b.get("open", 0) for b in bars], dtype=np.float64)
        highs = np.array([b.get("high", 0) for b in bars], dtype=np.float64)
        lows = np.array([b.get("low", 0) for b in bars], dtype=np.float64)
        closes = np.array([b.get("close", 0) for b in bars], dtype=np.float64)
        volumes = np.array([b.get("volume", 0) for b in bars], dtype=np.float64)

        closes = np.where(closes == 0, 1.0, closes)
        opens = np.where(opens == 0, closes, opens)
        volumes = np.where(volumes == 0, 1.0, volumes)

        # Valid positions: t = lb-1 .. n-1  (n_win total)
        n_win = n - lb + 1
        idx = np.arange(lb - 1, n)  # absolute indices of "current bar"
        n_feat = len(self.FEATURE_NAMES)
        F = np.zeros((n_win, n_feat), dtype=np.float32)

        def sd(a, b):
            """Safe divide."""
            return np.divide(a, b, out=np.zeros_like(a, dtype=np.float64),
                             where=np.abs(b) > 1e-10)

        c_t = closes[idx];  c1 = closes[idx - 1]
        c3 = closes[idx - 3]; c5 = closes[idx - 5]; c10 = closes[idx - 10]
        o_t = opens[idx]; h_t = highs[idx]; l_t = lows[idx]; v_t = volumes[idx]

        fi = 0  # feature column index

        # ── PRICE ACTION (12) ──────────────────────────────────────────
        F[:, fi] = sd(c_t - c1, c1);  fi += 1            # return_1
        F[:, fi] = sd(c_t - c3, c3);  fi += 1            # return_3
        F[:, fi] = sd(c_t - c5, c5);  fi += 1            # return_5
        F[:, fi] = sd(c_t - c10, c10); fi += 1           # return_10
        F[:, fi] = sd(o_t - c1, c1);  fi += 1            # gap_open

        rng = h_t - l_t
        body = np.abs(c_t - o_t)
        F[:, fi] = sd(rng, c_t);      fi += 1            # range_pct
        F[:, fi] = sd(body, rng);      fi += 1            # body_pct

        bull = c_t >= o_t
        uw = np.where(bull, h_t - c_t, h_t - o_t)
        lw = np.where(bull, o_t - l_t, c_t - l_t)
        F[:, fi] = sd(uw, rng);        fi += 1            # upper_wick_pct
        F[:, fi] = sd(lw, rng);        fi += 1            # lower_wick_pct
        F[:, fi] = sd(h_t - o_t, o_t); fi += 1           # high_from_open
        F[:, fi] = sd(o_t - l_t, o_t); fi += 1           # low_from_open
        cp = sd(c_t - l_t, rng)
        cp[rng < 1e-10] = 0.5
        F[:, fi] = cp;                 fi += 1            # close_position

        # ── VOLUME (6) ─────────────────────────────────────────────────
        vcum = np.cumsum(np.insert(volumes, 0, 0.0))
        avg5  = (vcum[idx] - vcum[idx - 5])  / 5.0
        avg10 = (vcum[idx] - vcum[idx - 10]) / 10.0
        avg20 = (vcum[idx] - vcum[idx - 20]) / 20.0
        F[:, fi] = sd(v_t, avg5);  fi += 1               # rvol_1
        F[:, fi] = sd(v_t, avg10); fi += 1               # rvol_5
        F[:, fi] = sd(v_t, avg20); fi += 1               # rvol_10

        F[:, fi] = sd(v_t - volumes[idx - 2], volumes[idx - 2]); fi += 1  # volume_trend_3
        F[:, fi] = sd(v_t - volumes[idx - 4], volumes[idx - 4]); fi += 1  # volume_trend_5

        # volume_price_corr (vectorized via sliding_window_view)
        vd = np.diff(volumes)
        pd_ = np.diff(closes)
        if len(vd) >= 9:
            vw = sliding_window_view(vd, 9)   # (n-10, 9)
            pw = sliding_window_view(pd_, 9)
            vm = vw - np.mean(vw, axis=1, keepdims=True)
            pm = pw - np.mean(pw, axis=1, keepdims=True)
            cov = np.mean(vm * pm, axis=1)
            vs = np.std(vw, axis=1)
            ps = np.std(pw, axis=1)
            denom = vs * ps
            corr_full = np.divide(cov, denom, out=np.zeros(len(cov), dtype=np.float64),
                                  where=denom > 1e-10)
            # corr_full[i] corresponds to position i+9 in closes (end of 10-bar window)
            # Map to our idx: idx[j] = lb-1+j → corr index = idx[j] - 9
            corr_idx = idx - 9
            valid = (corr_idx >= 0) & (corr_idx < len(corr_full))
            vpc = np.zeros(n_win, dtype=np.float64)
            vpc[valid] = corr_full[corr_idx[valid]]
            F[:, fi] = vpc
        fi += 1  # volume_price_corr

        # ── MOMENTUM (8) ───────────────────────────────────────────────
        # RSI-14 (full series)
        rsi_full = self._rsi_series(closes, 14)
        F[:, fi] = rsi_full[idx]; fi += 1                 # rsi_14
        F[:, fi] = 0.0;           fi += 1                 # rsi_change (placeholder)

        # MACD (full series EMAs)
        ema12 = self._ema_series(closes, 12)
        ema26 = self._ema_series(closes, 26)
        macd_line = ema12 - ema26
        ema9_macd = self._ema_series(macd_line, 9)
        F[:, fi] = sd(macd_line[idx] - ema9_macd[idx], c_t); fi += 1  # macd_hist
        F[:, fi] = np.where(macd_line[idx] > ema9_macd[idx], 1.0, -1.0); fi += 1  # macd_signal_cross

        # Stochastic K/D — rolling 14-bar high/low
        if n >= 14:
            hw = sliding_window_view(highs, 14)
            lw = sliding_window_view(lows, 14)
            roll_hh = np.max(hw, axis=1)   # length n-13
            roll_ll = np.min(lw, axis=1)
            roll_range = roll_hh - roll_ll
            # stoch at position i+13 in original array
            stoch_full = np.full(n, 50.0, dtype=np.float64)
            valid_stoch = roll_range > 1e-10
            stoch_vals = np.where(valid_stoch,
                                  ((closes[13:] - roll_ll) / roll_range) * 100.0, 50.0)
            stoch_full[13:] = stoch_vals
            F[:, fi] = stoch_full[idx]; fi += 1            # stoch_k
            F[:, fi] = stoch_full[idx]; fi += 1            # stoch_d (simplified = k)

            # Williams %R
            wr_full = np.full(n, -50.0, dtype=np.float64)
            wr_vals = np.where(valid_stoch,
                               ((roll_hh - closes[13:]) / roll_range) * -100.0, -50.0)
            wr_full[13:] = wr_vals
            F[:, fi] = wr_full[idx]; fi += 1               # williams_r
        else:
            F[:, fi] = 50.0; fi += 1
            F[:, fi] = 50.0; fi += 1
            F[:, fi] = -50.0; fi += 1

        # CCI — rolling 20-bar
        if n >= 20:
            tp = (highs + lows + closes) / 3.0
            tp_w = sliding_window_view(tp, 20)  # (n-19, 20)
            tp_sma = np.mean(tp_w, axis=1)
            tp_mad = np.mean(np.abs(tp_w - tp_sma[:, None]), axis=1)
            cci_full = np.zeros(n, dtype=np.float64)
            valid_cci = tp_mad > 1e-10
            cci_full[19:] = np.where(valid_cci,
                                     (tp[19:] - tp_sma) / (0.015 * tp_mad), 0.0)
            F[:, fi] = cci_full[idx]; fi += 1              # cci
        else:
            F[:, fi] = 0.0; fi += 1

        # ── VOLATILITY (6) ─────────────────────────────────────────────
        # ATR-14
        if n >= 15:
            tr = np.maximum(highs[1:] - lows[1:],
                            np.maximum(np.abs(highs[1:] - closes[:-1]),
                                       np.abs(lows[1:] - closes[:-1])))
            tr_w = sliding_window_view(tr, 14)
            atr_vals = np.mean(tr_w, axis=1)  # length n-15+1
            atr_full = np.zeros(n, dtype=np.float64)
            atr_full[14:14 + len(atr_vals)] = atr_vals
            F[:, fi] = sd(atr_full[idx], c_t); fi += 1    # atr_pct
        else:
            F[:, fi] = 0.02; fi += 1

        # Bollinger Bands — 20-bar
        if n >= 20:
            cw = sliding_window_view(closes, 20)
            sma20 = np.mean(cw, axis=1)
            std20 = np.std(cw, axis=1)
            bb_upper = sma20 + 2.0 * std20
            bb_lower = sma20 - 2.0 * std20
            bb_w = bb_upper - bb_lower

            bb_pos_full = np.full(n, 0.5, dtype=np.float64)
            bb_width_full = np.full(n, 0.04, dtype=np.float64)
            valid_bb = bb_w > 1e-10
            bb_pos_full[19:] = np.where(valid_bb, (closes[19:] - bb_lower) / bb_w, 0.5)
            bb_width_full[19:] = np.where(sma20 > 1e-10, bb_w / sma20, 0.04)

            F[:, fi] = bb_pos_full[idx];   fi += 1        # bb_position
            F[:, fi] = bb_width_full[idx]; fi += 1        # bb_width
        else:
            F[:, fi] = 0.5;  fi += 1
            F[:, fi] = 0.04; fi += 1

        F[:, fi] = F[:, fi - 2];  fi += 1                 # keltner_position ≈ bb_position

        # Historical volatility (10-bar log returns std, annualized)
        if n >= 11:
            log_ret = np.diff(np.log(np.maximum(closes, 1e-10)))
            lr_w = sliding_window_view(log_ret, 10)
            hvol = np.std(lr_w, axis=1) * np.sqrt(252.0)
            hvol_full = np.full(n, 0.2, dtype=np.float64)
            hvol_full[10:10 + len(hvol)] = hvol
            F[:, fi] = hvol_full[idx]; fi += 1             # volatility_10
        else:
            F[:, fi] = 0.2; fi += 1

        # Volatility ratio (5-bar vs 20-bar)
        if n >= 21:
            lr = np.diff(np.log(np.maximum(closes, 1e-10)))
            lr5 = sliding_window_view(lr, 5)
            lr20 = sliding_window_view(lr, 20)
            v5 = np.std(lr5, axis=1)    # length n-5
            v20 = np.std(lr20, axis=1)  # length n-20
            vr_full = np.ones(n, dtype=np.float64)
            # Vectorized: v5[t-5] / v20[t-20] for each window position t
            i5 = idx - 5
            i20 = idx - 20
            valid = (i5 >= 0) & (i5 < len(v5)) & (i20 >= 0) & (i20 < len(v20))
            valid_i5 = i5[valid]
            valid_i20 = i20[valid]
            denom = v20[valid_i20]
            div_ok = denom > 1e-10
            vr_vals = np.ones(valid.sum(), dtype=np.float64)
            vr_vals[div_ok] = v5[valid_i5[div_ok]] / denom[div_ok]
            vr_full[idx[valid]] = vr_vals
            F[:, fi] = vr_full[idx]; fi += 1               # volatility_ratio
        else:
            F[:, fi] = 1.0; fi += 1

        # ── TREND (6) ──────────────────────────────────────────────────
        ema9 = self._ema_series(closes, 9)
        ema21 = self._ema_series(closes, 21)
        F[:, fi] = sd(c_t - ema9[idx], ema9[idx]);   fi += 1  # ema_9_distance
        F[:, fi] = sd(c_t - ema21[idx], ema21[idx]); fi += 1  # ema_21_distance

        if n >= 50:
            cw50 = sliding_window_view(closes, 50)
            sma50 = np.mean(cw50, axis=1)
            sma50_full = np.zeros(n, dtype=np.float64)
            sma50_full[49:49 + len(sma50)] = sma50
            F[:, fi] = sd(c_t - sma50_full[idx], sma50_full[idx]); fi += 1  # sma_50_distance
        else:
            F[:, fi] = 0.0; fi += 1

        # Trend strength (ADX-like)
        if n >= 15:
            up_moves = np.diff(highs)    # length n-1
            down_moves = -np.diff(lows)
            plus_dm = np.where((up_moves > down_moves) & (up_moves > 0), up_moves, 0.0)
            minus_dm = np.where((down_moves > up_moves) & (down_moves > 0), down_moves, 0.0)
            pdm_w = sliding_window_view(plus_dm, 13)   # 13 diffs over 14 bars
            mdm_w = sliding_window_view(minus_dm, 13)
            sum_pdm = np.sum(pdm_w, axis=1)
            sum_mdm = np.sum(mdm_w, axis=1)
            total = sum_pdm + sum_mdm
            ts_full = np.zeros(n, dtype=np.float64)
            ts_full[13:13 + len(total)] = np.where(total > 0, np.abs(sum_pdm - sum_mdm) / total, 0.0)
            F[:, fi] = ts_full[idx]; fi += 1               # trend_strength
        else:
            F[:, fi] = 0.0; fi += 1

        # Higher highs / lower lows (4-bar comparison) — vectorized
        hh = np.zeros(n, dtype=np.float64)
        ll = np.zeros(n, dtype=np.float64)
        if n >= 5:
            high_up = (np.diff(highs) > 0).astype(np.float64)
            low_dn = (np.diff(lows) < 0).astype(np.float64)
            if len(high_up) >= 4:
                hw = sliding_window_view(high_up, 4)
                lw = sliding_window_view(low_dn, 4)
                hh[4:4 + len(hw)] = np.mean(hw, axis=1)
                ll[4:4 + len(lw)] = np.mean(lw, axis=1)
        F[:, fi] = hh[idx]; fi += 1                        # higher_highs
        F[:, fi] = ll[idx]; fi += 1                        # lower_lows

        # ── PATTERN (4) ────────────────────────────────────────────────
        F[:, fi] = np.where((rng > 0) & (body / np.maximum(rng, 1e-10) < 0.1), 1.0, 0.0); fi += 1  # doji

        lw_pat = np.minimum(o_t, c_t) - l_t
        uw_pat = h_t - np.maximum(o_t, c_t)
        F[:, fi] = np.where((rng > 0) & (lw_pat > 2 * body) & (uw_pat < body), 1.0, 0.0); fi += 1  # hammer

        # Engulfing
        o_1 = opens[idx - 1]; c_prev = closes[idx - 1]
        prev_body = np.abs(c_prev - o_1)
        bull_eng = (c_t > o_t) & (c_prev < o_1) & (body > prev_body)
        bear_eng = (c_t < o_t) & (c_prev > o_1) & (body > prev_body)
        F[:, fi] = np.where(bull_eng, 1.0, np.where(bear_eng, -1.0, 0.0)); fi += 1  # engulfing

        # Inside bar
        F[:, fi] = np.where((h_t < highs[idx - 1]) & (l_t > lows[idx - 1]), 1.0, 0.0); fi += 1  # inside_bar

        # ── TIME (4) ───────────────────────────────────────────────────
        hours = np.zeros(n, dtype=np.float64)
        dows = np.full(n, 0.5, dtype=np.float64)
        for j in range(n):
            ts = bars[j].get("date", bars[j].get("timestamp", ""))
            if ts:
                try:
                    if isinstance(ts, str):
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    else:
                        dt = ts
                    hours[j] = dt.hour
                    dows[j] = dt.weekday() / 4.0
                except Exception:
                    pass
        F[:, fi] = np.sin(2.0 * np.pi * hours[idx] / 24.0); fi += 1  # hour_sin
        F[:, fi] = np.cos(2.0 * np.pi * hours[idx] / 24.0); fi += 1  # hour_cos
        F[:, fi] = dows[idx]; fi += 1                       # day_of_week
        F[:, fi] = np.where((hours[idx] >= 19) & (hours[idx] <= 20), 1.0, 0.0); fi += 1  # is_power_hour

        # Final NaN/Inf cleanup
        np.nan_to_num(F, copy=False, nan=0.0, posinf=0.0, neginf=0.0)

        return F.astype(np.float32)


# Singleton
_feature_engineer: Optional[TimeSeriesFeatureEngineer] = None


def get_feature_engineer(lookback: int = 50) -> TimeSeriesFeatureEngineer:
    """Get singleton instance"""
    global _feature_engineer
    if _feature_engineer is None:
        _feature_engineer = TimeSeriesFeatureEngineer(lookback)
    return _feature_engineer
