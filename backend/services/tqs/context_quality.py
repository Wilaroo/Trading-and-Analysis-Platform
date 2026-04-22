"""
Context Quality Service - 20% of TQS Score

Evaluates market context and timing:
- Market regime (trending vs choppy)
- Time of day optimization
- Sector strength/rotation
- VIX/Volatility regime
- Day of week patterns
"""

import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


@dataclass
class ContextQualityScore:
    """Result of context quality evaluation"""
    score: float = 50.0  # 0-100
    grade: str = "C"
    
    # Component scores (0-100 each)
    regime_score: float = 50.0
    time_score: float = 50.0
    sector_score: float = 50.0
    vix_score: float = 50.0
    day_score: float = 50.0
    
    # Raw values
    market_regime: str = "unknown"
    time_of_day: str = "midday"
    sector: str = "unknown"
    sector_rank: int = 6
    is_sector_leader: bool = False
    vix_level: float = 18.0
    day_of_week: int = 2  # Wednesday
    spy_change_pct: float = 0.0
    
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
                "regime": round(self.regime_score, 1),
                "time": round(self.time_score, 1),
                "sector": round(self.sector_score, 1),
                "vix": round(self.vix_score, 1),
                "day": round(self.day_score, 1)
            },
            "raw_values": {
                "market_regime": self.market_regime,
                "time_of_day": self.time_of_day,
                "sector": self.sector,
                "sector_rank": self.sector_rank,
                "is_sector_leader": self.is_sector_leader,
                "vix_level": round(self.vix_level, 1),
                "day_of_week": self.day_of_week,
                "spy_change_pct": round(self.spy_change_pct, 2)
            },
            "factors": self.factors
        }


class ContextQualityService:
    """Evaluates context quality - 20% of TQS"""
    
    # Setup performance by time of day (based on SMB research)
    TIME_SCORES = {
        "opening_auction": {"momentum": 85, "reversal": 40, "default": 60},
        "opening_drive": {"momentum": 95, "reversal": 45, "default": 75},
        "morning_momentum": {"momentum": 90, "reversal": 60, "default": 80},
        "late_morning": {"momentum": 70, "reversal": 75, "default": 70},
        "midday": {"momentum": 40, "reversal": 60, "default": 45},
        "afternoon": {"momentum": 65, "reversal": 70, "default": 65},
        "close": {"momentum": 55, "reversal": 50, "default": 55},
        "pre_market": {"momentum": 50, "reversal": 35, "default": 40},
        "after_hours": {"momentum": 30, "reversal": 25, "default": 25}
    }
    
    # Setup performance by regime
    REGIME_SCORES = {
        "strong_uptrend": {"long": 90, "short": 25},
        "weak_uptrend": {"long": 75, "short": 45},
        "range_bound": {"long": 55, "short": 55},
        "weak_downtrend": {"long": 45, "short": 75},
        "strong_downtrend": {"long": 25, "short": 90},
        "volatile": {"long": 50, "short": 50},
        "unknown": {"long": 50, "short": 50}
    }
    
    def __init__(self):
        self._alpaca_service = None
        self._sector_service = None
        self._ib_service = None
        
    def set_services(self, alpaca_service=None, sector_service=None, ib_service=None):
        """Wire up dependencies"""
        self._alpaca_service = alpaca_service
        self._sector_service = sector_service
        self._ib_service = ib_service
        
    async def calculate_score(
        self,
        symbol: str,
        direction: str = "long",
        setup_type: str = "",
        # Pre-fetched context (optional)
        market_regime: Optional[str] = None,
        spy_change_pct: Optional[float] = None,
        vix_level: Optional[float] = None,
        sector: Optional[str] = None,
        sector_rank: Optional[int] = None,
        is_sector_leader: Optional[bool] = None,
        time_of_day: Optional[str] = None,
        # AI model signals (from Confidence Gate pipeline)
        ai_model_direction: Optional[str] = None,  # "up", "down", "flat"
        ai_model_confidence: Optional[float] = None,  # 0.0-1.0
        ai_model_agrees: Optional[bool] = None,  # Does AI agree with trade direction?
    ) -> ContextQualityScore:
        """
        Calculate context quality score (0-100).
        
        Components:
        - Market regime fit (25%): Setup matches market conditions
        - Time of day (20%): Optimal trading window
        - Sector context (20%): Sector strength alignment
        - VIX regime (15%): Volatility environment
        - AI model alignment (10%): ML models agree with direction
        - Day of week (10%): Historical patterns
        """
        result = ContextQualityScore()
        is_long = direction.lower() == "long"
        
        # Determine setup category
        setup_lower = setup_type.lower()
        if any(s in setup_lower for s in ["breakout", "momentum", "drive", "orb", "flag"]):
            setup_category = "momentum"
        elif any(s in setup_lower for s in ["reversal", "bounce", "fade", "rubber"]):
            setup_category = "reversal"
        else:
            setup_category = "default"
            
        # Get current time info
        now = datetime.now(ZoneInfo("America/New_York"))  # ET
        result.day_of_week = now.weekday()
        
        # Determine time of day if not provided
        if time_of_day is None:
            hour = now.hour
            minute = now.minute
            time_minutes = hour * 60 + minute
            
            if time_minutes < 9 * 60 + 30:
                time_of_day = "pre_market"
            elif time_minutes < 9 * 60 + 35:
                time_of_day = "opening_auction"
            elif time_minutes < 10 * 60:
                time_of_day = "opening_drive"
            elif time_minutes < 11 * 60:
                time_of_day = "morning_momentum"
            elif time_minutes < 12 * 60:
                time_of_day = "late_morning"
            elif time_minutes < 14 * 60:
                time_of_day = "midday"
            elif time_minutes < 15 * 60 + 30:
                time_of_day = "afternoon"
            elif time_minutes < 16 * 60:
                time_of_day = "close"
            else:
                time_of_day = "after_hours"
                
        result.time_of_day = time_of_day
        
        # Fetch market data if not provided
        if self._alpaca_service and (spy_change_pct is None or market_regime is None):
            try:
                quotes = await self._alpaca_service.get_quotes_batch(["SPY"])
                if "SPY" in quotes:
                    spy_change_pct = quotes["SPY"].get("change_percent", 0)
            except Exception as e:
                logger.debug(f"Could not fetch SPY data: {e}")
                
        # Get VIX from IB pushed data or service
        if vix_level is None:
            try:
                # Try pushed data first (most reliable)
                from routers.ib import get_vix_from_pushed_data
                vix_data = get_vix_from_pushed_data()
                if vix_data and vix_data.get("price"):
                    vix_level = vix_data.get("price")
            except Exception:
                pass
            
            # Fallback to IB service
            if vix_level is None and self._ib_service:
                try:
                    vix_data = self._ib_service.get_vix()
                    if vix_data:
                        vix_level = vix_data.get("price", 18)
                except Exception:
                    pass
                
        # Fetch sector data if not provided
        if self._sector_service and (sector is None or sector_rank is None):
            try:
                sector_context = await self._sector_service.get_stock_sector_context(symbol)
                if sector_context:
                    sector = sector_context.get("sector", "unknown")
                    sector_rank = sector_context.get("sector_rank", 6)
                    is_sector_leader = sector_context.get("is_sector_leader", False)
            except Exception as e:
                logger.debug(f"Could not fetch sector data: {e}")
                
        # Use defaults
        spy_change_pct = spy_change_pct if spy_change_pct is not None else 0.0
        vix_level = vix_level if vix_level is not None else 18.0
        sector = sector if sector else "unknown"
        sector_rank = sector_rank if sector_rank is not None else 6
        is_sector_leader = is_sector_leader if is_sector_leader is not None else False
        
        # Classify market regime from SPY change
        if market_regime is None:
            if spy_change_pct >= 1.0:
                market_regime = "strong_uptrend"
            elif spy_change_pct >= 0.3:
                market_regime = "weak_uptrend"
            elif spy_change_pct <= -1.0:
                market_regime = "strong_downtrend"
            elif spy_change_pct <= -0.3:
                market_regime = "weak_downtrend"
            else:
                market_regime = "range_bound"
                
        result.market_regime = market_regime
        result.spy_change_pct = spy_change_pct
        result.vix_level = vix_level
        result.sector = sector
        result.sector_rank = sector_rank
        result.is_sector_leader = is_sector_leader
        
        # 1. Market Regime Score (30% weight)
        regime_scores = self.REGIME_SCORES.get(market_regime, {"long": 50, "short": 50})
        result.regime_score = regime_scores["long" if is_long else "short"]
        
        if is_long and market_regime == "strong_uptrend":
            result.factors.append(f"Strong uptrend (SPY +{spy_change_pct:.1f}%) favors longs (++)")
        elif is_long and market_regime == "strong_downtrend":
            result.factors.append(f"Strong downtrend (SPY {spy_change_pct:.1f}%) against longs (--)")
        elif not is_long and market_regime == "strong_downtrend":
            result.factors.append(f"Strong downtrend (SPY {spy_change_pct:.1f}%) favors shorts (++)")
        elif not is_long and market_regime == "strong_uptrend":
            result.factors.append(f"Strong uptrend (SPY +{spy_change_pct:.1f}%) against shorts (--)")
        elif market_regime == "range_bound":
            result.factors.append("Range-bound market - favor mean reversion")
            
        # 2. Time of Day Score (25% weight)
        time_scores = self.TIME_SCORES.get(time_of_day, {"default": 50})
        result.time_score = time_scores.get(setup_category, time_scores.get("default", 50))
        
        if time_of_day == "opening_drive" and setup_category == "momentum":
            result.factors.append("Opening drive - optimal for momentum setups (+)")
        elif time_of_day == "midday":
            result.factors.append("Midday lull - reduced edge (-)")
        elif time_of_day == "morning_momentum":
            result.factors.append("Morning momentum window (+)")
            
        # 3. Sector Score (20% weight)
        # Sector rank 1-3 is hot, 9-11 is cold
        if is_long:
            if is_sector_leader:
                result.sector_score = 95
                result.factors.append(f"{sector} sector leader (++)")
            elif sector_rank <= 3:
                result.sector_score = 85
                result.factors.append(f"{sector} in top 3 sectors (+)")
            elif sector_rank <= 5:
                result.sector_score = 70
            elif sector_rank <= 7:
                result.sector_score = 50
            elif sector_rank <= 9:
                result.sector_score = 35
            else:
                result.sector_score = 25
                result.factors.append(f"{sector} in bottom sectors (-)")
        else:  # short
            if sector_rank >= 9:
                result.sector_score = 85
                result.factors.append(f"{sector} weak sector - favors shorts (+)")
            elif sector_rank >= 7:
                result.sector_score = 70
            elif sector_rank >= 5:
                result.sector_score = 55
            else:
                result.sector_score = 40
                result.factors.append(f"{sector} strong sector - shorts harder (-)")
                
        # 4. VIX Score (15% weight)
        # VIX 15-22 is ideal, very high or very low is challenging
        if 15 <= vix_level <= 22:
            result.vix_score = 85
            result.factors.append(f"VIX {vix_level:.1f} - normal volatility (+)")
        elif 12 <= vix_level < 15:
            result.vix_score = 70
            result.factors.append(f"VIX {vix_level:.1f} - low volatility")
        elif 22 < vix_level <= 28:
            result.vix_score = 65
            result.factors.append(f"VIX {vix_level:.1f} - elevated volatility")
        elif vix_level < 12:
            result.vix_score = 50
            result.factors.append(f"VIX {vix_level:.1f} - very low, expect choppy action (-)")
        elif 28 < vix_level <= 35:
            result.vix_score = 45
            result.factors.append(f"VIX {vix_level:.1f} - high volatility, reduce size (-)")
        else:  # > 35
            result.vix_score = 30
            result.factors.append(f"VIX {vix_level:.1f} - extreme volatility, high risk (--)")
            
        # 5. Day of Week Score (10% weight)
        # Tuesday-Thursday typically best, Monday/Friday more random
        day_scores = {
            0: 55,  # Monday - weekend gap risk
            1: 75,  # Tuesday - good
            2: 80,  # Wednesday - best
            3: 75,  # Thursday - good
            4: 50   # Friday - EOW positioning
        }
        result.day_score = day_scores.get(result.day_of_week, 60)
        
        if result.day_of_week == 2:
            result.factors.append("Wednesday - historically best trading day (+)")
        elif result.day_of_week == 4:
            result.factors.append("Friday - EOW effects may impact")
        
        # 6. AI Model Alignment Score (10% weight)
        # Does the ML model agree with the proposed trade direction?
        # MODE-C calibration (2026-04-23): 3-class setup-specific LONG models
        # peak at 0.44-0.53 conf on triple-barrier data. An UP argmax at 0.50
        # is a real edge — bucket agreement at >=0.50 into CONFIRMS, not leans.
        ai_score = 50  # Neutral default (no model data)
        CONFIRMS_THRESHOLD = 0.50
        if ai_model_agrees is not None and ai_model_confidence is not None:
            if ai_model_agrees and ai_model_confidence >= CONFIRMS_THRESHOLD:
                ai_score = 90
                result.factors.append(f"AI model CONFIRMS {direction} ({ai_model_confidence:.0%} conf) (++)")
            elif ai_model_agrees:
                ai_score = 70
                result.factors.append(f"AI model leans {direction} ({ai_model_confidence:.0%} conf) (+)")
            elif ai_model_direction == "flat":
                ai_score = 45
                result.factors.append(f"AI model sees no edge (flat) (-)")
            elif not ai_model_agrees and ai_model_confidence >= 0.60:
                ai_score = 20
                result.factors.append(f"AI model DISAGREES — predicts {ai_model_direction} ({ai_model_confidence:.0%} conf) (--)")
            else:
                ai_score = 35
                result.factors.append(f"AI model weakly disagrees (-)")
            
        # Calculate weighted total (updated weights to include AI alignment)
        result.score = (
            result.regime_score * 0.25 +
            result.time_score * 0.20 +
            result.sector_score * 0.20 +
            result.vix_score * 0.15 +
            ai_score * 0.10 +
            result.day_score * 0.10
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
_context_quality_service: Optional[ContextQualityService] = None


def get_context_quality_service() -> ContextQualityService:
    global _context_quality_service
    if _context_quality_service is None:
        _context_quality_service = ContextQualityService()
    return _context_quality_service
