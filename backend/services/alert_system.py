"""
Advanced Trade Alert System
Organizes alerts by timeframe (Scalp, Intraday, Swing, Position)
with adjusted scoring weights and detailed reasoning.

Features:
- Breakout & Short Squeeze scan criteria
- "In Play" stock qualification
- Timeframe-specific scoring (less fundamentals for scalps, more for swing/position)
- Organized alert categories with reasoning
- Morning/EOD swing alerts
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import math

logger = logging.getLogger(__name__)


class AlertTimeframe(str, Enum):
    """Trade timeframe categories"""
    SCALP = "scalp"              # Minutes to 1 hour
    INTRADAY = "intraday"        # Same day
    SWING = "swing"             # Days to weeks
    POSITION = "position"        # Weeks to months


class AlertUrgency(str, Enum):
    """Alert urgency/timing"""
    SETTING_UP_NOW = "setting_up_now"           # Scalp: Ready now
    ON_WATCH_TODAY = "on_watch_today"           # Scalp: Later today
    SETTING_UP_TODAY = "setting_up_today"       # Swing: Today
    SETTING_UP_THIS_WEEK = "setting_up_this_week"  # Swing: This week


class InPlayReason(str, Enum):
    """Why a stock qualifies as "in play" """
    HIGH_RVOL = "high_relative_volume"
    GAPPING = "gapping_up_or_down"
    NEWS_CATALYST = "news_catalyst"
    EARNINGS = "earnings_related"
    BREAKING_LEVELS = "breaking_key_levels"
    UNUSUAL_OPTIONS = "unusual_options_activity"
    SECTOR_MOMENTUM = "sector_momentum"
    SHORT_SQUEEZE = "short_squeeze_setup"


@dataclass
class InPlayQualification:
    """Whether a stock qualifies as 'in play' for scalping/intraday"""
    is_in_play: bool
    score: int  # 0-100
    reasons: List[str]
    disqualifiers: List[str]
    
    # Key metrics
    rvol: float
    gap_pct: float
    atr_pct: float
    float_shares: Optional[float]
    short_interest: Optional[float]
    has_catalyst: bool


@dataclass
class AlertReasoning:
    """Detailed reasoning for why an alert was generated"""
    summary: str
    technical_reasons: List[str]
    fundamental_reasons: List[str]
    catalyst_reasons: List[str]
    risk_factors: List[str]
    key_levels: Dict[str, float]
    trade_plan: Dict[str, Any]


@dataclass
class OrganizedAlert:
    """A fully organized alert with timeframe and urgency"""
    id: str
    symbol: str
    setup_type: str
    direction: str  # "long" or "short"
    
    # Timeframe classification
    timeframe: AlertTimeframe
    urgency: AlertUrgency
    
    # In-play qualification (for scalp/intraday)
    in_play: Optional[InPlayQualification]
    
    # Scores (adjusted by timeframe)
    overall_score: int
    technical_score: int
    fundamental_score: int
    catalyst_score: int
    regime_score: int
    
    # Probabilities
    trigger_probability: float
    win_probability: float
    expected_value: float
    risk_reward: float
    
    # Trade details
    current_price: float
    entry_zone: Tuple[float, float]
    stop_loss: float
    target_1: float
    target_2: Optional[float]
    target_3: Optional[float]  # For swing/position
    
    # Timing
    estimated_trigger_time: str
    minutes_to_trigger: int
    
    # Reasoning
    reasoning: AlertReasoning
    
    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: Optional[str] = None
    status: str = "active"


# ==================== SCORING WEIGHTS BY TIMEFRAME ====================

TIMEFRAME_WEIGHTS = {
    AlertTimeframe.SCALP: {
        "technical": 0.50,      # Heavy technical focus
        "fundamental": 0.05,    # Minimal fundamental weight
        "catalyst": 0.25,       # News/catalyst important for movement
        "volume": 0.15,         # Volume crucial for scalps
        "regime": 0.05,         # Less regime weight
    },
    AlertTimeframe.INTRADAY: {
        "technical": 0.45,
        "fundamental": 0.10,
        "catalyst": 0.25,
        "volume": 0.12,
        "regime": 0.08,
    },
    AlertTimeframe.SWING: {
        "technical": 0.30,
        "fundamental": 0.25,    # More fundamental weight
        "catalyst": 0.20,
        "volume": 0.08,
        "regime": 0.17,         # Regime trends matter more
    },
    AlertTimeframe.POSITION: {
        "technical": 0.20,
        "fundamental": 0.35,    # Heavy fundamental weight
        "catalyst": 0.15,
        "volume": 0.05,
        "regime": 0.25,         # Longer-term trends crucial
    },
}

# ==================== IN PLAY CRITERIA ====================

IN_PLAY_CRITERIA = {
    "min_rvol": 2.0,           # Minimum relative volume
    "min_gap_pct": 3.0,        # Gap to qualify
    "min_atr_pct": 1.5,        # Minimum daily range
    "max_spread_pct": 0.3,     # Max bid-ask spread
    "min_volume": 500000,      # Minimum daily volume
}

# ==================== SETUP TYPES ====================

SCALP_SETUP_TYPES = {
    "rubber_band_scalp_long": {
        "name": "Rubber Band Scalp Long",
        "description": "Mean reversion long - price snapping back to 9 EMA",
        "min_rvol": 1.5,
        "base_win_rate": 0.62,
        "avg_hold_time_mins": 15,
    },
    "rubber_band_scalp_short": {
        "name": "Rubber Band Scalp Short", 
        "description": "Mean reversion short - price snapping back to 9 EMA",
        "min_rvol": 1.5,
        "base_win_rate": 0.58,
        "avg_hold_time_mins": 15,
    },
    "vwap_reclaim_long": {
        "name": "VWAP Reclaim Long",
        "description": "Price reclaiming VWAP with volume",
        "min_rvol": 2.0,
        "base_win_rate": 0.60,
        "avg_hold_time_mins": 20,
    },
    "vwap_rejection_short": {
        "name": "VWAP Rejection Short",
        "description": "Price rejected at VWAP",
        "min_rvol": 2.0,
        "base_win_rate": 0.58,
        "avg_hold_time_mins": 20,
    },
    "breakout_scalp": {
        "name": "Breakout Scalp",
        "description": "Breaking intraday resistance with volume surge",
        "min_rvol": 3.0,
        "base_win_rate": 0.55,
        "avg_hold_time_mins": 10,
    },
    "breakdown_scalp": {
        "name": "Breakdown Scalp",
        "description": "Breaking intraday support with volume",
        "min_rvol": 3.0,
        "base_win_rate": 0.53,
        "avg_hold_time_mins": 10,
    },
    "opening_range_breakout": {
        "name": "Opening Range Breakout (ORB)",
        "description": "Breaking first 15-min range",
        "min_rvol": 2.5,
        "base_win_rate": 0.54,
        "avg_hold_time_mins": 30,
    },
    "red_to_green_move": {
        "name": "Red to Green Move",
        "description": "Stock opens red, reverses green",
        "min_rvol": 2.0,
        "base_win_rate": 0.58,
        "avg_hold_time_mins": 25,
    },
}

INTRADAY_SETUP_TYPES = {
    "gap_and_go": {
        "name": "Gap and Go",
        "description": "Gap up continuation with strong volume",
        "min_rvol": 3.0,
        "min_gap_pct": 4.0,
        "base_win_rate": 0.52,
    },
    "gap_fade": {
        "name": "Gap Fade",
        "description": "Fading extended gap",
        "min_rvol": 2.0,
        "min_gap_pct": 5.0,
        "base_win_rate": 0.50,
    },
    "momentum_continuation": {
        "name": "Momentum Continuation",
        "description": "Strong trend continuation intraday",
        "min_rvol": 2.5,
        "base_win_rate": 0.55,
    },
    "short_squeeze_intraday": {
        "name": "Short Squeeze (Intraday)",
        "description": "Shorts getting squeezed - high SI + upward pressure",
        "min_short_interest": 15.0,
        "min_rvol": 4.0,
        "base_win_rate": 0.58,
    },
}

SWING_SETUP_TYPES = {
    "breakout_swing": {
        "name": "Breakout (Swing)",
        "description": "Breaking multi-day resistance on volume",
        "min_rvol": 2.0,
        "base_win_rate": 0.55,
        "hold_days": "3-10",
    },
    "bull_flag_swing": {
        "name": "Bull Flag (Swing)",
        "description": "Consolidation after strong move up",
        "base_win_rate": 0.60,
        "hold_days": "5-15",
    },
    "cup_and_handle": {
        "name": "Cup and Handle",
        "description": "Classic bullish continuation pattern",
        "base_win_rate": 0.62,
        "hold_days": "10-30",
    },
    "short_squeeze_swing": {
        "name": "Short Squeeze (Swing)",
        "description": "Building short squeeze over days",
        "min_short_interest": 20.0,
        "base_win_rate": 0.55,
        "hold_days": "3-14",
    },
    "earnings_momentum": {
        "name": "Earnings Momentum",
        "description": "Post-earnings drift continuation",
        "base_win_rate": 0.58,
        "hold_days": "5-20",
    },
    "sector_rotation": {
        "name": "Sector Rotation Play",
        "description": "Riding sector momentum",
        "base_win_rate": 0.55,
        "hold_days": "5-15",
    },
}

POSITION_SETUP_TYPES = {
    "accumulation_breakout": {
        "name": "Accumulation Breakout",
        "description": "Breaking out of accumulation zone",
        "base_win_rate": 0.60,
        "hold_weeks": "4-12",
    },
    "value_turnaround": {
        "name": "Value Turnaround",
        "description": "Undervalued stock showing reversal signs",
        "base_win_rate": 0.55,
        "hold_weeks": "8-24",
    },
    "growth_momentum": {
        "name": "Growth Momentum",
        "description": "Strong growth stock with momentum",
        "base_win_rate": 0.58,
        "hold_weeks": "8-20",
    },
}


class AdvancedAlertSystem:
    """
    Advanced alert system with timeframe organization
    and detailed reasoning.
    """
    
    def __init__(self, db=None):
        self.db = db
        
        # Organized alerts by category
        self._scalp_alerts_now: List[OrganizedAlert] = []
        self._scalp_alerts_watch: List[OrganizedAlert] = []
        self._swing_alerts_today: List[OrganizedAlert] = []
        self._swing_alerts_week: List[OrganizedAlert] = []
        self._position_alerts: List[OrganizedAlert] = []
        
        # Services (lazy loaded)
        self._alpaca_service = None
        self._fundamental_service = None
        self._news_service = None
        
        if db:
            self.alerts_collection = db["organized_alerts"]
    
    @property
    def alpaca_service(self):
        if self._alpaca_service is None:
            from services.alpaca_service import AlpacaService
            self._alpaca_service = AlpacaService()
        return self._alpaca_service
    
    @property
    def fundamental_service(self):
        if self._fundamental_service is None:
            from services.fundamental_data_service import get_fundamental_data_service
            self._fundamental_service = get_fundamental_data_service()
        return self._fundamental_service
    
    # ==================== IN PLAY QUALIFICATION ====================
    
    async def check_in_play(self, symbol: str, market_data: Dict) -> InPlayQualification:
        """
        Check if a stock qualifies as "in play" for scalping/intraday.
        A stock is in play if it has unusual activity that creates opportunity.
        """
        reasons = []
        disqualifiers = []
        score = 0
        
        rvol = market_data.get("rvol", 1.0)
        gap_pct = market_data.get("gap_pct", 0)
        atr_pct = market_data.get("atr_pct", 1.0)
        spread_pct = market_data.get("spread_pct", 0.1)
        volume = market_data.get("volume", 0)
        has_catalyst = market_data.get("has_catalyst", False)
        short_interest = market_data.get("short_interest")
        float_shares = market_data.get("float_shares")
        
        # Check RVOL (most important)
        if rvol >= 5.0:
            score += 35
            reasons.append(f"🔥 Exceptional volume (RVOL: {rvol:.1f}x) - Very active")
        elif rvol >= 3.0:
            score += 25
            reasons.append(f"High volume (RVOL: {rvol:.1f}x)")
        elif rvol >= IN_PLAY_CRITERIA["min_rvol"]:
            score += 15
            reasons.append(f"Above average volume (RVOL: {rvol:.1f}x)")
        else:
            disqualifiers.append(f"Low relative volume ({rvol:.1f}x) - Not in play")
        
        # Check gap
        if abs(gap_pct) >= 8.0:
            score += 25
            reasons.append(f"🚀 Large gap {'up' if gap_pct > 0 else 'down'} ({gap_pct:+.1f}%)")
        elif abs(gap_pct) >= IN_PLAY_CRITERIA["min_gap_pct"]:
            score += 15
            reasons.append(f"Gapping {'up' if gap_pct > 0 else 'down'} ({gap_pct:+.1f}%)")
        
        # Check ATR/Range
        if atr_pct >= 3.0:
            score += 15
            reasons.append(f"High daily range ({atr_pct:.1f}%) - Good for scalping")
        elif atr_pct >= IN_PLAY_CRITERIA["min_atr_pct"]:
            score += 8
            reasons.append(f"Decent range ({atr_pct:.1f}%)")
        else:
            disqualifiers.append(f"Tight range ({atr_pct:.1f}%) - Difficult to scalp")
        
        # Check spread
        if spread_pct > IN_PLAY_CRITERIA["max_spread_pct"]:
            score -= 10
            disqualifiers.append(f"Wide spread ({spread_pct:.2f}%) - Hurts entries/exits")
        
        # Check catalyst
        if has_catalyst:
            score += 15
            reasons.append("Has news/catalyst driving movement")
        
        # Check short interest (short squeeze potential)
        if short_interest and short_interest >= 20:
            score += 10
            reasons.append(f"High short interest ({short_interest:.1f}%) - Squeeze potential")
        
        # Check float (low float = more volatile)
        if float_shares and float_shares < 20_000_000:
            score += 5
            reasons.append("Low float - Can move fast")
        
        is_in_play = score >= 30 and len(disqualifiers) < 2
        
        return InPlayQualification(
            is_in_play=is_in_play,
            score=min(100, score),
            reasons=reasons,
            disqualifiers=disqualifiers,
            rvol=rvol,
            gap_pct=gap_pct,
            atr_pct=atr_pct,
            float_shares=float_shares,
            short_interest=short_interest,
            has_catalyst=has_catalyst
        )
    
    # ==================== SCORING BY TIMEFRAME ====================
    
    def calculate_timeframe_score(
        self,
        timeframe: AlertTimeframe,
        technical_score: int,
        fundamental_score: int,
        catalyst_score: int,
        volume_score: int,
        regime_score: int
    ) -> int:
        """
        Calculate weighted score based on timeframe.
        Scalps weight technicals/volume more, swings weight fundamentals more.
        """
        weights = TIMEFRAME_WEIGHTS[timeframe]
        
        weighted_score = (
            technical_score * weights["technical"] +
            fundamental_score * weights["fundamental"] +
            catalyst_score * weights["catalyst"] +
            volume_score * weights["volume"] +
            regime_score * weights["regime"]
        )
        
        return int(weighted_score)
    
    # ==================== BREAKOUT SCAN ====================
    
    async def scan_breakout_setups(
        self, 
        symbols: List[str],
        timeframe: AlertTimeframe = AlertTimeframe.INTRADAY
    ) -> List[OrganizedAlert]:
        """
        Scan for breakout setups across timeframes.
        """
        alerts = []
        
        for symbol in symbols:
            try:
                market_data = await self._get_enhanced_market_data(symbol)
                if not market_data:
                    continue
                
                breakout_setup = await self._check_breakout_setup(symbol, market_data, timeframe)
                if breakout_setup:
                    alerts.append(breakout_setup)
                    
            except Exception as e:
                logger.warning(f"Error scanning {symbol} for breakout: {e}")
        
        return sorted(alerts, key=lambda x: x.overall_score, reverse=True)
    
    async def _check_breakout_setup(
        self, 
        symbol: str, 
        market_data: Dict,
        timeframe: AlertTimeframe
    ) -> Optional[OrganizedAlert]:
        """Check if symbol has a breakout setup forming"""
        price = market_data.get("price", 0)
        if price <= 0:
            return None
        
        resistance = market_data.get("resistance", price * 1.03)
        high_of_day = market_data.get("high", price)
        rvol = market_data.get("rvol", 1.0)
        atr = market_data.get("atr", price * 0.02)
        
        # Distance to breakout level
        distance_to_breakout = ((resistance - price) / price) * 100
        
        # Only consider if close to breakout
        if distance_to_breakout > 2.0 or distance_to_breakout < 0:
            return None
        
        # Check volume requirement
        if timeframe in [AlertTimeframe.SCALP, AlertTimeframe.INTRADAY]:
            if rvol < 2.0:
                return None
        else:
            if rvol < 1.5:
                return None
        
        # Calculate scores
        technical_score = self._score_breakout_technicals(market_data)
        fundamental_score = await self._get_fundamental_score(symbol)
        catalyst_score = market_data.get("catalyst_score", 50)
        volume_score = min(100, int(rvol * 25))
        regime_score = market_data.get("regime_score", 50)
        
        overall_score = self.calculate_timeframe_score(
            timeframe, technical_score, fundamental_score,
            catalyst_score, volume_score, regime_score
        )
        
        if overall_score < 45:
            return None
        
        # Calculate probabilities
        trigger_prob = self._calculate_breakout_trigger_prob(distance_to_breakout, rvol)
        base_win_rate = 0.55 if timeframe == AlertTimeframe.SCALP else 0.58
        win_prob = base_win_rate + (0.05 if rvol > 3 else 0)
        
        # Determine urgency
        if distance_to_breakout < 0.5:
            urgency = AlertUrgency.SETTING_UP_NOW
        else:
            urgency = AlertUrgency.ON_WATCH_TODAY
        
        # Build reasoning
        reasoning = self._build_breakout_reasoning(
            symbol, market_data, distance_to_breakout, rvol, timeframe
        )
        
        # In-play check for scalp/intraday
        in_play = None
        if timeframe in [AlertTimeframe.SCALP, AlertTimeframe.INTRADAY]:
            in_play = await self.check_in_play(symbol, market_data)
            if not in_play.is_in_play:
                return None  # Must be in play for scalps
        
        return OrganizedAlert(
            id=f"breakout_{symbol}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type="breakout_scalp" if timeframe == AlertTimeframe.SCALP else "breakout_swing",
            direction="long",
            timeframe=timeframe,
            urgency=urgency,
            in_play=in_play,
            overall_score=overall_score,
            technical_score=technical_score,
            fundamental_score=fundamental_score,
            catalyst_score=catalyst_score,
            regime_score=regime_score,
            trigger_probability=trigger_prob,
            win_probability=win_prob,
            expected_value=round((win_prob * 2.5) - ((1 - win_prob) * 1.0), 2),
            risk_reward=2.5,
            current_price=price,
            entry_zone=(resistance, resistance * 1.005),
            stop_loss=round(resistance - atr, 2),
            target_1=round(resistance + (atr * 1.5), 2),
            target_2=round(resistance + (atr * 2.5), 2),
            target_3=round(resistance + (atr * 4.0), 2) if timeframe != AlertTimeframe.SCALP else None,
            estimated_trigger_time=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
            minutes_to_trigger=10,
            reasoning=reasoning
        )
    
    def _score_breakout_technicals(self, market_data: Dict) -> int:
        """Score technical factors for breakout"""
        score = 50
        
        rvol = market_data.get("rvol", 1.0)
        rsi = market_data.get("rsi", 50)
        above_vwap = market_data.get("above_vwap", False)
        
        # Volume is crucial for breakouts
        if rvol >= 4.0:
            score += 20
        elif rvol >= 2.5:
            score += 12
        elif rvol >= 2.0:
            score += 5
        
        # RSI not overbought
        if 50 <= rsi <= 70:
            score += 10
        elif rsi > 80:
            score -= 10
        
        # Above VWAP is bullish
        if above_vwap:
            score += 8
        
        return min(100, max(0, score))
    
    def _calculate_breakout_trigger_prob(self, distance: float, rvol: float) -> float:
        """Calculate probability of breakout triggering"""
        base_prob = 0.30
        
        # Distance factor (closer = higher prob)
        if distance < 0.3:
            base_prob += 0.35
        elif distance < 0.7:
            base_prob += 0.25
        elif distance < 1.2:
            base_prob += 0.15
        else:
            base_prob += 0.05
        
        # Volume factor
        if rvol >= 4.0:
            base_prob += 0.15
        elif rvol >= 3.0:
            base_prob += 0.10
        elif rvol >= 2.0:
            base_prob += 0.05
        
        return min(0.90, base_prob)
    
    def _build_breakout_reasoning(
        self, 
        symbol: str, 
        market_data: Dict,
        distance: float,
        rvol: float,
        timeframe: AlertTimeframe
    ) -> AlertReasoning:
        """Build detailed reasoning for breakout alert"""
        price = market_data.get("price", 0)
        resistance = market_data.get("resistance", price * 1.03)
        atr = market_data.get("atr", price * 0.02)
        
        technical_reasons = []
        if distance < 0.5:
            technical_reasons.append(f"Price at resistance (${resistance:.2f}) - {distance:.1f}% away")
        else:
            technical_reasons.append(f"Approaching resistance (${resistance:.2f}) - {distance:.1f}% away")
        
        if rvol >= 3.0:
            technical_reasons.append(f"Strong volume surge (RVOL: {rvol:.1f}x) supporting the move")
        else:
            technical_reasons.append(f"Volume building (RVOL: {rvol:.1f}x)")
        
        if market_data.get("above_vwap"):
            technical_reasons.append("Trading above VWAP - bulls in control")
        
        fundamental_reasons = []
        if timeframe in [AlertTimeframe.SWING, AlertTimeframe.POSITION]:
            fund_score = market_data.get("fundamental_score", 50)
            if fund_score >= 70:
                fundamental_reasons.append("Strong fundamentals support the long-term thesis")
            elif fund_score >= 50:
                fundamental_reasons.append("Decent fundamentals - focus on technical setup")
        
        catalyst_reasons = []
        if market_data.get("has_catalyst"):
            catalyst_reasons.append("News catalyst driving unusual activity")
        if market_data.get("earnings_soon"):
            catalyst_reasons.append("Earnings approaching - potential volatility")
        
        risk_factors = []
        rsi = market_data.get("rsi", 50)
        if rsi > 70:
            risk_factors.append(f"RSI elevated ({rsi:.0f}) - may see pullback before breakout")
        if rvol < 2.5:
            risk_factors.append("Volume could be stronger - watch for confirmation")
        
        summary = f"""
{symbol} is setting up for a {'scalp' if timeframe == AlertTimeframe.SCALP else 'swing'} breakout trade.

**The Setup:** Price is {distance:.1f}% below key resistance at ${resistance:.2f}. 
Volume is {'surging' if rvol >= 3 else 'building'} at {rvol:.1f}x relative volume.

**The Trade Plan:**
- Wait for price to break above ${resistance:.2f} with volume confirmation
- Entry zone: ${resistance:.2f} - ${resistance * 1.005:.2f}
- Stop loss: ${resistance - atr:.2f} (below breakout level)
- Target 1: ${resistance + (atr * 1.5):.2f} (+{((atr * 1.5) / resistance * 100):.1f}%)
- Target 2: ${resistance + (atr * 2.5):.2f} (+{((atr * 2.5) / resistance * 100):.1f}%)

**Why This Setup:** {"This is a high-conviction breakout with strong volume support." if rvol >= 3 else "Volume is building - confirm breakout before entry."}
"""
        
        return AlertReasoning(
            summary=summary,
            technical_reasons=technical_reasons,
            fundamental_reasons=fundamental_reasons,
            catalyst_reasons=catalyst_reasons,
            risk_factors=risk_factors,
            key_levels={
                "resistance": resistance,
                "stop": resistance - atr,
                "target_1": resistance + (atr * 1.5),
                "target_2": resistance + (atr * 2.5),
            },
            trade_plan={
                "entry_trigger": f"Break above ${resistance:.2f} with volume",
                "position_size": "Full size" if rvol >= 3 else "Half size until confirmed",
                "management": "Scale out at targets, trail stop after T1"
            }
        )
    
    # ==================== SHORT SQUEEZE SCAN ====================
    
    async def scan_short_squeeze_setups(
        self, 
        symbols: List[str],
        timeframe: AlertTimeframe = AlertTimeframe.INTRADAY
    ) -> List[OrganizedAlert]:
        """
        Scan for short squeeze setups.
        High short interest + upward price pressure + volume = squeeze
        """
        alerts = []
        
        for symbol in symbols:
            try:
                market_data = await self._get_enhanced_market_data(symbol)
                if not market_data:
                    continue
                
                squeeze_setup = await self._check_short_squeeze_setup(symbol, market_data, timeframe)
                if squeeze_setup:
                    alerts.append(squeeze_setup)
                    
            except Exception as e:
                logger.warning(f"Error scanning {symbol} for squeeze: {e}")
        
        return sorted(alerts, key=lambda x: x.overall_score, reverse=True)
    
    async def _check_short_squeeze_setup(
        self,
        symbol: str,
        market_data: Dict,
        timeframe: AlertTimeframe
    ) -> Optional[OrganizedAlert]:
        """Check for short squeeze setup"""
        short_interest = market_data.get("short_interest", 0)
        days_to_cover = market_data.get("days_to_cover", 0)
        price = market_data.get("price", 0)
        rvol = market_data.get("rvol", 1.0)
        
        if price <= 0:
            return None
        
        # Need high short interest
        min_si = 15.0 if timeframe in [AlertTimeframe.SCALP, AlertTimeframe.INTRADAY] else 20.0
        if short_interest < min_si:
            return None
        
        # Need volume surge
        if rvol < 2.0:
            return None
        
        # Need upward momentum (price above VWAP or key MA)
        above_vwap = market_data.get("above_vwap", False)
        price_change = market_data.get("price_change_pct", 0)
        
        if not above_vwap and price_change < 2.0:
            return None
        
        # Score the setup
        squeeze_score = self._score_squeeze_setup(market_data)
        if squeeze_score < 50:
            return None
        
        atr = market_data.get("atr", price * 0.03)
        
        # Calculate probabilities
        trigger_prob = min(0.85, 0.40 + (rvol * 0.08) + (short_interest * 0.01))
        win_prob = 0.55 + (0.02 if short_interest > 25 else 0) + (0.03 if rvol > 4 else 0)
        
        # Determine urgency
        if rvol >= 4 and price_change >= 5:
            urgency = AlertUrgency.SETTING_UP_NOW
        elif rvol >= 3:
            urgency = AlertUrgency.ON_WATCH_TODAY
        else:
            urgency = AlertUrgency.SETTING_UP_TODAY if timeframe == AlertTimeframe.SWING else AlertUrgency.ON_WATCH_TODAY
        
        # In-play check
        in_play = await self.check_in_play(symbol, market_data)
        
        # Build reasoning
        reasoning = self._build_squeeze_reasoning(symbol, market_data, timeframe)
        
        return OrganizedAlert(
            id=f"squeeze_{symbol}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type="short_squeeze_intraday" if timeframe == AlertTimeframe.INTRADAY else "short_squeeze_swing",
            direction="long",
            timeframe=timeframe,
            urgency=urgency,
            in_play=in_play,
            overall_score=squeeze_score,
            technical_score=market_data.get("technical_score", 60),
            fundamental_score=market_data.get("fundamental_score", 50),
            catalyst_score=market_data.get("catalyst_score", 70),  # Squeeze is a catalyst
            regime_score=market_data.get("regime_score", 50),
            trigger_probability=trigger_prob,
            win_probability=win_prob,
            expected_value=round((win_prob * 4.0) - ((1 - win_prob) * 1.5), 2),  # Squeezes have high R:R
            risk_reward=3.0,
            current_price=price,
            entry_zone=(price, price * 1.01),
            stop_loss=round(price * 0.95, 2),  # 5% stop for squeeze plays
            target_1=round(price * 1.10, 2),   # 10% target
            target_2=round(price * 1.20, 2),   # 20% target
            target_3=round(price * 1.35, 2) if timeframe == AlertTimeframe.SWING else None,  # 35% for swing
            estimated_trigger_time=(datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
            minutes_to_trigger=15,
            reasoning=reasoning
        )
    
    def _score_squeeze_setup(self, market_data: Dict) -> int:
        """Score short squeeze setup quality"""
        score = 40
        
        short_interest = market_data.get("short_interest", 0)
        days_to_cover = market_data.get("days_to_cover", 0)
        rvol = market_data.get("rvol", 1.0)
        price_change = market_data.get("price_change_pct", 0)
        
        # Short interest score
        if short_interest >= 30:
            score += 25
        elif short_interest >= 20:
            score += 18
        elif short_interest >= 15:
            score += 10
        
        # Days to cover
        if days_to_cover >= 5:
            score += 10
        elif days_to_cover >= 3:
            score += 5
        
        # Volume surge
        if rvol >= 5:
            score += 20
        elif rvol >= 3:
            score += 12
        elif rvol >= 2:
            score += 5
        
        # Price momentum
        if price_change >= 10:
            score += 15
        elif price_change >= 5:
            score += 10
        elif price_change >= 2:
            score += 5
        
        return min(100, score)
    
    def _build_squeeze_reasoning(
        self,
        symbol: str,
        market_data: Dict,
        timeframe: AlertTimeframe
    ) -> AlertReasoning:
        """Build reasoning for short squeeze alert"""
        price = market_data.get("price", 0)
        short_interest = market_data.get("short_interest", 0)
        days_to_cover = market_data.get("days_to_cover", 0)
        rvol = market_data.get("rvol", 1.0)
        price_change = market_data.get("price_change_pct", 0)
        
        summary = f"""
🔥 {symbol} SHORT SQUEEZE ALERT 🔥

**The Setup:** {short_interest:.1f}% of float is sold short ({days_to_cover:.1f} days to cover).
Price is up {price_change:.1f}% with {rvol:.1f}x relative volume - shorts are under pressure!

**Why This Works:** When heavily shorted stocks move up on volume, shorts are forced to cover (buy back shares),
creating a self-reinforcing buying cycle. With {short_interest:.1f}% short interest, there's significant fuel for a squeeze.

**Trade Plan:**
- Entry: Current price area (${price:.2f})
- Stop: ${price * 0.95:.2f} (-5% - tight stop, squeezes move fast)
- Target 1: ${price * 1.10:.2f} (+10%)
- Target 2: ${price * 1.20:.2f} (+20%)

**Warning:** Squeeze plays are volatile. Use smaller position size and expect fast moves in either direction.
"""
        
        return AlertReasoning(
            summary=summary,
            technical_reasons=[
                f"Price up {price_change:.1f}% - momentum building",
                f"Volume surge at {rvol:.1f}x relative volume",
                "Breaking above VWAP - bulls in control" if market_data.get("above_vwap") else "Testing VWAP"
            ],
            fundamental_reasons=[
                "Fundamentals less relevant for squeeze plays",
                "Focus on technical setup and short interest"
            ],
            catalyst_reasons=[
                f"High short interest ({short_interest:.1f}%) creates squeeze potential",
                f"{days_to_cover:.1f} days to cover - shorts need time to exit",
                "Volume surge indicates shorts may be covering"
            ],
            risk_factors=[
                "Squeeze plays are extremely volatile",
                "Can reverse quickly if momentum stalls",
                "Use smaller position size"
            ],
            key_levels={
                "entry": price,
                "stop": price * 0.95,
                "target_1": price * 1.10,
                "target_2": price * 1.20,
            },
            trade_plan={
                "position_size": "Half size - high volatility play",
                "management": "Take profits at each target, use trailing stop",
                "exit_signal": "Close if volume dries up or price fails VWAP"
            }
        )
    
    # ==================== MAIN SCAN FUNCTION ====================
    
    async def scan_all_setups(
        self,
        symbols: List[str] = None,
        include_scalp: bool = True,
        include_intraday: bool = True,
        include_swing: bool = True,
        include_position: bool = False
    ) -> Dict[str, List[OrganizedAlert]]:
        """
        Main scanning function - scans for all setup types and organizes by timeframe.
        Returns alerts organized into categories.
        """
        symbols = symbols or self._get_default_watchlist()
        
        results = {
            "scalp_now": [],
            "scalp_watch": [],
            "intraday_now": [],
            "intraday_watch": [],
            "swing_today": [],
            "swing_week": [],
            "position": []
        }
        
        for symbol in symbols:
            try:
                market_data = await self._get_enhanced_market_data(symbol)
                if not market_data:
                    continue
                
                # Check in-play status first
                in_play = await self.check_in_play(symbol, market_data)
                market_data["in_play"] = in_play
                
                # SCALP SCANS (only if in play)
                if include_scalp and in_play.is_in_play:
                    scalp_alerts = await self._scan_scalp_setups(symbol, market_data)
                    for alert in scalp_alerts:
                        if alert.urgency == AlertUrgency.SETTING_UP_NOW:
                            results["scalp_now"].append(alert)
                        else:
                            results["scalp_watch"].append(alert)
                
                # INTRADAY SCANS
                if include_intraday:
                    intraday_alerts = await self._scan_intraday_setups(symbol, market_data)
                    for alert in intraday_alerts:
                        if alert.urgency == AlertUrgency.SETTING_UP_NOW:
                            results["intraday_now"].append(alert)
                        else:
                            results["intraday_watch"].append(alert)
                
                # SWING SCANS
                if include_swing:
                    swing_alerts = await self._scan_swing_setups(symbol, market_data)
                    for alert in swing_alerts:
                        if alert.urgency == AlertUrgency.SETTING_UP_TODAY:
                            results["swing_today"].append(alert)
                        else:
                            results["swing_week"].append(alert)
                
                # POSITION SCANS (typically run EOD/morning)
                if include_position:
                    position_alerts = await self._scan_position_setups(symbol, market_data)
                    results["position"].extend(position_alerts)
                    
            except Exception as e:
                logger.warning(f"Error scanning {symbol}: {e}")
        
        # Sort each category by score
        for key in results:
            results[key].sort(key=lambda x: x.overall_score, reverse=True)
        
        # Update internal state
        self._scalp_alerts_now = results["scalp_now"]
        self._scalp_alerts_watch = results["scalp_watch"]
        self._swing_alerts_today = results["swing_today"]
        self._swing_alerts_week = results["swing_week"]
        
        return results
    
    async def _scan_scalp_setups(
        self, 
        symbol: str, 
        market_data: Dict
    ) -> List[OrganizedAlert]:
        """Scan for all scalp setups"""
        alerts = []
        
        # Rubber Band Long
        rb_long = await self._check_rubber_band_long(symbol, market_data, AlertTimeframe.SCALP)
        if rb_long:
            alerts.append(rb_long)
        
        # Rubber Band Short
        rb_short = await self._check_rubber_band_short(symbol, market_data, AlertTimeframe.SCALP)
        if rb_short:
            alerts.append(rb_short)
        
        # VWAP Reclaim
        vwap_reclaim = await self._check_vwap_reclaim(symbol, market_data)
        if vwap_reclaim:
            alerts.append(vwap_reclaim)
        
        # Breakout Scalp
        breakout = await self._check_breakout_setup(symbol, market_data, AlertTimeframe.SCALP)
        if breakout:
            alerts.append(breakout)
        
        return alerts
    
    async def _scan_intraday_setups(
        self, 
        symbol: str, 
        market_data: Dict
    ) -> List[OrganizedAlert]:
        """Scan for intraday setups"""
        alerts = []
        
        # Short Squeeze
        squeeze = await self._check_short_squeeze_setup(symbol, market_data, AlertTimeframe.INTRADAY)
        if squeeze:
            alerts.append(squeeze)
        
        # Gap and Go
        gap_go = await self._check_gap_and_go(symbol, market_data)
        if gap_go:
            alerts.append(gap_go)
        
        # Momentum Continuation
        momentum = await self._check_momentum_continuation(symbol, market_data, AlertTimeframe.INTRADAY)
        if momentum:
            alerts.append(momentum)
        
        return alerts
    
    async def _scan_swing_setups(
        self, 
        symbol: str, 
        market_data: Dict
    ) -> List[OrganizedAlert]:
        """Scan for swing setups (more fundamental weight)"""
        alerts = []
        
        # Breakout Swing
        breakout = await self._check_breakout_setup(symbol, market_data, AlertTimeframe.SWING)
        if breakout:
            alerts.append(breakout)
        
        # Short Squeeze Swing
        squeeze = await self._check_short_squeeze_setup(symbol, market_data, AlertTimeframe.SWING)
        if squeeze:
            alerts.append(squeeze)
        
        return alerts
    
    async def _scan_position_setups(
        self, 
        symbol: str, 
        market_data: Dict
    ) -> List[OrganizedAlert]:
        """Scan for position setups (heaviest fundamental weight)"""
        # Position setups require deeper fundamental analysis
        # Typically run this at EOD or morning
        return []
    
    # ==================== HELPER SETUP CHECKS ====================
    
    async def _check_rubber_band_long(
        self, 
        symbol: str, 
        market_data: Dict,
        timeframe: AlertTimeframe
    ) -> Optional[OrganizedAlert]:
        """Check for rubber band long setup"""
        price = market_data.get("price", 0)
        ema_9 = market_data.get("ema_9", price)
        atr = market_data.get("atr", price * 0.02)
        rvol = market_data.get("rvol", 1.0)
        rsi = market_data.get("rsi", 50)
        
        if price <= 0 or ema_9 <= 0:
            return None
        
        # Calculate extension
        extension_pct = ((price - ema_9) / ema_9) * 100
        
        # Need to be extended below EMA
        if extension_pct > -2.0 or extension_pct < -8.0:
            return None
        
        # RSI should be oversold
        if rsi > 45:
            return None
        
        # Calculate scores
        technical_score = 70 + int(abs(extension_pct) * 3)
        fundamental_score = await self._get_fundamental_score(symbol)
        volume_score = min(100, int(rvol * 25))
        
        overall_score = self.calculate_timeframe_score(
            timeframe, technical_score, fundamental_score, 50, volume_score, 50
        )
        
        if overall_score < 50:
            return None
        
        trigger_prob = min(0.85, 0.40 + abs(extension_pct) * 0.08 + (rvol * 0.05))
        win_prob = 0.62 + (0.03 if rvol > 2 else 0)
        
        urgency = AlertUrgency.SETTING_UP_NOW if extension_pct < -4 else AlertUrgency.ON_WATCH_TODAY
        
        reasoning = AlertReasoning(
            summary=f"""
{symbol} RUBBER BAND SCALP (LONG)

Price is extended {abs(extension_pct):.1f}% BELOW the 9 EMA - rubber band is stretched!
RSI at {rsi:.0f} confirms oversold conditions. When price snaps back to the 9 EMA, 
that's our profit zone.

**Entry:** Wait for price to show signs of reversal (green candle, bounce off support)
**Stop:** ${price - (atr * 0.75):.2f} (below recent low)
**Target:** ${ema_9:.2f} (9 EMA - the snap back target)

Volume is {'strong' if rvol >= 2 else 'moderate'} at {rvol:.1f}x - {'good confirmation' if rvol >= 2 else 'watch for volume pickup'}.
""",
            technical_reasons=[
                f"Extended {abs(extension_pct):.1f}% below 9 EMA - mean reversion setup",
                f"RSI oversold at {rsi:.0f}",
                f"RVOL at {rvol:.1f}x"
            ],
            fundamental_reasons=["Fundamentals less important for scalps - focus on price action"],
            catalyst_reasons=[],
            risk_factors=[
                "Could extend further before bouncing",
                "Need volume confirmation on reversal"
            ],
            key_levels={
                "entry": price,
                "stop": price - (atr * 0.75),
                "target_1": ema_9,
            },
            trade_plan={
                "entry_trigger": "Bullish reversal candle",
                "position_size": "Full size" if rvol >= 2 else "Half size"
            }
        )
        
        return OrganizedAlert(
            id=f"rb_long_{symbol}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type="rubber_band_scalp_long",
            direction="long",
            timeframe=timeframe,
            urgency=urgency,
            in_play=market_data.get("in_play"),
            overall_score=overall_score,
            technical_score=technical_score,
            fundamental_score=fundamental_score,
            catalyst_score=50,
            regime_score=50,
            trigger_probability=trigger_prob,
            win_probability=win_prob,
            expected_value=round((win_prob * 1.5) - ((1 - win_prob) * 0.75), 2),
            risk_reward=2.0,
            current_price=price,
            entry_zone=(price * 0.998, price * 1.002),
            stop_loss=round(price - (atr * 0.75), 2),
            target_1=round(ema_9, 2),
            target_2=round(ema_9 + (atr * 0.5), 2),
            target_3=None,
            estimated_trigger_time=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            minutes_to_trigger=5,
            reasoning=reasoning
        )
    
    async def _check_rubber_band_short(
        self, 
        symbol: str, 
        market_data: Dict,
        timeframe: AlertTimeframe
    ) -> Optional[OrganizedAlert]:
        """Check for rubber band short setup"""
        price = market_data.get("price", 0)
        ema_9 = market_data.get("ema_9", price)
        atr = market_data.get("atr", price * 0.02)
        rvol = market_data.get("rvol", 1.0)
        rsi = market_data.get("rsi", 50)
        
        if price <= 0 or ema_9 <= 0:
            return None
        
        extension_pct = ((price - ema_9) / ema_9) * 100
        
        # Need to be extended above EMA
        if extension_pct < 2.5 or extension_pct > 8.0:
            return None
        
        # RSI should be overbought
        if rsi < 60:
            return None
        
        technical_score = 65 + int(extension_pct * 3)
        fundamental_score = await self._get_fundamental_score(symbol)
        volume_score = min(100, int(rvol * 25))
        
        overall_score = self.calculate_timeframe_score(
            timeframe, technical_score, fundamental_score, 50, volume_score, 50
        )
        
        if overall_score < 50:
            return None
        
        trigger_prob = min(0.80, 0.35 + extension_pct * 0.07 + (rvol * 0.05))
        win_prob = 0.58 + (0.03 if rvol > 2 else 0)
        
        urgency = AlertUrgency.SETTING_UP_NOW if extension_pct > 4 else AlertUrgency.ON_WATCH_TODAY
        
        reasoning = AlertReasoning(
            summary=f"""
{symbol} RUBBER BAND SCALP (SHORT)

Price is extended {extension_pct:.1f}% ABOVE the 9 EMA - overextended!
RSI at {rsi:.0f} confirms overbought conditions. Expect a snap back DOWN to the 9 EMA.

**Entry:** Wait for price rejection (red candle, fail at resistance)
**Stop:** ${price + (atr * 0.75):.2f} (above recent high)
**Target:** ${ema_9:.2f} (9 EMA)
""",
            technical_reasons=[
                f"Extended {extension_pct:.1f}% above 9 EMA",
                f"RSI overbought at {rsi:.0f}",
            ],
            fundamental_reasons=[],
            catalyst_reasons=[],
            risk_factors=["Momentum can extend further", "Need volume confirmation"],
            key_levels={"entry": price, "stop": price + (atr * 0.75), "target_1": ema_9},
            trade_plan={"entry_trigger": "Bearish reversal candle"}
        )
        
        return OrganizedAlert(
            id=f"rb_short_{symbol}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type="rubber_band_scalp_short",
            direction="short",
            timeframe=timeframe,
            urgency=urgency,
            in_play=market_data.get("in_play"),
            overall_score=overall_score,
            technical_score=technical_score,
            fundamental_score=fundamental_score,
            catalyst_score=50,
            regime_score=50,
            trigger_probability=trigger_prob,
            win_probability=win_prob,
            expected_value=round((win_prob * 1.5) - ((1 - win_prob) * 0.75), 2),
            risk_reward=2.0,
            current_price=price,
            entry_zone=(price * 0.998, price * 1.002),
            stop_loss=round(price + (atr * 0.75), 2),
            target_1=round(ema_9, 2),
            target_2=round(ema_9 - (atr * 0.5), 2),
            target_3=None,
            estimated_trigger_time=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            minutes_to_trigger=5,
            reasoning=reasoning
        )
    
    async def _check_vwap_reclaim(
        self, 
        symbol: str, 
        market_data: Dict
    ) -> Optional[OrganizedAlert]:
        """Check for VWAP reclaim setup"""
        price = market_data.get("price", 0)
        vwap = market_data.get("vwap", price)
        atr = market_data.get("atr", price * 0.02)
        rvol = market_data.get("rvol", 1.0)
        
        if price <= 0:
            return None
        
        vwap_dist = ((price - vwap) / vwap) * 100
        
        # Looking for price just below VWAP, about to reclaim
        if vwap_dist < -1.5 or vwap_dist > 0.3:
            return None
        
        if rvol < 1.5:
            return None
        
        technical_score = 65
        overall_score = self.calculate_timeframe_score(
            AlertTimeframe.SCALP, technical_score, 50, 50, min(100, int(rvol * 25)), 50
        )
        
        if overall_score < 45:
            return None
        
        reasoning = AlertReasoning(
            summary=f"""
{symbol} VWAP RECLAIM SETUP

Price is {abs(vwap_dist):.1f}% below VWAP at ${vwap:.2f}. 
If price reclaims VWAP with volume, it signals bulls taking control.

**Entry:** On VWAP reclaim with volume confirmation
**Stop:** ${vwap - (atr * 0.5):.2f}
**Target:** ${vwap + (atr * 1.0):.2f}
""",
            technical_reasons=[f"Price {abs(vwap_dist):.1f}% below VWAP", f"RVOL: {rvol:.1f}x"],
            fundamental_reasons=[],
            catalyst_reasons=[],
            risk_factors=["May fail VWAP and continue lower"],
            key_levels={"vwap": vwap},
            trade_plan={"entry_trigger": "Break above VWAP"}
        )
        
        return OrganizedAlert(
            id=f"vwap_reclaim_{symbol}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type="vwap_reclaim_long",
            direction="long",
            timeframe=AlertTimeframe.SCALP,
            urgency=AlertUrgency.SETTING_UP_NOW if abs(vwap_dist) < 0.5 else AlertUrgency.ON_WATCH_TODAY,
            in_play=market_data.get("in_play"),
            overall_score=overall_score,
            technical_score=technical_score,
            fundamental_score=50,
            catalyst_score=50,
            regime_score=50,
            trigger_probability=0.55,
            win_probability=0.60,
            expected_value=1.2,
            risk_reward=2.0,
            current_price=price,
            entry_zone=(vwap * 0.998, vwap * 1.002),
            stop_loss=round(vwap - (atr * 0.5), 2),
            target_1=round(vwap + (atr * 1.0), 2),
            target_2=round(vwap + (atr * 1.5), 2),
            target_3=None,
            estimated_trigger_time=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
            minutes_to_trigger=10,
            reasoning=reasoning
        )
    
    async def _check_gap_and_go(
        self, 
        symbol: str, 
        market_data: Dict
    ) -> Optional[OrganizedAlert]:
        """Check for gap and go setup"""
        price = market_data.get("price", 0)
        gap_pct = market_data.get("gap_pct", 0)
        rvol = market_data.get("rvol", 1.0)
        atr = market_data.get("atr", price * 0.03)
        
        if price <= 0:
            return None
        
        # Need significant gap up
        if gap_pct < 4.0:
            return None
        
        if rvol < 3.0:
            return None
        
        # Check if holding gap
        prev_close = price / (1 + gap_pct / 100)
        if price < prev_close:
            return None  # Lost the gap
        
        overall_score = self.calculate_timeframe_score(
            AlertTimeframe.INTRADAY, 70, 50, 70, min(100, int(rvol * 20)), 50
        )
        
        reasoning = AlertReasoning(
            summary=f"""
{symbol} GAP AND GO

Gapped up {gap_pct:.1f}% with {rvol:.1f}x volume - showing strength!
Look for continuation above opening range high.

**The Play:** Gap ups that hold and continue higher often run hard.
Watch for break of the opening range high for entry.
""",
            technical_reasons=[f"Gap up {gap_pct:.1f}%", f"High volume {rvol:.1f}x", "Holding gap level"],
            fundamental_reasons=[],
            catalyst_reasons=["Gap usually indicates news/catalyst"],
            risk_factors=["Gap could fill if momentum stalls"],
            key_levels={"gap_fill": prev_close},
            trade_plan={"entry_trigger": "Break above opening range high"}
        )
        
        return OrganizedAlert(
            id=f"gap_go_{symbol}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type="gap_and_go",
            direction="long",
            timeframe=AlertTimeframe.INTRADAY,
            urgency=AlertUrgency.SETTING_UP_NOW if gap_pct >= 6 else AlertUrgency.ON_WATCH_TODAY,
            in_play=market_data.get("in_play"),
            overall_score=overall_score,
            technical_score=70,
            fundamental_score=50,
            catalyst_score=70,
            regime_score=50,
            trigger_probability=0.55,
            win_probability=0.52,
            expected_value=1.5,
            risk_reward=2.0,
            current_price=price,
            entry_zone=(price * 1.002, price * 1.01),
            stop_loss=round(prev_close * 1.01, 2),
            target_1=round(price * 1.05, 2),
            target_2=round(price * 1.10, 2),
            target_3=None,
            estimated_trigger_time=(datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
            minutes_to_trigger=20,
            reasoning=reasoning
        )
    
    async def _check_momentum_continuation(
        self, 
        symbol: str, 
        market_data: Dict,
        timeframe: AlertTimeframe
    ) -> Optional[OrganizedAlert]:
        """Check for momentum continuation setup"""
        price = market_data.get("price", 0)
        price_change = market_data.get("price_change_pct", 0)
        rvol = market_data.get("rvol", 1.0)
        atr = market_data.get("atr", price * 0.02)
        above_vwap = market_data.get("above_vwap", False)
        
        if price <= 0:
            return None
        
        # Need strong momentum
        if price_change < 3.0:
            return None
        
        if rvol < 2.0:
            return None
        
        if not above_vwap:
            return None
        
        overall_score = self.calculate_timeframe_score(
            timeframe, 72, 50, 60, min(100, int(rvol * 20)), 55
        )
        
        direction = "long" if price_change > 0 else "short"
        
        reasoning = AlertReasoning(
            summary=f"""
{symbol} MOMENTUM CONTINUATION

Strong momentum today: +{price_change:.1f}% with {rvol:.1f}x volume.
Trading above VWAP - bulls in control. Look for pullback entry or breakout continuation.
""",
            technical_reasons=[f"+{price_change:.1f}% move", f"RVOL: {rvol:.1f}x", "Above VWAP"],
            fundamental_reasons=[],
            catalyst_reasons=["Momentum often driven by catalyst"],
            risk_factors=["Extended move could pullback"],
            key_levels={},
            trade_plan={"entry_trigger": "Pullback to VWAP or breakout continuation"}
        )
        
        return OrganizedAlert(
            id=f"momentum_{symbol}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type="momentum_continuation",
            direction=direction,
            timeframe=timeframe,
            urgency=AlertUrgency.ON_WATCH_TODAY,
            in_play=market_data.get("in_play"),
            overall_score=overall_score,
            technical_score=72,
            fundamental_score=50,
            catalyst_score=60,
            regime_score=55,
            trigger_probability=0.50,
            win_probability=0.55,
            expected_value=1.3,
            risk_reward=2.0,
            current_price=price,
            entry_zone=(price * 0.99, price * 1.01),
            stop_loss=round(price * 0.97, 2),
            target_1=round(price * 1.05, 2),
            target_2=round(price * 1.08, 2),
            target_3=None,
            estimated_trigger_time=(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
            minutes_to_trigger=30,
            reasoning=reasoning
        )
    
    # ==================== DATA HELPERS ====================
    
    async def _get_enhanced_market_data(self, symbol: str) -> Optional[Dict]:
        """Get comprehensive market data for scanning"""
        try:
            quote = await self.alpaca_service.get_quote(symbol)
            if not quote or quote.get("price", 0) <= 0:
                return None
            
            price = quote.get("price", 0)
            
            # Get fundamentals
            fundamentals = None
            fundamental_score = 50
            try:
                fundamentals = await self.fundamental_service.get_fundamentals(symbol)
                if fundamentals:
                    # Quick fundamental score
                    if fundamentals.roe and fundamentals.roe > 0.15:
                        fundamental_score += 15
                    if fundamentals.pe_ratio and 10 < fundamentals.pe_ratio < 25:
                        fundamental_score += 10
                    if fundamentals.debt_to_equity and fundamentals.debt_to_equity < 1:
                        fundamental_score += 10
            except:
                pass
            
            # Estimate technicals (would be more accurate with real bar data)
            atr = price * 0.025  # 2.5% estimate
            
            return {
                "symbol": symbol,
                "price": price,
                "bid": quote.get("bid", price * 0.999),
                "ask": quote.get("ask", price * 1.001),
                "spread_pct": ((quote.get("ask", price) - quote.get("bid", price)) / price) * 100,
                "volume": quote.get("volume", 0),
                "rvol": 1.8,  # Estimate - would come from real data
                "gap_pct": 2.0,  # Estimate
                "atr": atr,
                "atr_pct": (atr / price) * 100,
                "vwap": price * 0.998,
                "ema_9": price * 0.99,
                "ema_20": price * 0.985,
                "rsi": 52,  # Estimate
                "above_vwap": True,
                "price_change_pct": 1.5,  # Estimate
                "resistance": price * 1.025,
                "support": price * 0.975,
                "high": price * 1.015,
                "low": price * 0.985,
                "has_catalyst": False,
                "short_interest": 8.0,  # Estimate
                "days_to_cover": 2.0,
                "float_shares": 100_000_000,
                "fundamental_score": fundamental_score,
                "fundamentals": fundamentals,
            }
        except Exception as e:
            logger.warning(f"Error getting market data for {symbol}: {e}")
            return None
    
    async def _get_fundamental_score(self, symbol: str) -> int:
        """Get fundamental score for a symbol"""
        try:
            analysis = await self.fundamental_service.analyze_fundamentals(symbol)
            if analysis.get("available"):
                return analysis.get("value_score", 50)
        except:
            pass
        return 50
    
    def _get_default_watchlist(self) -> List[str]:
        """Default watchlist"""
        return [
            "NVDA", "TSLA", "AMD", "META", "AAPL", "MSFT", "GOOGL", "AMZN",
            "SPY", "QQQ", "IWM", "NFLX", "BA", "DIS", "COIN", "SHOP", "SQ"
        ]
    
    # ==================== PUBLIC API ====================
    
    def get_scalp_alerts(self) -> Dict[str, List[OrganizedAlert]]:
        """Get organized scalp alerts"""
        return {
            "setting_up_now": self._scalp_alerts_now[:10],
            "on_watch_today": self._scalp_alerts_watch[:10]
        }
    
    def get_swing_alerts(self) -> Dict[str, List[OrganizedAlert]]:
        """Get organized swing alerts"""
        return {
            "setting_up_today": self._swing_alerts_today[:10],
            "setting_up_this_week": self._swing_alerts_week[:10]
        }
    
    def get_alerts_summary_for_ai(self) -> str:
        """Get formatted summary for AI assistant"""
        summary = "=== TRADE ALERTS SUMMARY ===\n\n"
        
        if self._scalp_alerts_now:
            summary += "🔴 SCALP: SETTING UP NOW\n"
            for alert in self._scalp_alerts_now[:3]:
                summary += f"""
• {alert.symbol} - {alert.setup_type.replace('_', ' ').title()}
  Direction: {alert.direction.upper()} | Score: {alert.overall_score}
  Win Prob: {alert.win_probability:.0%} | R:R: {alert.risk_reward:.1f}:1
  {alert.reasoning.summary[:200]}...
"""
        
        if self._scalp_alerts_watch:
            summary += "\n🟡 SCALP: ON WATCH FOR LATER TODAY\n"
            for alert in self._scalp_alerts_watch[:3]:
                summary += f"• {alert.symbol} - {alert.setup_type.replace('_', ' ').title()} ({alert.overall_score})\n"
        
        if self._swing_alerts_today:
            summary += "\n📊 SWING: SETTING UP TODAY\n"
            for alert in self._swing_alerts_today[:3]:
                summary += f"""
• {alert.symbol} - {alert.setup_type.replace('_', ' ').title()}
  Score: {alert.overall_score} | Win Prob: {alert.win_probability:.0%}
  Fundamentals: {alert.fundamental_score}/100
"""
        
        if self._swing_alerts_week:
            summary += "\n📅 SWING: SETTING UP THIS WEEK\n"
            for alert in self._swing_alerts_week[:3]:
                summary += f"• {alert.symbol} - {alert.setup_type.replace('_', ' ').title()} ({alert.overall_score})\n"
        
        return summary


# Global instance
_alert_system: Optional[AdvancedAlertSystem] = None


def get_alert_system() -> AdvancedAlertSystem:
    """Get or create the alert system"""
    global _alert_system
    if _alert_system is None:
        _alert_system = AdvancedAlertSystem()
    return _alert_system
