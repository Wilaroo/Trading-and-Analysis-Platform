"""
Technical Quality Service - 25% of TQS Score

Evaluates technical indicators and price action:
- Trend alignment (MA stack)
- RSI position (overbought/oversold/neutral)
- Support/Resistance proximity
- ATR-based volatility assessment
- Relative Volume (RVOL)
- Squeeze status
"""

import logging
from typing import Optional, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TechnicalQualityScore:
    """Result of technical quality evaluation"""
    score: float = 50.0  # 0-100
    grade: str = "C"
    
    # Component scores (0-100 each)
    trend_score: float = 50.0
    rsi_score: float = 50.0
    levels_score: float = 50.0
    volatility_score: float = 50.0
    volume_score: float = 50.0
    
    # Raw values
    ma_stack: str = "neutral"  # bullish/bearish/neutral
    rsi: float = 50.0
    atr_percent: float = 2.0
    rvol: float = 1.0
    vwap_distance_pct: float = 0.0
    squeeze_active: bool = False
    
    # Reasoning
    factors: list = None
    
    def __post_init__(self):
        if self.factors is None:
            self.factors = []
    
    def to_dict(self) -> Dict:
        return {
            "score": round(self.score, 1),
            "grade": self.grade,
            "components": {
                "trend": round(self.trend_score, 1),
                "rsi": round(self.rsi_score, 1),
                "levels": round(self.levels_score, 1),
                "volatility": round(self.volatility_score, 1),
                "volume": round(self.volume_score, 1)
            },
            "raw_values": {
                "ma_stack": self.ma_stack,
                "rsi": round(self.rsi, 1),
                "atr_percent": round(self.atr_percent, 2),
                "rvol": round(self.rvol, 2),
                "vwap_distance_pct": round(self.vwap_distance_pct, 2),
                "squeeze_active": self.squeeze_active
            },
            "factors": self.factors
        }


class TechnicalQualityService:
    """Evaluates technical quality - 25% of TQS"""
    
    def __init__(self):
        self._technical_service = None
        self._alpaca_service = None
        
    def set_services(self, technical_service=None, alpaca_service=None):
        """Wire up dependencies"""
        self._technical_service = technical_service
        self._alpaca_service = alpaca_service
        
    async def calculate_score(
        self,
        symbol: str,
        direction: str = "long",
        setup_type: str = "",
        # Pre-fetched data (optional, will fetch if not provided)
        rsi: Optional[float] = None,
        ma_stack: Optional[str] = None,
        atr_percent: Optional[float] = None,
        rvol: Optional[float] = None,
        vwap_distance_pct: Optional[float] = None,
        support_distance_pct: Optional[float] = None,
        resistance_distance_pct: Optional[float] = None,
        squeeze_active: Optional[bool] = None
    ) -> TechnicalQualityScore:
        """
        Calculate technical quality score (0-100).
        
        Components:
        - Trend alignment (25%): MA stack matches direction
        - RSI position (20%): Not overbought/oversold counter-trend
        - S/R proximity (20%): Near support for longs, resistance for shorts
        - Volatility (15%): Not too low (no movement) or too high (risky)
        - Volume (20%): RVOL indicates interest
        """
        result = TechnicalQualityScore()
        is_long = direction.lower() == "long"
        
        # Fetch technical data if not provided
        if self._technical_service and any(v is None for v in [rsi, ma_stack, atr_percent, rvol]):
            try:
                snapshot = await self._technical_service.get_technical_snapshot(symbol)
                if snapshot:
                    # TechnicalSnapshot is a dataclass, access attributes directly
                    rsi = rsi if rsi is not None else getattr(snapshot, "rsi_14", 50)
                    atr_percent = atr_percent if atr_percent is not None else getattr(snapshot, "atr_percent", 2.0)
                    rvol = rvol if rvol is not None else getattr(snapshot, "rvol", 1.0)
                    vwap_distance_pct = vwap_distance_pct if vwap_distance_pct is not None else getattr(snapshot, "dist_from_vwap", 0)
                    
                    # MA stack from moving averages
                    ema20 = getattr(snapshot, "ema_20", 0)
                    ema50 = getattr(snapshot, "ema_50", 0)
                    sma200 = getattr(snapshot, "sma_200", 0)
                    if ema20 > ema50 > sma200:
                        ma_stack = "bullish"
                    elif ema20 < ema50 < sma200:
                        ma_stack = "bearish"
                    else:
                        ma_stack = "neutral"
                    
                    squeeze_active = squeeze_active if squeeze_active is not None else getattr(snapshot, "squeeze_on", False)
                    
                    # Calculate distance percentages from levels
                    price = getattr(snapshot, "current_price", 0)
                    support = getattr(snapshot, "support", 0)
                    resistance = getattr(snapshot, "resistance", 0)
                    if price > 0 and support > 0:
                        support_distance_pct = support_distance_pct if support_distance_pct is not None else ((price - support) / price) * 100
                    if price > 0 and resistance > 0:
                        resistance_distance_pct = resistance_distance_pct if resistance_distance_pct is not None else ((resistance - price) / price) * 100
            except Exception as e:
                logger.debug(f"Could not fetch technicals for {symbol}: {e}")
                
        # Use defaults if still None
        rsi = rsi if rsi is not None else 50.0
        ma_stack = ma_stack if ma_stack is not None else "neutral"
        atr_percent = atr_percent if atr_percent is not None else 2.0
        rvol = rvol if rvol is not None else 1.0
        vwap_distance_pct = vwap_distance_pct if vwap_distance_pct is not None else 0.0
        support_distance_pct = support_distance_pct if support_distance_pct is not None else 5.0
        resistance_distance_pct = resistance_distance_pct if resistance_distance_pct is not None else 5.0
        squeeze_active = squeeze_active if squeeze_active is not None else False
        
        result.rsi = rsi
        result.ma_stack = ma_stack
        result.atr_percent = atr_percent
        result.rvol = rvol
        result.vwap_distance_pct = vwap_distance_pct
        result.squeeze_active = squeeze_active
        
        # 1. Trend Alignment Score (25% weight)
        if is_long:
            if ma_stack == "bullish":
                result.trend_score = 90
                result.factors.append("Bullish MA stack supports long (+)")
            elif ma_stack == "neutral":
                result.trend_score = 60
            else:  # bearish
                result.trend_score = 25
                result.factors.append("Bearish MA stack against long direction (-)")
        else:  # short
            if ma_stack == "bearish":
                result.trend_score = 90
                result.factors.append("Bearish MA stack supports short (+)")
            elif ma_stack == "neutral":
                result.trend_score = 60
            else:  # bullish
                result.trend_score = 25
                result.factors.append("Bullish MA stack against short direction (-)")
                
        # Squeeze bonus
        if squeeze_active:
            result.trend_score = min(100, result.trend_score + 10)
            result.factors.append("Squeeze active - potential breakout (+)")
            
        # 2. RSI Score (20% weight)
        # For longs: want RSI 30-60 (not overbought)
        # For shorts: want RSI 40-70 (not oversold)
        if is_long:
            if 30 <= rsi <= 50:
                result.rsi_score = 90  # Oversold bouncing
                result.factors.append(f"RSI {rsi:.0f} - good entry for long (+)")
            elif 50 < rsi <= 65:
                result.rsi_score = 75  # Momentum
            elif 65 < rsi <= 75:
                result.rsi_score = 50  # Getting extended
                result.factors.append(f"RSI {rsi:.0f} - getting extended")
            elif rsi > 75:
                result.rsi_score = 25  # Overbought
                result.factors.append(f"RSI {rsi:.0f} - overbought (-)")
            else:  # < 30
                result.rsi_score = 70  # Very oversold, reversal candidate
        else:  # short
            if 50 <= rsi <= 70:
                result.rsi_score = 90  # Overbought fading
                result.factors.append(f"RSI {rsi:.0f} - good entry for short (+)")
            elif 35 <= rsi < 50:
                result.rsi_score = 75  # Momentum down
            elif 25 <= rsi < 35:
                result.rsi_score = 50  # Getting oversold
            elif rsi < 25:
                result.rsi_score = 25  # Too oversold
                result.factors.append(f"RSI {rsi:.0f} - oversold, risky short (-)")
            else:  # > 70
                result.rsi_score = 70
                
        # 3. S/R Proximity Score (20% weight)
        if is_long:
            # Want to be near support for longs
            if support_distance_pct <= 1.0:
                result.levels_score = 95
                result.factors.append(f"Near support ({support_distance_pct:.1f}% away) (+)")
            elif support_distance_pct <= 2.0:
                result.levels_score = 80
            elif support_distance_pct <= 3.0:
                result.levels_score = 65
            elif support_distance_pct <= 5.0:
                result.levels_score = 50
            else:
                result.levels_score = 35
                
            # Penalize if too close to resistance
            if resistance_distance_pct <= 1.0:
                result.levels_score = max(20, result.levels_score - 30)
                result.factors.append(f"Near resistance ({resistance_distance_pct:.1f}% away) - limited upside (-)")
        else:  # short
            # Want to be near resistance for shorts
            if resistance_distance_pct <= 1.0:
                result.levels_score = 95
                result.factors.append(f"Near resistance ({resistance_distance_pct:.1f}% away) (+)")
            elif resistance_distance_pct <= 2.0:
                result.levels_score = 80
            elif resistance_distance_pct <= 3.0:
                result.levels_score = 65
            else:
                result.levels_score = 50
                
        # VWAP consideration
        if is_long and vwap_distance_pct < -1.0:
            result.levels_score = min(100, result.levels_score + 10)
            result.factors.append(f"Below VWAP ({vwap_distance_pct:.1f}%) - value area (+)")
        elif not is_long and vwap_distance_pct > 1.0:
            result.levels_score = min(100, result.levels_score + 10)
            result.factors.append(f"Above VWAP ({vwap_distance_pct:.1f}%) - fade candidate (+)")
            
        # 4. Volatility Score (15% weight)
        # ATR% of 1-3% is ideal for most setups
        if 1.5 <= atr_percent <= 3.0:
            result.volatility_score = 85
            result.factors.append(f"ATR {atr_percent:.1f}% - good volatility (+)")
        elif 1.0 <= atr_percent < 1.5:
            result.volatility_score = 70
        elif 3.0 < atr_percent <= 4.5:
            result.volatility_score = 65
        elif 0.5 <= atr_percent < 1.0:
            result.volatility_score = 45
            result.factors.append(f"ATR {atr_percent:.1f}% - low volatility (-)")
        elif atr_percent > 4.5:
            result.volatility_score = 40
            result.factors.append(f"ATR {atr_percent:.1f}% - high volatility, risky (-)")
        else:
            result.volatility_score = 30
            
        # Adjust for setup type
        if "scalp" in setup_type.lower() and atr_percent > 2.0:
            result.volatility_score = min(100, result.volatility_score + 10)
        if "swing" in setup_type.lower() and atr_percent < 1.5:
            result.volatility_score = max(0, result.volatility_score - 10)
            
        # 5. Volume Score (20% weight)
        # RVOL > 1.5 is good, > 2.5 is excellent
        if rvol >= 3.0:
            result.volume_score = 100
            result.factors.append(f"RVOL {rvol:.1f}x - very high interest (++)")
        elif rvol >= 2.0:
            result.volume_score = 90
            result.factors.append(f"RVOL {rvol:.1f}x - strong interest (+)")
        elif rvol >= 1.5:
            result.volume_score = 75
            result.factors.append(f"RVOL {rvol:.1f}x - above average (+)")
        elif rvol >= 1.0:
            result.volume_score = 60
        elif rvol >= 0.7:
            result.volume_score = 40
            result.factors.append(f"RVOL {rvol:.1f}x - below average (-)")
        else:
            result.volume_score = 25
            result.factors.append(f"RVOL {rvol:.1f}x - low volume (-)")
            
        # Calculate weighted total
        result.score = (
            result.trend_score * 0.25 +
            result.rsi_score * 0.20 +
            result.levels_score * 0.20 +
            result.volatility_score * 0.15 +
            result.volume_score * 0.20
        )
        
        # Assign grade
        if result.score >= 85:
            result.grade = "A"
        elif result.score >= 75:
            result.grade = "B+"
        elif result.score >= 65:
            result.grade = "B"
        elif result.score >= 55:
            result.grade = "C+"
        elif result.score >= 45:
            result.grade = "C"
        elif result.score >= 35:
            result.grade = "D"
        else:
            result.grade = "F"
            
        return result


# Singleton
_technical_quality_service: Optional[TechnicalQualityService] = None


def get_technical_quality_service() -> TechnicalQualityService:
    global _technical_quality_service
    if _technical_quality_service is None:
        _technical_quality_service = TechnicalQualityService()
    return _technical_quality_service
