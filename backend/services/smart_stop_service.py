"""
Smart Stop Service - Anti-Stop-Hunt Stop Loss Management
=========================================================

This service implements intelligent stop loss strategies designed to:
1. Avoid obvious stop placement (support - small buffer)
2. Use ATR-based dynamic stops
3. Avoid round numbers and obvious clustering zones
4. Detect potential stop-hunt patterns
5. Implement layered/partial stops

Based on research into institutional stop-hunting tactics:
- Large players target stops below swing lows, above resistance, near round numbers
- Sharp spikes through levels followed by reversal = liquidity sweep
- Tight stops get hit more frequently
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class StopMode(Enum):
    """Available smart stop modes"""
    ORIGINAL = "original"           # Traditional: Support - small buffer
    ATR_DYNAMIC = "atr_dynamic"     # ATR-based: Support - 1.5x ATR
    ANTI_HUNT = "anti_hunt"         # Anti-hunt: Avoids obvious levels, uses deeper buffer
    VOLATILITY_ADJUSTED = "volatility_adjusted"  # Adjusts based on current volatility regime
    LAYERED = "layered"             # Multiple stop levels for partial exits
    CHANDELIER = "chandelier"       # Chandelier exit (ATR from high)


@dataclass
class SmartStopConfig:
    """Configuration for smart stop calculation"""
    mode: StopMode = StopMode.ATR_DYNAMIC
    atr_multiplier: float = 1.5     # Multiplier for ATR-based stops
    min_stop_distance_pct: float = 0.02  # Minimum 2% from entry
    max_stop_distance_pct: float = 0.08  # Maximum 8% from entry
    avoid_round_numbers: bool = True
    round_number_buffer_pct: float = 0.002  # 0.2% buffer from round numbers
    use_swing_levels: bool = True   # Consider swing highs/lows
    lookback_periods: int = 50      # Periods to look back for levels
    
    # Layered stop config
    layer_1_pct: float = 0.4        # 40% of position at first stop
    layer_2_pct: float = 0.3        # 30% at second (deeper) stop
    layer_3_pct: float = 0.3        # 30% at third (deepest) stop
    layer_depth_atr: List[float] = field(default_factory=lambda: [1.0, 1.5, 2.0])
    
    # Anti-hunt specific
    hunt_detection_lookback: int = 20
    hunt_volume_multiplier: float = 1.5
    post_sweep_confirmation_bars: int = 2
    
    # Chandelier config
    chandelier_period: int = 22
    chandelier_multiplier: float = 3.0


@dataclass
class StopHuntSignal:
    """Detected stop hunt pattern"""
    timestamp: datetime
    symbol: str
    direction: str  # 'long_sweep' or 'short_sweep'
    level_breached: float
    wick_low: float  # For long sweeps
    wick_high: float  # For short sweeps
    close_price: float
    volume_ratio: float
    confidence: float


class SmartStopService:
    """
    Service for calculating intelligent stop losses that avoid
    common stop-hunting tactics used by institutions.
    """
    
    def __init__(self, config: SmartStopConfig = None):
        self.config = config or SmartStopConfig()
        self._cache = {}
        self._hunt_signals = []
        
    def calculate_smart_stop(
        self,
        entry_price: float,
        direction: str,  # 'long' or 'short'
        symbol: str,
        atr: float = None,
        support_level: float = None,
        resistance_level: float = None,
        swing_low: float = None,
        swing_high: float = None,
        current_volatility_regime: str = "normal",  # "low", "normal", "high"
        mode: StopMode = None
    ) -> Dict[str, Any]:
        """
        Calculate smart stop loss based on the configured mode.
        
        Returns:
            Dict with:
            - stop_price: Primary stop level
            - stop_mode: The mode used
            - stop_reasoning: Explanation of the stop placement
            - layered_stops: Optional list of layered stop levels
            - avoid_zones: Price zones to avoid placing stops
            - anti_hunt_buffer: Additional buffer applied
        """
        mode = mode or self.config.mode
        
        # Calculate base stop using traditional method first
        base_stop = self._calculate_base_stop(
            entry_price, direction, support_level, resistance_level, 
            swing_low, swing_high, atr
        )
        
        # Apply mode-specific adjustments
        if mode == StopMode.ORIGINAL:
            result = self._apply_original_stop(entry_price, direction, base_stop, atr)
        elif mode == StopMode.ATR_DYNAMIC:
            result = self._apply_atr_dynamic_stop(entry_price, direction, atr)
        elif mode == StopMode.ANTI_HUNT:
            result = self._apply_anti_hunt_stop(
                entry_price, direction, base_stop, atr, 
                swing_low, swing_high, support_level, resistance_level
            )
        elif mode == StopMode.VOLATILITY_ADJUSTED:
            result = self._apply_volatility_adjusted_stop(
                entry_price, direction, base_stop, atr, current_volatility_regime
            )
        elif mode == StopMode.LAYERED:
            result = self._apply_layered_stop(entry_price, direction, atr, base_stop)
        elif mode == StopMode.CHANDELIER:
            result = self._apply_chandelier_stop(entry_price, direction, atr, swing_high, swing_low)
        else:
            result = self._apply_atr_dynamic_stop(entry_price, direction, atr)
        
        # Enforce min/max distance constraints
        result = self._enforce_stop_constraints(entry_price, direction, result)
        
        # Avoid round numbers if configured
        if self.config.avoid_round_numbers:
            result['stop_price'] = self._avoid_round_number(result['stop_price'], direction)
        
        # Add common info
        result['symbol'] = symbol
        result['entry_price'] = entry_price
        result['direction'] = direction
        result['stop_mode'] = mode.value
        result['calculated_at'] = datetime.now(timezone.utc).isoformat()
        
        return result
    
    def _calculate_base_stop(
        self,
        entry_price: float,
        direction: str,
        support_level: float,
        resistance_level: float,
        swing_low: float,
        swing_high: float,
        atr: float
    ) -> float:
        """Calculate traditional base stop level"""
        if direction == 'long':
            # Use the nearest level below entry
            candidates = [level for level in [support_level, swing_low] if level and level < entry_price]
            if candidates:
                return max(candidates)  # Highest level below entry
            # Default: entry - 2%
            return entry_price * 0.98
        else:  # short
            # Use the nearest level above entry
            candidates = [level for level in [resistance_level, swing_high] if level and level > entry_price]
            if candidates:
                return min(candidates)  # Lowest level above entry
            return entry_price * 1.02
    
    def _apply_original_stop(
        self,
        entry_price: float,
        direction: str,
        base_stop: float,
        atr: float
    ) -> Dict[str, Any]:
        """Traditional stop: level - small buffer"""
        small_buffer = atr * 0.3 if atr else entry_price * 0.005
        
        if direction == 'long':
            stop_price = round(base_stop - small_buffer, 2)
            reasoning = f"Traditional stop below support/swing low (${base_stop:.2f}) with small buffer"
        else:
            stop_price = round(base_stop + small_buffer, 2)
            reasoning = f"Traditional stop above resistance/swing high (${base_stop:.2f}) with small buffer"
        
        return {
            'stop_price': stop_price,
            'stop_reasoning': reasoning,
            'buffer_applied': small_buffer,
            'anti_hunt_buffer': 0,
            'hunt_risk': 'HIGH'  # Traditional stops are easily hunted
        }
    
    def _apply_atr_dynamic_stop(
        self,
        entry_price: float,
        direction: str,
        atr: float
    ) -> Dict[str, Any]:
        """ATR-based dynamic stop: entry - (ATR * multiplier)"""
        if not atr or atr <= 0:
            atr = entry_price * 0.02  # Default to 2% if no ATR
        
        buffer = atr * self.config.atr_multiplier
        
        if direction == 'long':
            stop_price = round(entry_price - buffer, 2)
            reasoning = f"ATR-dynamic stop: Entry ${entry_price:.2f} - {self.config.atr_multiplier}x ATR (${atr:.2f}) = ${stop_price:.2f}"
        else:
            stop_price = round(entry_price + buffer, 2)
            reasoning = f"ATR-dynamic stop: Entry ${entry_price:.2f} + {self.config.atr_multiplier}x ATR (${atr:.2f}) = ${stop_price:.2f}"
        
        return {
            'stop_price': stop_price,
            'stop_reasoning': reasoning,
            'buffer_applied': buffer,
            'anti_hunt_buffer': 0,
            'hunt_risk': 'MEDIUM'
        }
    
    def _apply_anti_hunt_stop(
        self,
        entry_price: float,
        direction: str,
        base_stop: float,
        atr: float,
        swing_low: float,
        swing_high: float,
        support: float,
        resistance: float
    ) -> Dict[str, Any]:
        """
        Anti-hunt stop: Places stop BEYOND obvious levels with extra buffer.
        
        Strategy:
        1. Identify obvious stop zones (round numbers, swing levels, support/resistance)
        2. Place stop deeper than these zones by 1-2 ATR
        3. Add buffer to avoid sweep wicks
        """
        if not atr or atr <= 0:
            atr = entry_price * 0.02
        
        # Collect all "obvious" levels that institutions might target
        obvious_zones = []
        
        if direction == 'long':
            # For longs, obvious stops are BELOW these levels
            if swing_low and swing_low < entry_price:
                obvious_zones.append(('swing_low', swing_low))
            if support and support < entry_price:
                obvious_zones.append(('support', support))
            
            # Add round number levels
            for round_level in self._get_nearby_round_numbers(entry_price, direction):
                if round_level < entry_price:
                    obvious_zones.append(('round_number', round_level))
            
            # Find the deepest obvious zone
            if obvious_zones:
                deepest_zone = min(obvious_zones, key=lambda x: x[1])
                zone_type, zone_price = deepest_zone
            else:
                zone_price = entry_price * 0.97
                zone_type = 'default'
            
            # Place stop DEEPER than the obvious zone by 1-2x ATR
            anti_hunt_buffer = atr * 1.5
            stop_price = round(zone_price - anti_hunt_buffer, 2)
            
            reasoning = (
                f"Anti-hunt stop placed below {zone_type} (${zone_price:.2f}) "
                f"with 1.5x ATR buffer (${anti_hunt_buffer:.2f}) to avoid sweep wicks"
            )
            
        else:  # short
            # For shorts, obvious stops are ABOVE these levels
            if swing_high and swing_high > entry_price:
                obvious_zones.append(('swing_high', swing_high))
            if resistance and resistance > entry_price:
                obvious_zones.append(('resistance', resistance))
            
            for round_level in self._get_nearby_round_numbers(entry_price, direction):
                if round_level > entry_price:
                    obvious_zones.append(('round_number', round_level))
            
            if obvious_zones:
                deepest_zone = max(obvious_zones, key=lambda x: x[1])
                zone_type, zone_price = deepest_zone
            else:
                zone_price = entry_price * 1.03
                zone_type = 'default'
            
            anti_hunt_buffer = atr * 1.5
            stop_price = round(zone_price + anti_hunt_buffer, 2)
            
            reasoning = (
                f"Anti-hunt stop placed above {zone_type} (${zone_price:.2f}) "
                f"with 1.5x ATR buffer (${anti_hunt_buffer:.2f}) to avoid sweep wicks"
            )
        
        return {
            'stop_price': stop_price,
            'stop_reasoning': reasoning,
            'buffer_applied': anti_hunt_buffer,
            'anti_hunt_buffer': anti_hunt_buffer,
            'obvious_zones_avoided': [z[1] for z in obvious_zones],
            'hunt_risk': 'LOW'
        }
    
    def _apply_volatility_adjusted_stop(
        self,
        entry_price: float,
        direction: str,
        base_stop: float,
        atr: float,
        volatility_regime: str
    ) -> Dict[str, Any]:
        """
        Volatility-adjusted stop: Wider in high vol, tighter in low vol.
        
        In high volatility:
        - Widen stops to avoid being shaken out by noise
        - Reduce position size to maintain same dollar risk
        
        In low volatility:
        - Can use tighter stops since moves are more meaningful
        """
        if not atr or atr <= 0:
            atr = entry_price * 0.02
        
        # Multiplier based on volatility regime
        vol_multipliers = {
            'low': 1.0,      # Normal ATR multiplier
            'normal': 1.5,   # Standard
            'high': 2.5,     # Wider stops in high vol
            'extreme': 3.0   # Very wide for crisis periods
        }
        
        multiplier = vol_multipliers.get(volatility_regime, 1.5)
        buffer = atr * multiplier
        
        if direction == 'long':
            stop_price = round(entry_price - buffer, 2)
        else:
            stop_price = round(entry_price + buffer, 2)
        
        reasoning = (
            f"Volatility-adjusted stop ({volatility_regime} regime): "
            f"{multiplier}x ATR = ${buffer:.2f} buffer"
        )
        
        return {
            'stop_price': stop_price,
            'stop_reasoning': reasoning,
            'buffer_applied': buffer,
            'anti_hunt_buffer': buffer - (atr * 1.5) if multiplier > 1.5 else 0,
            'volatility_regime': volatility_regime,
            'multiplier_used': multiplier,
            'hunt_risk': 'LOW' if volatility_regime in ['high', 'extreme'] else 'MEDIUM'
        }
    
    def _apply_layered_stop(
        self,
        entry_price: float,
        direction: str,
        atr: float,
        base_stop: float
    ) -> Dict[str, Any]:
        """
        Layered stop: Multiple stop levels for partial exits.
        
        Benefits:
        - Reduces impact of single sweep taking out entire position
        - Allows some position to survive brief stop hunts
        - Better average exit price if stop hunt reverses
        """
        if not atr or atr <= 0:
            atr = entry_price * 0.02
        
        layers = []
        for i, depth in enumerate(self.config.layer_depth_atr):
            buffer = atr * depth
            if direction == 'long':
                layer_stop = round(entry_price - buffer, 2)
            else:
                layer_stop = round(entry_price + buffer, 2)
            
            pct = [self.config.layer_1_pct, self.config.layer_2_pct, self.config.layer_3_pct][i]
            layers.append({
                'level': i + 1,
                'stop_price': layer_stop,
                'position_pct': pct,
                'atr_depth': depth
            })
        
        # Primary stop is the first layer
        primary_stop = layers[0]['stop_price']
        
        reasoning = (
            f"Layered stops: L1=${layers[0]['stop_price']:.2f} ({layers[0]['position_pct']*100:.0f}%), "
            f"L2=${layers[1]['stop_price']:.2f} ({layers[1]['position_pct']*100:.0f}%), "
            f"L3=${layers[2]['stop_price']:.2f} ({layers[2]['position_pct']*100:.0f}%)"
        )
        
        return {
            'stop_price': primary_stop,
            'stop_reasoning': reasoning,
            'buffer_applied': atr * self.config.layer_depth_atr[0],
            'anti_hunt_buffer': 0,
            'layered_stops': layers,
            'hunt_risk': 'LOW'  # Layered stops are harder to fully hunt
        }
    
    def _apply_chandelier_stop(
        self,
        entry_price: float,
        direction: str,
        atr: float,
        swing_high: float,
        swing_low: float
    ) -> Dict[str, Any]:
        """
        Chandelier Exit: ATR-based stop from recent high (longs) or low (shorts).
        
        For longs: Stop = Recent High - (ATR * multiplier)
        For shorts: Stop = Recent Low + (ATR * multiplier)
        
        This naturally trails as price moves in your favor.
        """
        if not atr or atr <= 0:
            atr = entry_price * 0.02
        
        buffer = atr * self.config.chandelier_multiplier
        
        if direction == 'long':
            # Use swing high if available, otherwise entry price
            reference = swing_high if swing_high and swing_high >= entry_price else entry_price
            stop_price = round(reference - buffer, 2)
            reasoning = f"Chandelier exit: High ${reference:.2f} - {self.config.chandelier_multiplier}x ATR (${buffer:.2f})"
        else:
            reference = swing_low if swing_low and swing_low <= entry_price else entry_price
            stop_price = round(reference + buffer, 2)
            reasoning = f"Chandelier exit: Low ${reference:.2f} + {self.config.chandelier_multiplier}x ATR (${buffer:.2f})"
        
        return {
            'stop_price': stop_price,
            'stop_reasoning': reasoning,
            'buffer_applied': buffer,
            'anti_hunt_buffer': buffer - atr,  # Extra beyond 1x ATR
            'reference_price': reference,
            'hunt_risk': 'MEDIUM'
        }
    
    def _enforce_stop_constraints(
        self,
        entry_price: float,
        direction: str,
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Enforce minimum and maximum stop distance constraints"""
        stop_price = result['stop_price']
        
        min_distance = entry_price * self.config.min_stop_distance_pct
        max_distance = entry_price * self.config.max_stop_distance_pct
        
        if direction == 'long':
            min_stop = entry_price - max_distance
            max_stop = entry_price - min_distance
            
            if stop_price > max_stop:
                stop_price = round(max_stop, 2)
                result['constraint_applied'] = 'min_distance'
            elif stop_price < min_stop:
                stop_price = round(min_stop, 2)
                result['constraint_applied'] = 'max_distance'
        else:
            min_stop = entry_price + min_distance
            max_stop = entry_price + max_distance
            
            if stop_price < min_stop:
                stop_price = round(min_stop, 2)
                result['constraint_applied'] = 'min_distance'
            elif stop_price > max_stop:
                stop_price = round(max_stop, 2)
                result['constraint_applied'] = 'max_distance'
        
        result['stop_price'] = stop_price
        return result
    
    def _avoid_round_number(self, stop_price: float, direction: str) -> float:
        """
        Adjust stop to avoid obvious round numbers.
        
        Round numbers (50, 100, 150, etc.) are magnets for stop clusters.
        Place stop slightly beyond these levels.
        """
        # Check nearby round numbers
        for divisor in [100, 50, 25, 10]:
            nearest_round = round(stop_price / divisor) * divisor
            distance_pct = abs(stop_price - nearest_round) / stop_price
            
            if distance_pct < self.config.round_number_buffer_pct:
                buffer = stop_price * self.config.round_number_buffer_pct
                
                if direction == 'long':
                    # For longs, place stop BELOW the round number
                    stop_price = round(nearest_round - buffer, 2)
                else:
                    # For shorts, place stop ABOVE the round number
                    stop_price = round(nearest_round + buffer, 2)
                
                logger.debug(f"Avoiding round number ${nearest_round:.2f}, adjusted stop to ${stop_price:.2f}")
                break
        
        return stop_price
    
    def _get_nearby_round_numbers(self, price: float, direction: str, range_pct: float = 0.05) -> List[float]:
        """Get round numbers near the current price"""
        round_numbers = []
        
        lower = price * (1 - range_pct)
        upper = price * (1 + range_pct)
        
        for divisor in [100, 50, 25, 10]:
            level = round(price / divisor) * divisor
            
            # Check levels above and below
            for offset in [-2, -1, 0, 1, 2]:
                candidate = level + (offset * divisor)
                if lower <= candidate <= upper:
                    round_numbers.append(candidate)
        
        return sorted(set(round_numbers))
    
    def detect_stop_hunt(
        self,
        df: pd.DataFrame,
        symbol: str,
        support_levels: List[float] = None,
        resistance_levels: List[float] = None
    ) -> List[StopHuntSignal]:
        """
        Detect potential stop hunt patterns in price data.
        
        Stop hunt signatures:
        1. Sharp spike through a key level (support/resistance/swing)
        2. High volume during the spike
        3. Close back inside the prior range (pin bar/false breakout)
        
        Args:
            df: DataFrame with OHLCV data (columns: open, high, low, close, volume)
            symbol: Ticker symbol
            support_levels: Known support levels to watch
            resistance_levels: Known resistance levels to watch
            
        Returns:
            List of detected StopHuntSignal objects
        """
        if df is None or len(df) < self.config.hunt_detection_lookback:
            return []
        
        signals = []
        df = df.copy()
        
        # Calculate ATR for reference
        df['atr'] = self._calculate_atr(df, period=14)
        
        # Calculate average volume
        df['avg_volume'] = df['volume'].rolling(50).mean()
        
        # Detect swing levels if not provided
        if not support_levels:
            support_levels = self._detect_swing_lows(df, lookback=self.config.hunt_detection_lookback)
        if not resistance_levels:
            resistance_levels = self._detect_swing_highs(df, lookback=self.config.hunt_detection_lookback)
        
        # Scan for stop hunt patterns
        for i in range(self.config.hunt_detection_lookback, len(df)):
            bar = df.iloc[i]
            _prev_bar = df.iloc[i-1]
            atr = bar['atr']
            avg_vol = bar['avg_volume']
            
            if pd.isna(atr) or pd.isna(avg_vol):
                continue
            
            vol_ratio = bar['volume'] / avg_vol if avg_vol > 0 else 1.0
            
            # Check for long sweep (wick below support, close above)
            for support in support_levels:
                if (bar['low'] < support - atr * 0.5 and 
                    bar['close'] > support and
                    vol_ratio >= self.config.hunt_volume_multiplier):
                    
                    confidence = min(100, 50 + (vol_ratio - 1) * 25)
                    
                    signals.append(StopHuntSignal(
                        timestamp=df.index[i] if isinstance(df.index[i], datetime) else datetime.now(timezone.utc),
                        symbol=symbol,
                        direction='long_sweep',
                        level_breached=support,
                        wick_low=bar['low'],
                        wick_high=bar['high'],
                        close_price=bar['close'],
                        volume_ratio=vol_ratio,
                        confidence=confidence
                    ))
            
            # Check for short sweep (wick above resistance, close below)
            for resistance in resistance_levels:
                if (bar['high'] > resistance + atr * 0.5 and 
                    bar['close'] < resistance and
                    vol_ratio >= self.config.hunt_volume_multiplier):
                    
                    confidence = min(100, 50 + (vol_ratio - 1) * 25)
                    
                    signals.append(StopHuntSignal(
                        timestamp=df.index[i] if isinstance(df.index[i], datetime) else datetime.now(timezone.utc),
                        symbol=symbol,
                        direction='short_sweep',
                        level_breached=resistance,
                        wick_low=bar['low'],
                        wick_high=bar['high'],
                        close_price=bar['close'],
                        volume_ratio=vol_ratio,
                        confidence=confidence
                    ))
        
        return signals
    
    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate Average True Range"""
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.rolling(period).mean()
    
    def _detect_swing_lows(self, df: pd.DataFrame, lookback: int = 20) -> List[float]:
        """Detect swing low levels"""
        lows = df['low'].values
        swing_lows = []
        
        for i in range(2, len(lows) - 2):
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                swing_lows.append(lows[i])
        
        return sorted(set(swing_lows))[-5:]  # Return last 5 swing lows
    
    def _detect_swing_highs(self, df: pd.DataFrame, lookback: int = 20) -> List[float]:
        """Detect swing high levels"""
        highs = df['high'].values
        swing_highs = []
        
        for i in range(2, len(highs) - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                swing_highs.append(highs[i])
        
        return sorted(set(swing_highs))[-5:]  # Return last 5 swing highs
    
    def get_recommended_mode(
        self,
        symbol: str,
        float_shares: float = None,
        avg_volume: float = None,
        volatility_regime: str = "normal",
        time_of_day: str = "regular"  # "premarket", "regular", "afterhours"
    ) -> StopMode:
        """
        Recommend the best stop mode based on stock characteristics.
        
        Low float/volume stocks: Higher hunt risk -> use ANTI_HUNT
        High volatility: Use VOLATILITY_ADJUSTED
        Pre/after hours: Use wider stops (ANTI_HUNT or CHANDELIER)
        """
        # Low float stocks are easier to manipulate
        if float_shares and float_shares < 10_000_000:
            return StopMode.ANTI_HUNT
        
        # Low volume stocks
        if avg_volume and avg_volume < 500_000:
            return StopMode.ANTI_HUNT
        
        # High volatility
        if volatility_regime in ['high', 'extreme']:
            return StopMode.VOLATILITY_ADJUSTED
        
        # Thin markets (pre/after hours)
        if time_of_day in ['premarket', 'afterhours']:
            return StopMode.ANTI_HUNT
        
        # Default to ATR dynamic for liquid stocks in regular hours
        return StopMode.ATR_DYNAMIC


# Global instance
_smart_stop_service: SmartStopService = None


def get_smart_stop_service() -> SmartStopService:
    """Get or create the SmartStopService instance"""
    global _smart_stop_service
    if _smart_stop_service is None:
        _smart_stop_service = SmartStopService()
    return _smart_stop_service


def init_smart_stop_service(config: SmartStopConfig = None) -> SmartStopService:
    """Initialize the SmartStopService with custom config"""
    global _smart_stop_service
    _smart_stop_service = SmartStopService(config=config)
    return _smart_stop_service
