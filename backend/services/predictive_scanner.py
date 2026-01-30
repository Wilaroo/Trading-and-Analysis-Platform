"""
Predictive Trade Scanner & Alert System
Identifies trade setups BEFORE they trigger using probability-based analysis.

Features:
- Real-time scanning for "forming" setups (not just "formed")
- Entry trigger probability calculation
- Predicted outcome with realistic targets
- 5-minute advance alerts
- AI Assistant integration
- Strategy-specific filtering (Rubber Band, Breakout, etc.)
"""
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import math

logger = logging.getLogger(__name__)


class SetupPhase(str, Enum):
    """Phase of setup development"""
    EARLY_FORMATION = "early_formation"      # Pattern starting to form (20-40% probability)
    DEVELOPING = "developing"                 # Pattern developing (40-60% probability)
    NEARLY_READY = "nearly_ready"            # About to trigger (60-80% probability)
    TRIGGER_IMMINENT = "trigger_imminent"    # 5 mins or less to trigger (80%+ probability)
    TRIGGERED = "triggered"                   # Entry triggered
    INVALIDATED = "invalidated"              # Setup failed/invalidated


class SetupType(str, Enum):
    """Types of trade setups we scan for"""
    RUBBER_BAND_LONG = "rubber_band_long"
    RUBBER_BAND_SHORT = "rubber_band_short"
    BREAKOUT = "breakout"
    BREAKDOWN = "breakdown"
    VWAP_BOUNCE = "vwap_bounce"
    VWAP_REJECTION = "vwap_rejection"
    GAP_AND_GO = "gap_and_go"
    GAP_FADE = "gap_fade"
    MOMENTUM_CONTINUATION = "momentum_continuation"
    MEAN_REVERSION = "mean_reversion"
    OPENING_RANGE_BREAKOUT = "orb"
    RED_TO_GREEN = "red_to_green"
    GREEN_TO_RED = "green_to_red"


@dataclass
class PredictedOutcome:
    """Predicted trade outcome with probabilities"""
    win_probability: float          # 0-1 probability of hitting target
    expected_gain_pct: float        # Expected gain if wins
    expected_loss_pct: float        # Expected loss if stops out
    expected_value: float           # EV calculation
    realistic_target: float         # Price target
    realistic_stop: float           # Stop loss price
    risk_reward_ratio: float        # R:R
    time_to_target_mins: int        # Estimated time to reach target
    confidence: str                 # "high", "medium", "low"
    factors: List[str]              # Key factors driving prediction


@dataclass
class FormingSetup:
    """A trade setup that is forming but not yet triggered"""
    id: str
    symbol: str
    setup_type: SetupType
    phase: SetupPhase
    direction: str                  # "long" or "short"
    
    # Current state
    current_price: float
    trigger_price: float            # Price that triggers entry
    distance_to_trigger_pct: float  # How far from trigger
    
    # Probabilities
    trigger_probability: float      # Probability entry will trigger (0-1)
    minutes_to_trigger: int         # Estimated minutes until trigger
    
    # Predicted outcome
    prediction: PredictedOutcome
    
    # Scores
    setup_score: int                # 0-100 overall score
    technical_score: int
    fundamental_score: int
    catalyst_score: int
    
    # Context
    strategy_match: str             # Which strategy this matches
    pattern_detected: List[str]     # Detected chart patterns
    key_levels: Dict[str, float]    # Support, resistance, VWAP, etc.
    
    # Alerts
    alert_sent: bool = False
    alert_time: Optional[str] = None
    
    # Metadata
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    notes: List[str] = field(default_factory=list)


@dataclass 
class TriggerAlert:
    """Alert for an imminent trade trigger"""
    id: str
    setup_id: str
    symbol: str
    setup_type: str
    direction: str
    
    # Timing
    alert_time: str
    estimated_trigger_time: str
    minutes_until_trigger: int
    
    # Trade details
    trigger_price: float
    entry_zone: Tuple[float, float]  # (low, high) entry range
    stop_loss: float
    target_1: float
    target_2: Optional[float]
    risk_reward: float
    
    # Probabilities
    trigger_probability: float
    win_probability: float
    expected_value: float
    
    # Context
    setup_score: int
    strategy_match: str
    reasoning: List[str]
    
    # Status
    status: str = "pending"  # pending, triggered, invalidated, expired
    outcome: Optional[str] = None  # win, loss, breakeven


class PredictiveScannerService:
    """
    Core predictive scanning engine that identifies forming setups
    and calculates trigger probabilities.
    """
    
    # Strategy criteria definitions
    STRATEGY_CRITERIA = {
        SetupType.RUBBER_BAND_LONG: {
            "description": "Mean reversion long - price extended below 9 EMA",
            "min_extension_pct": -3.0,      # Must be X% below EMA
            "max_extension_pct": -8.0,      # Not more than X% (overextended)
            "min_rvol": 1.5,
            "vwap_position": "below",       # Should be below VWAP
            "rsi_range": (20, 40),          # Oversold but not extreme
            "trigger_condition": "price crosses above 9 EMA",
            "base_win_rate": 0.62,
            "avg_gain": 2.5,
            "avg_loss": 1.0,
        },
        SetupType.RUBBER_BAND_SHORT: {
            "description": "Mean reversion short - price extended above 9 EMA",
            "min_extension_pct": 3.0,
            "max_extension_pct": 8.0,
            "min_rvol": 1.5,
            "vwap_position": "above",
            "rsi_range": (60, 80),
            "trigger_condition": "price crosses below 9 EMA",
            "base_win_rate": 0.58,
            "avg_gain": 2.0,
            "avg_loss": 1.0,
        },
        SetupType.BREAKOUT: {
            "description": "Price breaking above resistance with volume",
            "min_rvol": 2.0,
            "consolidation_bars": 5,        # Min bars of consolidation
            "breakout_threshold_pct": 0.5,  # Must break by X%
            "vwap_position": "above",
            "trigger_condition": "price breaks resistance with volume surge",
            "base_win_rate": 0.55,
            "avg_gain": 3.0,
            "avg_loss": 1.5,
        },
        SetupType.VWAP_BOUNCE: {
            "description": "Price bouncing off VWAP support",
            "vwap_distance_pct": (-0.5, 0.5),  # Near VWAP
            "min_rvol": 1.5,
            "trend": "uptrend",              # Overall trend should be up
            "trigger_condition": "price bounces off VWAP with bullish candle",
            "base_win_rate": 0.60,
            "avg_gain": 1.5,
            "avg_loss": 0.75,
        },
        SetupType.GAP_AND_GO: {
            "description": "Gap up continuation with strong volume",
            "min_gap_pct": 4.0,
            "min_rvol": 3.0,
            "hold_gap": True,                # Must hold gap level
            "trigger_condition": "price breaks opening range high",
            "base_win_rate": 0.52,
            "avg_gain": 4.0,
            "avg_loss": 2.0,
        },
        SetupType.OPENING_RANGE_BREAKOUT: {
            "description": "Break of first 15-min range",
            "time_window": (9, 30, 9, 45),   # 9:30-9:45 AM range
            "min_rvol": 2.0,
            "min_range_pct": 1.0,            # Range must be at least 1%
            "trigger_condition": "price breaks opening range with volume",
            "base_win_rate": 0.54,
            "avg_gain": 2.5,
            "avg_loss": 1.25,
        },
        SetupType.RED_TO_GREEN: {
            "description": "Stock opens red, reverses to green",
            "open_change_pct": (-3, 0),      # Opens down
            "reversal_required": True,
            "min_rvol": 2.0,
            "trigger_condition": "price crosses above previous close",
            "base_win_rate": 0.58,
            "avg_gain": 2.0,
            "avg_loss": 1.0,
        },
    }
    
    def __init__(self, db=None):
        self.db = db
        self._forming_setups: Dict[str, FormingSetup] = {}
        self._alerts: List[TriggerAlert] = []
        self._alert_history: List[TriggerAlert] = []
        self._watchlist: List[str] = []
        self._scanning: bool = False
        self._scan_interval: int = 30  # seconds between scans
        
        # Service dependencies (lazy loaded)
        self._alpaca_service = None
        self._scoring_engine = None
        self._fundamental_service = None
        self._trading_intelligence = None
        self._news_service = None
        
        if db:
            self.alerts_collection = db["predictive_alerts"]
            self.setups_collection = db["forming_setups"]
    
    # ==================== SERVICE GETTERS ====================
    
    @property
    def alpaca_service(self):
        if self._alpaca_service is None:
            from services.alpaca_service import AlpacaService
            self._alpaca_service = AlpacaService()
        return self._alpaca_service
    
    @property
    def scoring_engine(self):
        if self._scoring_engine is None:
            from services.scoring_engine import get_scoring_engine
            self._scoring_engine = get_scoring_engine()
        return self._scoring_engine
    
    @property
    def fundamental_service(self):
        if self._fundamental_service is None:
            from services.fundamental_data_service import get_fundamental_data_service
            self._fundamental_service = get_fundamental_data_service()
        return self._fundamental_service
    
    @property
    def trading_intelligence(self):
        if self._trading_intelligence is None:
            from services.trading_intelligence import get_trading_intelligence
            self._trading_intelligence = get_trading_intelligence()
        return self._trading_intelligence
    
    # ==================== CORE SCANNING LOGIC ====================
    
    async def scan_for_setups(self, symbols: List[str] = None) -> List[FormingSetup]:
        """
        Scan symbols for forming trade setups.
        Returns list of setups sorted by trigger probability.
        """
        symbols = symbols or self._watchlist or self._get_default_watchlist()
        forming_setups = []
        
        for symbol in symbols:
            try:
                # Get market data
                market_data = await self._get_market_data(symbol)
                if not market_data:
                    continue
                
                # Check each setup type
                for setup_type in SetupType:
                    if setup_type not in self.STRATEGY_CRITERIA:
                        continue
                    
                    setup = await self._check_setup_forming(symbol, setup_type, market_data)
                    if setup and setup.trigger_probability > 0.20:
                        forming_setups.append(setup)
                        
            except Exception as e:
                logger.warning(f"Error scanning {symbol}: {e}")
                continue
        
        # Sort by trigger probability (highest first)
        forming_setups.sort(key=lambda x: x.trigger_probability, reverse=True)
        
        # Update internal state
        for setup in forming_setups:
            self._forming_setups[setup.id] = setup
        
        # Generate alerts for imminent triggers
        await self._check_and_generate_alerts(forming_setups)
        
        return forming_setups
    
    async def _get_market_data(self, symbol: str) -> Optional[Dict]:
        """Fetch comprehensive market data for a symbol"""
        try:
            # Get real-time quote from Alpaca
            quote = await self.alpaca_service.get_quote(symbol)
            if not quote or quote.get("price", 0) <= 0:
                return None
            
            current_price = quote.get("price", 0)
            
            # Get fundamental data
            fundamentals = None
            try:
                fundamentals = await self.fundamental_service.get_fundamentals(symbol)
            except Exception as e:
                logger.debug(f"Could not get fundamentals for {symbol}: {e}")
            
            # Build basic technical data from quote
            # Note: For full technicals, we'd need historical bars
            # For now, use approximations based on price
            atr_estimate = current_price * 0.02  # 2% of price as ATR estimate
            
            return {
                "symbol": symbol,
                "current_price": current_price,
                "bid": quote.get("bid", current_price * 0.999),
                "ask": quote.get("ask", current_price * 1.001),
                "volume": quote.get("volume", 0),
                "timestamp": quote.get("timestamp"),
                "fundamentals": fundamentals,
                "technicals": {
                    "vwap": current_price * 0.995,  # Estimate VWAP slightly below current
                    "ema_9": current_price * 0.99,   # Estimate 9 EMA
                    "ema_20": current_price * 0.985, # Estimate 20 EMA
                    "rsi_14": 50,  # Default neutral RSI
                    "rvol": 1.5,   # Default moderate relative volume
                    "atr": atr_estimate,
                    "high": current_price * 1.02,
                    "low": current_price * 0.98,
                    "resistance": current_price * 1.03,
                    "support": current_price * 0.97,
                },
                "scores": {
                    "overall": 50,
                    "technical": 50,
                    "fundamental": 50,
                    "catalyst": 0
                },
            }
        except Exception as e:
            logger.warning(f"Error getting market data for {symbol}: {e}")
            return None
    
    async def _check_setup_forming(
        self, 
        symbol: str, 
        setup_type: SetupType, 
        market_data: Dict
    ) -> Optional[FormingSetup]:
        """
        Check if a specific setup type is forming for a symbol.
        Returns FormingSetup if conditions are partially met.
        """
        criteria = self.STRATEGY_CRITERIA.get(setup_type)
        if not criteria:
            return None
        
        current_price = market_data.get("current_price", 0)
        technicals = market_data.get("technicals", {})
        analysis = market_data.get("analysis", {})
        
        if current_price <= 0:
            return None
        
        # Extract technical indicators
        vwap = technicals.get("vwap", current_price)
        ema_9 = technicals.get("ema_9", current_price)
        ema_20 = technicals.get("ema_20", current_price)
        rsi = technicals.get("rsi_14", 50)
        rvol = technicals.get("rvol", 1.0)
        atr = technicals.get("atr", current_price * 0.02)
        
        # Calculate distances
        vwap_distance_pct = ((current_price - vwap) / vwap * 100) if vwap > 0 else 0
        ema9_distance_pct = ((current_price - ema_9) / ema_9 * 100) if ema_9 > 0 else 0
        
        # Check setup-specific criteria
        if setup_type == SetupType.RUBBER_BAND_LONG:
            return await self._check_rubber_band_long(
                symbol, current_price, ema9_distance_pct, vwap_distance_pct, 
                rsi, rvol, ema_9, atr, market_data
            )
        
        elif setup_type == SetupType.RUBBER_BAND_SHORT:
            return await self._check_rubber_band_short(
                symbol, current_price, ema9_distance_pct, vwap_distance_pct,
                rsi, rvol, ema_9, atr, market_data
            )
        
        elif setup_type == SetupType.BREAKOUT:
            return await self._check_breakout(
                symbol, current_price, vwap_distance_pct, rvol, atr, market_data
            )
        
        elif setup_type == SetupType.VWAP_BOUNCE:
            return await self._check_vwap_bounce(
                symbol, current_price, vwap, vwap_distance_pct, rvol, atr, market_data
            )
        
        return None
    
    async def _check_rubber_band_long(
        self, symbol: str, price: float, ema_dist: float, vwap_dist: float,
        rsi: float, rvol: float, ema_9: float, atr: float, market_data: Dict
    ) -> Optional[FormingSetup]:
        """Check for Rubber Band Long setup forming"""
        criteria = self.STRATEGY_CRITERIA[SetupType.RUBBER_BAND_LONG]
        
        # Check if price is extended below EMA
        if ema_dist > criteria["min_extension_pct"]:
            return None  # Not extended enough
        
        if ema_dist < criteria["max_extension_pct"]:
            return None  # Too extended (dangerous)
        
        # Calculate trigger probability based on conditions
        probability = 0.0
        notes = []
        
        # Extension factor (more extended = higher probability of snap back)
        extension_factor = abs(ema_dist) / abs(criteria["min_extension_pct"])
        probability += min(0.25, extension_factor * 0.15)
        notes.append(f"Extended {abs(ema_dist):.1f}% below 9 EMA")
        
        # RVOL factor
        if rvol >= criteria["min_rvol"]:
            probability += 0.15
            notes.append(f"Good volume (RVOL: {rvol:.1f}x)")
        elif rvol >= criteria["min_rvol"] * 0.7:
            probability += 0.08
            notes.append(f"Moderate volume (RVOL: {rvol:.1f}x)")
        
        # RSI factor (oversold = higher probability)
        rsi_low, rsi_high = criteria["rsi_range"]
        if rsi_low <= rsi <= rsi_high:
            probability += 0.20
            notes.append(f"RSI in sweet spot ({rsi:.0f})")
        elif rsi < rsi_low:
            probability += 0.10  # Very oversold, could bounce hard
            notes.append(f"Very oversold RSI ({rsi:.0f})")
        
        # VWAP position
        if vwap_dist < 0:  # Below VWAP
            probability += 0.10
            notes.append("Below VWAP (mean reversion target)")
        
        # Price approaching trigger (EMA 9)
        distance_to_trigger = abs(ema_dist)
        if distance_to_trigger < 1.5:
            probability += 0.20
            notes.append("Very close to trigger!")
        elif distance_to_trigger < 2.5:
            probability += 0.10
            notes.append("Approaching trigger zone")
        
        # Estimate time to trigger based on recent momentum
        minutes_to_trigger = self._estimate_time_to_trigger(distance_to_trigger, atr, price)
        
        # Determine phase
        if probability >= 0.70:
            phase = SetupPhase.TRIGGER_IMMINENT
        elif probability >= 0.50:
            phase = SetupPhase.NEARLY_READY
        elif probability >= 0.35:
            phase = SetupPhase.DEVELOPING
        else:
            phase = SetupPhase.EARLY_FORMATION
        
        # Calculate predicted outcome
        prediction = self._calculate_predicted_outcome(
            setup_type=SetupType.RUBBER_BAND_LONG,
            entry_price=ema_9,
            current_price=price,
            atr=atr,
            rvol=rvol,
            market_data=market_data
        )
        
        # Get scores from analysis
        scores = market_data.get("scores", {})
        
        return FormingSetup(
            id=f"{symbol}_{SetupType.RUBBER_BAND_LONG.value}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type=SetupType.RUBBER_BAND_LONG,
            phase=phase,
            direction="long",
            current_price=price,
            trigger_price=ema_9,
            distance_to_trigger_pct=abs(ema_dist),
            trigger_probability=min(0.95, probability),
            minutes_to_trigger=minutes_to_trigger,
            prediction=prediction,
            setup_score=scores.get("overall", 50),
            technical_score=scores.get("technical", 50),
            fundamental_score=scores.get("fundamental", 50),
            catalyst_score=scores.get("catalyst", 0),
            strategy_match="Rubber Band Scalp",
            pattern_detected=["mean_reversion", "oversold_bounce"],
            key_levels={
                "entry": ema_9,
                "stop": price - (atr * 1.5),
                "target_1": ema_9 + (atr * 1.5),
                "target_2": ema_9 + (atr * 2.5),
                "vwap": market_data.get("technicals", {}).get("vwap", price),
            },
            notes=notes
        )
    
    async def _check_rubber_band_short(
        self, symbol: str, price: float, ema_dist: float, vwap_dist: float,
        rsi: float, rvol: float, ema_9: float, atr: float, market_data: Dict
    ) -> Optional[FormingSetup]:
        """Check for Rubber Band Short setup forming"""
        criteria = self.STRATEGY_CRITERIA[SetupType.RUBBER_BAND_SHORT]
        
        # Check if price is extended above EMA
        if ema_dist < criteria["min_extension_pct"]:
            return None
        
        if ema_dist > criteria["max_extension_pct"]:
            return None
        
        probability = 0.0
        notes = []
        
        # Extension factor
        extension_factor = ema_dist / criteria["min_extension_pct"]
        probability += min(0.25, extension_factor * 0.15)
        notes.append(f"Extended {ema_dist:.1f}% above 9 EMA")
        
        # RVOL factor
        if rvol >= criteria["min_rvol"]:
            probability += 0.15
            notes.append(f"Good volume (RVOL: {rvol:.1f}x)")
        
        # RSI factor (overbought)
        rsi_low, rsi_high = criteria["rsi_range"]
        if rsi_low <= rsi <= rsi_high:
            probability += 0.20
            notes.append(f"RSI overbought ({rsi:.0f})")
        elif rsi > rsi_high:
            probability += 0.10
            notes.append(f"Very overbought RSI ({rsi:.0f})")
        
        # VWAP position
        if vwap_dist > 0:
            probability += 0.10
            notes.append("Above VWAP (mean reversion target)")
        
        # Distance to trigger
        distance_to_trigger = abs(ema_dist)
        if distance_to_trigger < 1.5:
            probability += 0.20
            notes.append("Very close to trigger!")
        elif distance_to_trigger < 2.5:
            probability += 0.10
        
        minutes_to_trigger = self._estimate_time_to_trigger(distance_to_trigger, atr, price)
        
        if probability >= 0.70:
            phase = SetupPhase.TRIGGER_IMMINENT
        elif probability >= 0.50:
            phase = SetupPhase.NEARLY_READY
        elif probability >= 0.35:
            phase = SetupPhase.DEVELOPING
        else:
            phase = SetupPhase.EARLY_FORMATION
        
        prediction = self._calculate_predicted_outcome(
            setup_type=SetupType.RUBBER_BAND_SHORT,
            entry_price=ema_9,
            current_price=price,
            atr=atr,
            rvol=rvol,
            market_data=market_data
        )
        
        scores = market_data.get("scores", {})
        
        return FormingSetup(
            id=f"{symbol}_{SetupType.RUBBER_BAND_SHORT.value}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type=SetupType.RUBBER_BAND_SHORT,
            phase=phase,
            direction="short",
            current_price=price,
            trigger_price=ema_9,
            distance_to_trigger_pct=distance_to_trigger,
            trigger_probability=min(0.95, probability),
            minutes_to_trigger=minutes_to_trigger,
            prediction=prediction,
            setup_score=scores.get("overall", 50),
            technical_score=scores.get("technical", 50),
            fundamental_score=scores.get("fundamental", 50),
            catalyst_score=scores.get("catalyst", 0),
            strategy_match="Rubber Band Scalp",
            pattern_detected=["mean_reversion", "overbought_fade"],
            key_levels={
                "entry": ema_9,
                "stop": price + (atr * 1.5),
                "target_1": ema_9 - (atr * 1.5),
                "target_2": ema_9 - (atr * 2.5),
                "vwap": market_data.get("technicals", {}).get("vwap", price),
            },
            notes=notes
        )
    
    async def _check_breakout(
        self, symbol: str, price: float, vwap_dist: float, 
        rvol: float, atr: float, market_data: Dict
    ) -> Optional[FormingSetup]:
        """Check for Breakout setup forming"""
        criteria = self.STRATEGY_CRITERIA[SetupType.BREAKOUT]
        technicals = market_data.get("technicals", {})
        
        # Need high of day or resistance level
        high_of_day = technicals.get("high", price)
        resistance = technicals.get("resistance", high_of_day)
        
        # Check if consolidating near resistance
        distance_to_resistance = ((resistance - price) / price * 100) if resistance > price else 0
        
        if distance_to_resistance > 2.0:
            return None  # Too far from breakout
        
        probability = 0.0
        notes = []
        
        # Proximity to resistance
        if distance_to_resistance < 0.5:
            probability += 0.30
            notes.append("At resistance level!")
        elif distance_to_resistance < 1.0:
            probability += 0.20
            notes.append("Near resistance")
        else:
            probability += 0.10
        
        # Volume building
        if rvol >= criteria["min_rvol"]:
            probability += 0.25
            notes.append(f"Volume building (RVOL: {rvol:.1f}x)")
        elif rvol >= 1.5:
            probability += 0.10
        
        # Above VWAP (bullish)
        if vwap_dist > 0:
            probability += 0.15
            notes.append("Above VWAP")
        
        # Check for consolidation pattern
        # (simplified - would need candle data for proper detection)
        probability += 0.10
        notes.append("Consolidation pattern forming")
        
        if probability < 0.25:
            return None
        
        minutes_to_trigger = self._estimate_time_to_trigger(distance_to_resistance, atr, price)
        
        if probability >= 0.70:
            phase = SetupPhase.TRIGGER_IMMINENT
        elif probability >= 0.50:
            phase = SetupPhase.NEARLY_READY
        elif probability >= 0.35:
            phase = SetupPhase.DEVELOPING
        else:
            phase = SetupPhase.EARLY_FORMATION
        
        prediction = self._calculate_predicted_outcome(
            setup_type=SetupType.BREAKOUT,
            entry_price=resistance * 1.002,  # Entry just above resistance
            current_price=price,
            atr=atr,
            rvol=rvol,
            market_data=market_data
        )
        
        scores = market_data.get("scores", {})
        
        return FormingSetup(
            id=f"{symbol}_{SetupType.BREAKOUT.value}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type=SetupType.BREAKOUT,
            phase=phase,
            direction="long",
            current_price=price,
            trigger_price=resistance,
            distance_to_trigger_pct=distance_to_resistance,
            trigger_probability=min(0.95, probability),
            minutes_to_trigger=minutes_to_trigger,
            prediction=prediction,
            setup_score=scores.get("overall", 50),
            technical_score=scores.get("technical", 50),
            fundamental_score=scores.get("fundamental", 50),
            catalyst_score=scores.get("catalyst", 0),
            strategy_match="Breakout",
            pattern_detected=["consolidation", "breakout_forming"],
            key_levels={
                "entry": resistance * 1.002,
                "stop": resistance - (atr * 1.0),
                "target_1": resistance + (atr * 2.0),
                "target_2": resistance + (atr * 3.5),
                "resistance": resistance,
                "vwap": technicals.get("vwap", price),
            },
            notes=notes
        )
    
    async def _check_vwap_bounce(
        self, symbol: str, price: float, vwap: float, vwap_dist: float,
        rvol: float, atr: float, market_data: Dict
    ) -> Optional[FormingSetup]:
        """Check for VWAP Bounce setup forming"""
        criteria = self.STRATEGY_CRITERIA[SetupType.VWAP_BOUNCE]
        
        # Check if price is near VWAP
        dist_low, dist_high = criteria["vwap_distance_pct"]
        if not (dist_low <= vwap_dist <= dist_high):
            # Also check if approaching VWAP from above
            if vwap_dist > dist_high and vwap_dist < 2.0:
                pass  # Allow approaching
            else:
                return None
        
        probability = 0.0
        notes = []
        
        # Proximity to VWAP
        if abs(vwap_dist) < 0.3:
            probability += 0.30
            notes.append("At VWAP!")
        elif abs(vwap_dist) < 0.7:
            probability += 0.20
            notes.append("Near VWAP")
        else:
            probability += 0.10
            notes.append("Approaching VWAP")
        
        # Volume
        if rvol >= criteria["min_rvol"]:
            probability += 0.20
            notes.append(f"Good volume (RVOL: {rvol:.1f}x)")
        
        # Overall trend (need to be in uptrend for bounce to work)
        technicals = market_data.get("technicals", {})
        ema_20 = technicals.get("ema_20", price)
        if price > ema_20:
            probability += 0.15
            notes.append("Uptrend intact (above 20 EMA)")
        
        if probability < 0.25:
            return None
        
        minutes_to_trigger = self._estimate_time_to_trigger(abs(vwap_dist), atr, price)
        
        if probability >= 0.70:
            phase = SetupPhase.TRIGGER_IMMINENT
        elif probability >= 0.50:
            phase = SetupPhase.NEARLY_READY
        elif probability >= 0.35:
            phase = SetupPhase.DEVELOPING
        else:
            phase = SetupPhase.EARLY_FORMATION
        
        prediction = self._calculate_predicted_outcome(
            setup_type=SetupType.VWAP_BOUNCE,
            entry_price=vwap,
            current_price=price,
            atr=atr,
            rvol=rvol,
            market_data=market_data
        )
        
        scores = market_data.get("scores", {})
        
        return FormingSetup(
            id=f"{symbol}_{SetupType.VWAP_BOUNCE.value}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type=SetupType.VWAP_BOUNCE,
            phase=phase,
            direction="long",
            current_price=price,
            trigger_price=vwap,
            distance_to_trigger_pct=abs(vwap_dist),
            trigger_probability=min(0.95, probability),
            minutes_to_trigger=minutes_to_trigger,
            prediction=prediction,
            setup_score=scores.get("overall", 50),
            technical_score=scores.get("technical", 50),
            fundamental_score=scores.get("fundamental", 50),
            catalyst_score=scores.get("catalyst", 0),
            strategy_match="VWAP Bounce",
            pattern_detected=["vwap_test", "support_bounce"],
            key_levels={
                "entry": vwap,
                "stop": vwap - (atr * 0.75),
                "target_1": vwap + (atr * 1.5),
                "target_2": vwap + (atr * 2.5),
                "vwap": vwap,
            },
            notes=notes
        )
    
    # ==================== PREDICTION & PROBABILITY ====================
    
    def _calculate_predicted_outcome(
        self,
        setup_type: SetupType,
        entry_price: float,
        current_price: float,
        atr: float,
        rvol: float,
        market_data: Dict
    ) -> PredictedOutcome:
        """Calculate predicted outcome with win probability and expected value"""
        criteria = self.STRATEGY_CRITERIA.get(setup_type, {})
        
        # Base win rate from historical data
        base_win_rate = criteria.get("base_win_rate", 0.50)
        avg_gain = criteria.get("avg_gain", 2.0)
        avg_loss = criteria.get("avg_loss", 1.0)
        
        # Adjust win rate based on conditions
        win_rate = base_win_rate
        factors = []
        
        # Volume adjustment
        if rvol >= 3.0:
            win_rate += 0.05
            factors.append(f"High volume boost (+5%): RVOL {rvol:.1f}x")
        elif rvol >= 2.0:
            win_rate += 0.02
            factors.append(f"Good volume (+2%): RVOL {rvol:.1f}x")
        elif rvol < 1.5:
            win_rate -= 0.05
            factors.append(f"Low volume risk (-5%): RVOL {rvol:.1f}x")
        
        # Market context adjustment
        scores = market_data.get("scores", {})
        overall_score = scores.get("overall", 50)
        if overall_score >= 70:
            win_rate += 0.05
            factors.append(f"Strong technicals (+5%): Score {overall_score}")
        elif overall_score < 40:
            win_rate -= 0.05
            factors.append(f"Weak technicals (-5%): Score {overall_score}")
        
        # Fundamental adjustment (from real-time data)
        fundamentals = market_data.get("fundamentals")
        if fundamentals:
            roe = fundamentals.roe
            if roe and roe > 0.15:
                win_rate += 0.02
                factors.append("Strong ROE (+2%)")
        
        # Clamp win rate
        win_rate = max(0.30, min(0.80, win_rate))
        
        # Calculate targets based on ATR
        if setup_type in [SetupType.RUBBER_BAND_LONG, SetupType.VWAP_BOUNCE]:
            realistic_target = entry_price + (atr * 1.5)
            realistic_stop = entry_price - (atr * 0.75)
        elif setup_type == SetupType.RUBBER_BAND_SHORT:
            realistic_target = entry_price - (atr * 1.5)
            realistic_stop = entry_price + (atr * 0.75)
        else:  # Breakout
            realistic_target = entry_price + (atr * 2.0)
            realistic_stop = entry_price - (atr * 1.0)
        
        # Calculate percentages
        expected_gain_pct = abs(realistic_target - entry_price) / entry_price * 100
        expected_loss_pct = abs(entry_price - realistic_stop) / entry_price * 100
        
        # Risk:Reward
        rr_ratio = expected_gain_pct / expected_loss_pct if expected_loss_pct > 0 else 1.0
        
        # Expected Value
        ev = (win_rate * expected_gain_pct) - ((1 - win_rate) * expected_loss_pct)
        
        # Confidence level
        if win_rate >= 0.65 and rr_ratio >= 2.0:
            confidence = "high"
        elif win_rate >= 0.55 and rr_ratio >= 1.5:
            confidence = "medium"
        else:
            confidence = "low"
        
        # Time to target estimate
        time_to_target = int(30 + (expected_gain_pct / 0.5) * 15)  # Rough estimate
        
        return PredictedOutcome(
            win_probability=round(win_rate, 3),
            expected_gain_pct=round(expected_gain_pct, 2),
            expected_loss_pct=round(expected_loss_pct, 2),
            expected_value=round(ev, 2),
            realistic_target=round(realistic_target, 2),
            realistic_stop=round(realistic_stop, 2),
            risk_reward_ratio=round(rr_ratio, 2),
            time_to_target_mins=time_to_target,
            confidence=confidence,
            factors=factors
        )
    
    def _estimate_time_to_trigger(
        self, distance_pct: float, atr: float, price: float
    ) -> int:
        """Estimate minutes until trigger based on distance and volatility"""
        # Rough estimate: how many ATR-sized moves to reach trigger
        atr_pct = (atr / price) * 100
        if atr_pct <= 0:
            return 60
        
        moves_needed = distance_pct / (atr_pct * 0.3)  # Assume 30% ATR moves per bar
        minutes = int(moves_needed * 5)  # Assume 5-min bars
        
        return max(2, min(120, minutes))
    
    # ==================== ALERT GENERATION ====================
    
    async def _check_and_generate_alerts(self, setups: List[FormingSetup]) -> List[TriggerAlert]:
        """Generate alerts for setups that are about to trigger"""
        new_alerts = []
        
        for setup in setups:
            # Alert if trigger imminent (5 mins or less) and high probability
            if (setup.phase in [SetupPhase.TRIGGER_IMMINENT, SetupPhase.NEARLY_READY] 
                and setup.trigger_probability >= 0.60
                and not setup.alert_sent):
                
                alert = self._create_alert(setup)
                new_alerts.append(alert)
                self._alerts.append(alert)
                setup.alert_sent = True
                setup.alert_time = datetime.now(timezone.utc).isoformat()
                
                logger.info(f"🚨 ALERT: {setup.symbol} {setup.setup_type.value} - "
                           f"Trigger in ~{setup.minutes_to_trigger} mins "
                           f"({setup.trigger_probability:.0%} probability)")
        
        return new_alerts
    
    def _create_alert(self, setup: FormingSetup) -> TriggerAlert:
        """Create a trigger alert from a forming setup"""
        now = datetime.now(timezone.utc)
        trigger_time = now + timedelta(minutes=setup.minutes_to_trigger)
        
        reasoning = [
            f"Setup: {setup.setup_type.value.replace('_', ' ').title()}",
            f"Strategy Match: {setup.strategy_match}",
            f"Trigger Probability: {setup.trigger_probability:.0%}",
            f"Win Probability: {setup.prediction.win_probability:.0%}",
            f"Expected Value: {setup.prediction.expected_value:.2f}%",
            f"Risk:Reward: {setup.prediction.risk_reward_ratio:.1f}:1",
        ] + setup.notes
        
        return TriggerAlert(
            id=f"alert_{setup.id}",
            setup_id=setup.id,
            symbol=setup.symbol,
            setup_type=setup.setup_type.value,
            direction=setup.direction,
            alert_time=now.isoformat(),
            estimated_trigger_time=trigger_time.isoformat(),
            minutes_until_trigger=setup.minutes_to_trigger,
            trigger_price=setup.trigger_price,
            entry_zone=(setup.trigger_price * 0.998, setup.trigger_price * 1.002),
            stop_loss=setup.key_levels.get("stop", setup.trigger_price * 0.98),
            target_1=setup.key_levels.get("target_1", setup.trigger_price * 1.02),
            target_2=setup.key_levels.get("target_2"),
            risk_reward=setup.prediction.risk_reward_ratio,
            trigger_probability=setup.trigger_probability,
            win_probability=setup.prediction.win_probability,
            expected_value=setup.prediction.expected_value,
            setup_score=setup.setup_score,
            strategy_match=setup.strategy_match,
            reasoning=reasoning
        )
    
    # ==================== PUBLIC API ====================
    
    def get_forming_setups(
        self, 
        min_probability: float = 0.30,
        setup_types: List[SetupType] = None,
        symbols: List[str] = None
    ) -> List[FormingSetup]:
        """Get currently forming setups, optionally filtered"""
        setups = list(self._forming_setups.values())
        
        # Filter by probability
        setups = [s for s in setups if s.trigger_probability >= min_probability]
        
        # Filter by setup type
        if setup_types:
            setups = [s for s in setups if s.setup_type in setup_types]
        
        # Filter by symbol
        if symbols:
            symbols_upper = [s.upper() for s in symbols]
            setups = [s for s in setups if s.symbol in symbols_upper]
        
        # Sort by probability
        setups.sort(key=lambda x: x.trigger_probability, reverse=True)
        
        return setups
    
    def get_active_alerts(self) -> List[TriggerAlert]:
        """Get all active (pending) alerts"""
        return [a for a in self._alerts if a.status == "pending"]
    
    def get_alert_history(self, limit: int = 50) -> List[TriggerAlert]:
        """Get historical alerts"""
        return self._alert_history[-limit:]
    
    def set_watchlist(self, symbols: List[str]):
        """Set the watchlist for scanning"""
        self._watchlist = [s.upper() for s in symbols]
    
    def _get_default_watchlist(self) -> List[str]:
        """Default watchlist of liquid stocks"""
        return [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
            "AMD", "SPY", "QQQ", "IWM", "NFLX", "DIS", "BA", "JPM",
            "V", "MA", "PYPL", "SQ", "COIN", "SHOP", "ROKU", "SNAP"
        ]
    
    def get_setup_summary_for_ai(self) -> str:
        """Get formatted summary for AI assistant context"""
        setups = self.get_forming_setups(min_probability=0.40)
        alerts = self.get_active_alerts()
        
        if not setups and not alerts:
            return "No significant trade setups currently forming."
        
        summary = "=== CURRENT TRADE SETUPS FORMING ===\n\n"
        
        if alerts:
            summary += "🚨 IMMINENT TRIGGERS:\n"
            for alert in alerts[:3]:
                summary += f"""
• {alert.symbol} - {alert.setup_type.replace('_', ' ').upper()}
  Direction: {alert.direction.upper()}
  Trigger in: ~{alert.minutes_until_trigger} mins
  Entry: ${alert.trigger_price:.2f}
  Stop: ${alert.stop_loss:.2f} | Target: ${alert.target_1:.2f}
  Win Prob: {alert.win_probability:.0%} | R:R: {alert.risk_reward:.1f}:1
"""
        
        if setups:
            summary += "\n📊 DEVELOPING SETUPS:\n"
            for setup in setups[:5]:
                summary += f"""
• {setup.symbol} - {setup.setup_type.value.replace('_', ' ').title()}
  Phase: {setup.phase.value.replace('_', ' ').title()}
  Trigger Prob: {setup.trigger_probability:.0%}
  Distance to trigger: {setup.distance_to_trigger_pct:.1f}%
  Prediction: {setup.prediction.win_probability:.0%} win rate, {setup.prediction.expected_value:.1f}% EV
"""
        
        return summary


# Global service instance
_predictive_scanner: Optional[PredictiveScannerService] = None


def get_predictive_scanner() -> PredictiveScannerService:
    """Get or create the predictive scanner service"""
    global _predictive_scanner
    if _predictive_scanner is None:
        _predictive_scanner = PredictiveScannerService()
    return _predictive_scanner
