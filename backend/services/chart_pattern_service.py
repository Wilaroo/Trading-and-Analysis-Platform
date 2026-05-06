"""
Advanced Chart Pattern Detection Service
Detects classic technical patterns: flags, pennants, wedges, head & shoulders, triangles.
Integrates with scanner and AI for pattern-based trade alerts.
"""
import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Dict, List, Optional
from enum import Enum
import numpy as np

logger = logging.getLogger(__name__)


class PatternType(Enum):
    """Types of chart patterns detected"""
    BULL_FLAG = "bull_flag"
    BEAR_FLAG = "bear_flag"
    BULL_PENNANT = "bull_pennant"
    BEAR_PENNANT = "bear_pennant"
    ASCENDING_TRIANGLE = "ascending_triangle"
    DESCENDING_TRIANGLE = "descending_triangle"
    SYMMETRIC_TRIANGLE = "symmetric_triangle"
    RISING_WEDGE = "rising_wedge"        # Bearish
    FALLING_WEDGE = "falling_wedge"      # Bullish
    HEAD_SHOULDERS = "head_shoulders"     # Bearish reversal
    INVERSE_HEAD_SHOULDERS = "inverse_head_shoulders"  # Bullish reversal
    DOUBLE_TOP = "double_top"            # Bearish
    DOUBLE_BOTTOM = "double_bottom"      # Bullish
    CUP_HANDLE = "cup_handle"            # Bullish continuation


class PatternStrength(Enum):
    """Pattern quality/reliability"""
    STRONG = "strong"        # Clear pattern, high probability
    MODERATE = "moderate"    # Good pattern, reasonable setup
    WEAK = "weak"           # Pattern forming, needs confirmation


@dataclass
class ChartPattern:
    """Detected chart pattern with actionable data"""
    symbol: str
    pattern_type: PatternType
    strength: PatternStrength
    direction: str  # "bullish" or "bearish"
    
    # Price levels
    current_price: float
    entry_price: float       # Optimal entry (breakout level)
    stop_loss: float
    target_price: float
    
    # Pattern specifics
    pattern_start: str       # ISO date when pattern started
    pattern_duration_days: int
    breakout_pending: bool   # True if pattern not yet broken
    
    # Metrics
    risk_reward: float
    pattern_score: float     # 0-100 quality score
    volume_confirmation: bool
    
    # Context
    reasoning: List[str]
    detected_at: str
    
    def to_dict(self) -> Dict:
        result = {
            'symbol': self.symbol,
            'pattern_type': self.pattern_type.value,
            'strength': self.strength.value,
            'direction': self.direction,
            'current_price': float(self.current_price),
            'entry_price': float(self.entry_price),
            'stop_loss': float(self.stop_loss),
            'target_price': float(self.target_price),
            'pattern_start': self.pattern_start,
            'pattern_duration_days': int(self.pattern_duration_days),
            'breakout_pending': bool(self.breakout_pending),
            'risk_reward': float(self.risk_reward),
            'pattern_score': float(self.pattern_score),
            'volume_confirmation': bool(self.volume_confirmation),
            'reasoning': list(self.reasoning),
            'detected_at': self.detected_at
        }
        return result


class ChartPatternService:
    """
    Detects and analyzes chart patterns for trading opportunities.
    Uses price action and volume analysis.
    """
    
    def __init__(self):
        self._alpaca_service = None
        self._pattern_cache: Dict[str, List[ChartPattern]] = {}
        self._initialized = False
    
    def is_initialized(self) -> bool:
        """Check if service is properly initialized"""
        return self._initialized and self._alpaca_service is not None
    
    def set_alpaca_service(self, alpaca_service):
        """Set the Alpaca service for data access"""
        self._alpaca_service = alpaca_service
        self._initialized = True
        logger.info("ChartPatternService initialized with Alpaca service")
    
    def _ensure_initialized(self) -> bool:
        """Ensure service is initialized before operations"""
        if not self.is_initialized():
            logger.warning("ChartPatternService not initialized - call set_alpaca_service() first")
            return False
        return True
    
    async def detect_patterns(self, symbol: str, bars: List[Dict] = None) -> List[ChartPattern]:
        """
        Detect all chart patterns for a symbol.
        Returns list of detected patterns sorted by strength.
        """
        if not self._ensure_initialized():
            return []
        
        symbol = symbol.upper()
        
        # Get bar data if not provided
        if not bars:
            try:
                bars = await self._alpaca_service.get_bars(symbol, timeframe="1Day", limit=60)
            except Exception as e:
                logger.error(f"Could not fetch bars for {symbol}: {e}")
                return []
        
        if not bars or len(bars) < 20:
            return []
        
        patterns = []
        
        # Extract price arrays
        closes = np.array([b.get('close', b.get('c', 0)) for b in bars])
        highs = np.array([b.get('high', b.get('h', 0)) for b in bars])
        lows = np.array([b.get('low', b.get('l', 0)) for b in bars])
        volumes = np.array([b.get('volume', b.get('v', 0)) for b in bars])
        
        current_price = closes[-1]
        
        # Detect various patterns
        flag_pattern = self._detect_flag(symbol, closes, highs, lows, volumes, current_price)
        if flag_pattern:
            patterns.append(flag_pattern)
        
        pennant_pattern = self._detect_pennant(symbol, closes, highs, lows, volumes, current_price)
        if pennant_pattern:
            patterns.append(pennant_pattern)
        
        triangle_pattern = self._detect_triangle(symbol, closes, highs, lows, volumes, current_price)
        if triangle_pattern:
            patterns.append(triangle_pattern)
        
        wedge_pattern = self._detect_wedge(symbol, closes, highs, lows, volumes, current_price)
        if wedge_pattern:
            patterns.append(wedge_pattern)
        
        hs_pattern = self._detect_head_shoulders(symbol, closes, highs, lows, volumes, current_price)
        if hs_pattern:
            patterns.append(hs_pattern)
        
        double_pattern = self._detect_double_top_bottom(symbol, closes, highs, lows, volumes, current_price)
        if double_pattern:
            patterns.append(double_pattern)
        
        # Cache results
        self._pattern_cache[symbol] = patterns
        
        # Sort by pattern score
        patterns.sort(key=lambda x: x.pattern_score, reverse=True)
        
        return patterns
    
    def _detect_flag(self, symbol: str, closes: np.ndarray, highs: np.ndarray, 
                     lows: np.ndarray, volumes: np.ndarray, current_price: float) -> Optional[ChartPattern]:
        """
        Detect bull/bear flag patterns.
        Flag = strong move (pole) followed by consolidation (flag).
        """
        if len(closes) < 20:
            return None
        
        # Look for flag in last 20 bars
        recent = closes[-20:]
        recent_highs = highs[-20:]
        recent_lows = lows[-20:]
        
        # Find the pole (strong move in first 5-10 bars)
        pole_start = recent[0]
        pole_end = max(recent[:10])  # For bull flag
        pole_move = (pole_end - pole_start) / pole_start if pole_start > 0 else 0
        
        # Check for consolidation after pole
        flag_section = recent[10:]
        flag_highs = recent_highs[10:]
        flag_lows = recent_lows[10:]
        
        flag_high = max(flag_highs)
        flag_low = min(flag_lows)
        flag_range = (flag_high - flag_low) / flag_high if flag_high > 0 else 0
        
        # Bull flag criteria: pole up 5%+, flag range < 5%, flag slopes slightly down
        if pole_move > 0.05 and flag_range < 0.05:
            # Check flag slopes down (higher highs to lower highs)
            if flag_highs[-1] < flag_highs[0]:
                return ChartPattern(
                    symbol=symbol,
                    pattern_type=PatternType.BULL_FLAG,
                    strength=PatternStrength.STRONG if pole_move > 0.08 else PatternStrength.MODERATE,
                    direction="bullish",
                    current_price=current_price,
                    entry_price=flag_high * 1.002,  # Breakout above flag
                    stop_loss=flag_low * 0.99,
                    target_price=flag_high + (pole_end - pole_start),  # Measured move
                    pattern_start=datetime.now(timezone.utc).isoformat(),
                    pattern_duration_days=10,
                    breakout_pending=current_price < flag_high,
                    risk_reward=self._calc_rr(flag_high, flag_low, flag_high + (pole_end - pole_start)),
                    pattern_score=75 if pole_move > 0.08 else 60,
                    volume_confirmation=volumes[-1] < np.mean(volumes[-10:]),
                    reasoning=[
                        f"Bull flag: {pole_move*100:.1f}% pole move",
                        f"Tight consolidation: {flag_range*100:.1f}% range",
                        f"Breakout level: ${flag_high:.2f}"
                    ],
                    detected_at=datetime.now(timezone.utc).isoformat()
                )
        
        # Check for bear flag (inverse)
        pole_low = min(recent[:10])
        pole_move_bear = (pole_start - pole_low) / pole_start if pole_start > 0 else 0
        
        if pole_move_bear > 0.05 and flag_range < 0.05:
            if flag_lows[-1] > flag_lows[0]:  # Flag slopes up
                return ChartPattern(
                    symbol=symbol,
                    pattern_type=PatternType.BEAR_FLAG,
                    strength=PatternStrength.STRONG if pole_move_bear > 0.08 else PatternStrength.MODERATE,
                    direction="bearish",
                    current_price=current_price,
                    entry_price=flag_low * 0.998,  # Breakdown below flag
                    stop_loss=flag_high * 1.01,
                    target_price=flag_low - (pole_start - pole_low),
                    pattern_start=datetime.now(timezone.utc).isoformat(),
                    pattern_duration_days=10,
                    breakout_pending=current_price > flag_low,
                    risk_reward=self._calc_rr(flag_low, flag_high, flag_low - (pole_start - pole_low)),
                    pattern_score=75 if pole_move_bear > 0.08 else 60,
                    volume_confirmation=volumes[-1] < np.mean(volumes[-10:]),
                    reasoning=[
                        f"Bear flag: {pole_move_bear*100:.1f}% pole drop",
                        f"Tight consolidation: {flag_range*100:.1f}% range",
                        f"Breakdown level: ${flag_low:.2f}"
                    ],
                    detected_at=datetime.now(timezone.utc).isoformat()
                )
        
        return None
    
    def _detect_pennant(self, symbol: str, closes: np.ndarray, highs: np.ndarray,
                        lows: np.ndarray, volumes: np.ndarray, current_price: float) -> Optional[ChartPattern]:
        """
        Detect pennant patterns (converging trendlines after strong move).
        """
        if len(closes) < 15:
            return None
        
        recent = closes[-15:]
        recent_highs = highs[-15:]
        recent_lows = lows[-15:]
        
        # Check for converging highs and lows (pennant shape)
        high_slope = (recent_highs[-1] - recent_highs[5]) / recent_highs[5] if recent_highs[5] > 0 else 0
        low_slope = (recent_lows[-1] - recent_lows[5]) / recent_lows[5] if recent_lows[5] > 0 else 0
        
        # Pennant: highs trending down, lows trending up (convergence)
        if high_slope < -0.01 and low_slope > 0.01:
            # Determine direction based on prior trend
            prior_move = (recent[4] - recent[0]) / recent[0] if recent[0] > 0 else 0
            
            if prior_move > 0.03:  # Bull pennant
                apex = (recent_highs[-1] + recent_lows[-1]) / 2
                target = apex + abs(recent[4] - recent[0])
                
                return ChartPattern(
                    symbol=symbol,
                    pattern_type=PatternType.BULL_PENNANT,
                    strength=PatternStrength.MODERATE,
                    direction="bullish",
                    current_price=current_price,
                    entry_price=recent_highs[-1] * 1.002,
                    stop_loss=recent_lows[-1] * 0.99,
                    target_price=target,
                    pattern_start=datetime.now(timezone.utc).isoformat(),
                    pattern_duration_days=8,
                    breakout_pending=True,
                    risk_reward=self._calc_rr(recent_highs[-1], recent_lows[-1], target),
                    pattern_score=65,
                    volume_confirmation=volumes[-1] < np.mean(volumes[-8:]),
                    reasoning=[
                        "Pennant formation with converging trendlines",
                        f"Prior uptrend: +{prior_move*100:.1f}%",
                        "Volume contracting - breakout imminent"
                    ],
                    detected_at=datetime.now(timezone.utc).isoformat()
                )
            
            elif prior_move < -0.03:  # Bear pennant
                apex = (recent_highs[-1] + recent_lows[-1]) / 2
                target = apex - abs(recent[0] - recent[4])
                
                return ChartPattern(
                    symbol=symbol,
                    pattern_type=PatternType.BEAR_PENNANT,
                    strength=PatternStrength.MODERATE,
                    direction="bearish",
                    current_price=current_price,
                    entry_price=recent_lows[-1] * 0.998,
                    stop_loss=recent_highs[-1] * 1.01,
                    target_price=target,
                    pattern_start=datetime.now(timezone.utc).isoformat(),
                    pattern_duration_days=8,
                    breakout_pending=True,
                    risk_reward=self._calc_rr(recent_lows[-1], recent_highs[-1], target),
                    pattern_score=65,
                    volume_confirmation=volumes[-1] < np.mean(volumes[-8:]),
                    reasoning=[
                        "Bear pennant with converging trendlines",
                        f"Prior downtrend: {prior_move*100:.1f}%",
                        "Expecting downside continuation"
                    ],
                    detected_at=datetime.now(timezone.utc).isoformat()
                )
        
        return None
    
    def _detect_triangle(self, symbol: str, closes: np.ndarray, highs: np.ndarray,
                         lows: np.ndarray, volumes: np.ndarray, current_price: float) -> Optional[ChartPattern]:
        """
        Detect ascending, descending, and symmetric triangles.
        """
        if len(closes) < 20:
            return None
        
        recent_highs = highs[-20:]
        recent_lows = lows[-20:]
        
        # Calculate slopes
        high_slope = np.polyfit(range(len(recent_highs)), recent_highs, 1)[0]
        low_slope = np.polyfit(range(len(recent_lows)), recent_lows, 1)[0]
        
        # Normalize slopes
        avg_price = np.mean(closes[-20:])
        high_slope_pct = high_slope / avg_price if avg_price > 0 else 0
        low_slope_pct = low_slope / avg_price if avg_price > 0 else 0
        
        # Ascending triangle: flat highs, rising lows
        if abs(high_slope_pct) < 0.001 and low_slope_pct > 0.001:
            resistance = max(recent_highs[-5:])
            support = min(recent_lows[-5:])
            
            return ChartPattern(
                symbol=symbol,
                pattern_type=PatternType.ASCENDING_TRIANGLE,
                strength=PatternStrength.STRONG,
                direction="bullish",
                current_price=current_price,
                entry_price=resistance * 1.003,
                stop_loss=support * 0.98,
                target_price=resistance + (resistance - support),
                pattern_start=datetime.now(timezone.utc).isoformat(),
                pattern_duration_days=15,
                breakout_pending=current_price < resistance,
                risk_reward=self._calc_rr(resistance, support, resistance + (resistance - support)),
                pattern_score=70,
                volume_confirmation=True,
                reasoning=[
                    f"Ascending triangle: Resistance at ${resistance:.2f}",
                    "Higher lows showing accumulation",
                    "Bullish breakout expected"
                ],
                detected_at=datetime.now(timezone.utc).isoformat()
            )
        
        # Descending triangle: falling highs, flat lows
        if high_slope_pct < -0.001 and abs(low_slope_pct) < 0.001:
            resistance = max(recent_highs[-5:])
            support = min(recent_lows[-5:])
            
            return ChartPattern(
                symbol=symbol,
                pattern_type=PatternType.DESCENDING_TRIANGLE,
                strength=PatternStrength.STRONG,
                direction="bearish",
                current_price=current_price,
                entry_price=support * 0.997,
                stop_loss=resistance * 1.02,
                target_price=support - (resistance - support),
                pattern_start=datetime.now(timezone.utc).isoformat(),
                pattern_duration_days=15,
                breakout_pending=current_price > support,
                risk_reward=self._calc_rr(support, resistance, support - (resistance - support)),
                pattern_score=70,
                volume_confirmation=True,
                reasoning=[
                    f"Descending triangle: Support at ${support:.2f}",
                    "Lower highs showing distribution",
                    "Bearish breakdown expected"
                ],
                detected_at=datetime.now(timezone.utc).isoformat()
            )
        
        # Symmetric triangle: converging
        if high_slope_pct < -0.0005 and low_slope_pct > 0.0005:
            apex = (max(recent_highs[-3:]) + min(recent_lows[-3:])) / 2
            breakout_up = max(recent_highs[-3:])
            breakout_down = min(recent_lows[-3:])
            
            return ChartPattern(
                symbol=symbol,
                pattern_type=PatternType.SYMMETRIC_TRIANGLE,
                strength=PatternStrength.MODERATE,
                direction="neutral",  # Could break either way
                current_price=current_price,
                entry_price=breakout_up,
                stop_loss=breakout_down,
                target_price=breakout_up + (breakout_up - breakout_down),
                pattern_start=datetime.now(timezone.utc).isoformat(),
                pattern_duration_days=15,
                breakout_pending=True,
                risk_reward=2.0,
                pattern_score=55,
                volume_confirmation=volumes[-1] < np.mean(volumes[-15:]),
                reasoning=[
                    "Symmetric triangle - neutral bias",
                    f"Upper breakout: ${breakout_up:.2f}",
                    f"Lower breakdown: ${breakout_down:.2f}",
                    "Wait for direction confirmation"
                ],
                detected_at=datetime.now(timezone.utc).isoformat()
            )
        
        return None
    
    def _detect_wedge(self, symbol: str, closes: np.ndarray, highs: np.ndarray,
                      lows: np.ndarray, volumes: np.ndarray, current_price: float) -> Optional[ChartPattern]:
        """
        Detect rising and falling wedge patterns.
        Rising wedge = bearish, Falling wedge = bullish.
        """
        if len(closes) < 25:
            return None
        
        recent_highs = highs[-25:]
        recent_lows = lows[-25:]
        
        high_slope = np.polyfit(range(len(recent_highs)), recent_highs, 1)[0]
        low_slope = np.polyfit(range(len(recent_lows)), recent_lows, 1)[0]
        
        avg_price = np.mean(closes[-25:])
        
        # Rising wedge: both slopes positive, converging
        if high_slope > 0 and low_slope > 0 and low_slope > high_slope:
            support = min(recent_lows[-3:])
            resistance = max(recent_highs[-3:])
            
            return ChartPattern(
                symbol=symbol,
                pattern_type=PatternType.RISING_WEDGE,
                strength=PatternStrength.MODERATE,
                direction="bearish",
                current_price=current_price,
                entry_price=support * 0.998,  # Short on breakdown
                stop_loss=resistance * 1.01,
                target_price=support - (resistance - support) * 0.618,
                pattern_start=datetime.now(timezone.utc).isoformat(),
                pattern_duration_days=20,
                breakout_pending=current_price > support,
                risk_reward=self._calc_rr(support, resistance, support - (resistance - support) * 0.618),
                pattern_score=60,
                volume_confirmation=volumes[-1] < np.mean(volumes[-20:]),
                reasoning=[
                    "Rising wedge - bearish reversal pattern",
                    "Price rising on weakening momentum",
                    f"Breakdown target: ${(support - (resistance - support) * 0.618):.2f}"
                ],
                detected_at=datetime.now(timezone.utc).isoformat()
            )
        
        # Falling wedge: both slopes negative, converging
        if high_slope < 0 and low_slope < 0 and low_slope < high_slope:
            support = min(recent_lows[-3:])
            resistance = max(recent_highs[-3:])
            
            return ChartPattern(
                symbol=symbol,
                pattern_type=PatternType.FALLING_WEDGE,
                strength=PatternStrength.MODERATE,
                direction="bullish",
                current_price=current_price,
                entry_price=resistance * 1.002,  # Long on breakout
                stop_loss=support * 0.99,
                target_price=resistance + (resistance - support) * 0.618,
                pattern_start=datetime.now(timezone.utc).isoformat(),
                pattern_duration_days=20,
                breakout_pending=current_price < resistance,
                risk_reward=self._calc_rr(resistance, support, resistance + (resistance - support) * 0.618),
                pattern_score=60,
                volume_confirmation=volumes[-1] < np.mean(volumes[-20:]),
                reasoning=[
                    "Falling wedge - bullish reversal pattern",
                    "Price falling with support building",
                    f"Breakout target: ${(resistance + (resistance - support) * 0.618):.2f}"
                ],
                detected_at=datetime.now(timezone.utc).isoformat()
            )
        
        return None
    
    def _detect_head_shoulders(self, symbol: str, closes: np.ndarray, highs: np.ndarray,
                               lows: np.ndarray, volumes: np.ndarray, current_price: float) -> Optional[ChartPattern]:
        """
        Detect head and shoulders / inverse head and shoulders patterns.
        """
        if len(closes) < 30:
            return None
        
        # Find local peaks and troughs
        peaks = self._find_peaks(highs[-30:])
        troughs = self._find_troughs(lows[-30:])
        
        if len(peaks) < 3 or len(troughs) < 2:
            return None
        
        # Check for H&S pattern: left shoulder, head (higher), right shoulder (similar to left)
        if len(peaks) >= 3:
            left_shoulder = highs[-30:][peaks[-3]]
            head = highs[-30:][peaks[-2]]
            right_shoulder = highs[-30:][peaks[-1]]
            
            # Head should be highest, shoulders roughly equal
            if (head > left_shoulder * 1.02 and 
                head > right_shoulder * 1.02 and
                abs(left_shoulder - right_shoulder) / left_shoulder < 0.03):
                
                # Neckline from troughs
                neckline = min(lows[-30:][troughs[-2]], lows[-30:][troughs[-1]])
                target = neckline - (head - neckline)
                
                return ChartPattern(
                    symbol=symbol,
                    pattern_type=PatternType.HEAD_SHOULDERS,
                    strength=PatternStrength.STRONG,
                    direction="bearish",
                    current_price=current_price,
                    entry_price=neckline * 0.998,
                    stop_loss=right_shoulder * 1.01,
                    target_price=target,
                    pattern_start=datetime.now(timezone.utc).isoformat(),
                    pattern_duration_days=25,
                    breakout_pending=current_price > neckline,
                    risk_reward=self._calc_rr(neckline, right_shoulder, target),
                    pattern_score=80,
                    volume_confirmation=True,
                    reasoning=[
                        "Head & Shoulders reversal pattern",
                        f"Neckline: ${neckline:.2f}",
                        f"Measured target: ${target:.2f}",
                        "Classic bearish reversal - high reliability"
                    ],
                    detected_at=datetime.now(timezone.utc).isoformat()
                )
        
        # Check for inverse H&S
        if len(troughs) >= 3:
            left_shoulder = lows[-30:][troughs[-3]]
            head = lows[-30:][troughs[-2]]
            right_shoulder = lows[-30:][troughs[-1]]
            
            if (head < left_shoulder * 0.98 and 
                head < right_shoulder * 0.98 and
                abs(left_shoulder - right_shoulder) / left_shoulder < 0.03):
                
                neckline = max(highs[-30:][peaks[-2]] if len(peaks) > 1 else highs[-30:][peaks[-1]], 
                              highs[-30:][peaks[-1]])
                target = neckline + (neckline - head)
                
                return ChartPattern(
                    symbol=symbol,
                    pattern_type=PatternType.INVERSE_HEAD_SHOULDERS,
                    strength=PatternStrength.STRONG,
                    direction="bullish",
                    current_price=current_price,
                    entry_price=neckline * 1.002,
                    stop_loss=right_shoulder * 0.99,
                    target_price=target,
                    pattern_start=datetime.now(timezone.utc).isoformat(),
                    pattern_duration_days=25,
                    breakout_pending=current_price < neckline,
                    risk_reward=self._calc_rr(neckline, right_shoulder, target),
                    pattern_score=80,
                    volume_confirmation=True,
                    reasoning=[
                        "Inverse H&S bullish reversal",
                        f"Neckline resistance: ${neckline:.2f}",
                        f"Measured target: ${target:.2f}",
                        "High-probability bullish reversal"
                    ],
                    detected_at=datetime.now(timezone.utc).isoformat()
                )
        
        return None
    
    def _detect_double_top_bottom(self, symbol: str, closes: np.ndarray, highs: np.ndarray,
                                  lows: np.ndarray, volumes: np.ndarray, current_price: float) -> Optional[ChartPattern]:
        """
        Detect double top and double bottom patterns.
        """
        if len(closes) < 25:
            return None
        
        peaks = self._find_peaks(highs[-25:])
        troughs = self._find_troughs(lows[-25:])
        
        # Double top: two similar peaks with valley between
        if len(peaks) >= 2:
            peak1 = highs[-25:][peaks[-2]]
            peak2 = highs[-25:][peaks[-1]]
            
            # Peaks within 2% of each other
            if abs(peak1 - peak2) / peak1 < 0.02 and peaks[-1] - peaks[-2] > 5:
                valley = min(lows[-25:][peaks[-2]:peaks[-1]])
                target = valley - (peak1 - valley)
                
                return ChartPattern(
                    symbol=symbol,
                    pattern_type=PatternType.DOUBLE_TOP,
                    strength=PatternStrength.MODERATE,
                    direction="bearish",
                    current_price=current_price,
                    entry_price=valley * 0.998,
                    stop_loss=max(peak1, peak2) * 1.01,
                    target_price=target,
                    pattern_start=datetime.now(timezone.utc).isoformat(),
                    pattern_duration_days=20,
                    breakout_pending=current_price > valley,
                    risk_reward=self._calc_rr(valley, max(peak1, peak2), target),
                    pattern_score=65,
                    volume_confirmation=volumes[peaks[-1]] < volumes[peaks[-2]],
                    reasoning=[
                        f"Double top at ${(peak1+peak2)/2:.2f}",
                        f"Neckline support: ${valley:.2f}",
                        "Bearish reversal on breakdown"
                    ],
                    detected_at=datetime.now(timezone.utc).isoformat()
                )
        
        # Double bottom
        if len(troughs) >= 2:
            trough1 = lows[-25:][troughs[-2]]
            trough2 = lows[-25:][troughs[-1]]
            
            if abs(trough1 - trough2) / trough1 < 0.02 and troughs[-1] - troughs[-2] > 5:
                peak = max(highs[-25:][troughs[-2]:troughs[-1]])
                target = peak + (peak - trough1)
                
                return ChartPattern(
                    symbol=symbol,
                    pattern_type=PatternType.DOUBLE_BOTTOM,
                    strength=PatternStrength.MODERATE,
                    direction="bullish",
                    current_price=current_price,
                    entry_price=peak * 1.002,
                    stop_loss=min(trough1, trough2) * 0.99,
                    target_price=target,
                    pattern_start=datetime.now(timezone.utc).isoformat(),
                    pattern_duration_days=20,
                    breakout_pending=current_price < peak,
                    risk_reward=self._calc_rr(peak, min(trough1, trough2), target),
                    pattern_score=65,
                    volume_confirmation=volumes[troughs[-1]] > volumes[troughs[-2]],
                    reasoning=[
                        f"Double bottom at ${(trough1+trough2)/2:.2f}",
                        f"Neckline resistance: ${peak:.2f}",
                        "Bullish reversal on breakout"
                    ],
                    detected_at=datetime.now(timezone.utc).isoformat()
                )
        
        return None
    
    def _find_peaks(self, arr: np.ndarray, threshold: int = 3) -> List[int]:
        """Find local peaks in array"""
        peaks = []
        for i in range(threshold, len(arr) - threshold):
            if arr[i] == max(arr[i-threshold:i+threshold+1]):
                peaks.append(i)
        return peaks
    
    def _find_troughs(self, arr: np.ndarray, threshold: int = 3) -> List[int]:
        """Find local troughs in array"""
        troughs = []
        for i in range(threshold, len(arr) - threshold):
            if arr[i] == min(arr[i-threshold:i+threshold+1]):
                troughs.append(i)
        return troughs
    
    def _calc_rr(self, entry: float, stop: float, target: float) -> float:
        """Calculate risk/reward ratio"""
        risk = abs(entry - stop)
        reward = abs(target - entry)
        return round(reward / risk, 2) if risk > 0 else 0
    
    async def get_pattern_summary_for_ai(self, symbols: List[str]) -> str:
        """Generate pattern summary for AI assistant"""
        all_patterns = []
        
        for symbol in symbols[:5]:  # Limit to 5 symbols
            patterns = await self.detect_patterns(symbol)
            all_patterns.extend(patterns)
        
        if not all_patterns:
            return "No significant chart patterns detected."
        
        # Sort by score and take top 5
        all_patterns.sort(key=lambda x: x.pattern_score, reverse=True)
        top_patterns = all_patterns[:5]
        
        lines = ["**Chart Pattern Alerts**:"]
        for p in top_patterns:
            direction_emoji = "↗️" if p.direction == "bullish" else "↘️" if p.direction == "bearish" else "↔️"
            lines.append(f"- {p.symbol}: {p.pattern_type.value.replace('_', ' ').title()} {direction_emoji}")
            lines.append(f"  Entry: ${p.entry_price:.2f} | Target: ${p.target_price:.2f} | R:R {p.risk_reward}")
        
        return "\n".join(lines)


# Singleton instance
_pattern_service: Optional[ChartPatternService] = None


def get_chart_pattern_service() -> ChartPatternService:
    """Get or create the chart pattern service singleton"""
    global _pattern_service
    if _pattern_service is None:
        _pattern_service = ChartPatternService()
    return _pattern_service
