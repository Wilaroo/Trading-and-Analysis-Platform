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
            tr = np.maximum(
                highs[:14] - lows[:14],
                np.maximum(
                    np.abs(highs[:14] - np.roll(closes[:14], 1)[1:15]),
                    np.abs(lows[:14] - np.roll(closes[:14], 1)[1:15])
                )
            )
            atr = np.mean(tr[:14])
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


# Singleton
_feature_engineer: Optional[TimeSeriesFeatureEngineer] = None


def get_feature_engineer(lookback: int = 50) -> TimeSeriesFeatureEngineer:
    """Get singleton instance"""
    global _feature_engineer
    if _feature_engineer is None:
        _feature_engineer = TimeSeriesFeatureEngineer(lookback)
    return _feature_engineer
