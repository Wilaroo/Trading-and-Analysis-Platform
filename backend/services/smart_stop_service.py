"""
Smart Stop System - Unified Intelligent Stop Loss Management
=============================================================

A single, comprehensive stop loss system that combines ALL features:

STOP MODES (6 types):
- original: Traditional stop below support with small buffer
- atr_dynamic: ATR-based stop (default 1.5x)
- anti_hunt: Beyond obvious levels with extra buffer
- volatility_adjusted: Widens in high vol, tightens in low vol
- layered: Multiple stop levels for partial exits
- chandelier: ATR-based trailing from high/low

SETUP-BASED RULES (8 types):
- breakout, pullback, momentum, mean_reversion
- gap_and_go, vwap_reversal, earnings_play, default

ANALYSIS FACTORS:
1. Volume Profile (POC, VAH/VAL, HVN/LVN)
2. Stop Hunt Risk Detection (float, volume, obvious levels)
3. Sector/Market Correlation (relative strength)
4. Regime Context (RISK_ON/OFF, CONFIRMED_DOWN adjustments)
5. Support/Resistance Levels (multi-timeframe)
6. ATR-based calculations
7. Round number avoidance
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS
# ============================================================================

class StopMode(Enum):
    """Available stop calculation modes"""
    ORIGINAL = "original"           # Traditional: Support - small buffer
    ATR_DYNAMIC = "atr_dynamic"     # ATR-based: Entry - 1.5x ATR
    ANTI_HUNT = "anti_hunt"         # Anti-hunt: Beyond obvious levels
    VOLATILITY_ADJUSTED = "volatility_adjusted"  # Adapts to volatility
    LAYERED = "layered"             # Multiple stop levels
    CHANDELIER = "chandelier"       # ATR from high/low


class TrailingMode(Enum):
    """Trailing stop behavior modes"""
    NONE = "none"
    ATR = "atr"
    PERCENT = "percent"
    CHANDELIER = "chandelier"
    BREAKEVEN_PLUS = "breakeven_plus"
    PARABOLIC = "parabolic"


class StopUrgency(Enum):
    """How urgently the stop should be managed"""
    NORMAL = "normal"
    CAUTION = "caution"
    HIGH_ALERT = "high_alert"
    EMERGENCY = "emergency"


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class SmartStopConfig:
    """Global configuration for smart stop calculations"""
    # Default mode
    default_mode: StopMode = StopMode.ATR_DYNAMIC
    
    # ATR settings
    atr_multiplier: float = 1.5
    chandelier_multiplier: float = 3.0
    
    # Distance constraints
    min_stop_distance_pct: float = 0.02  # 2% minimum
    max_stop_distance_pct: float = 0.08  # 8% maximum
    
    # Anti-hunt settings
    avoid_round_numbers: bool = True
    round_number_buffer_pct: float = 0.002
    anti_hunt_extra_atr: float = 0.5
    
    # Layered stop settings
    layer_percentages: List[float] = field(default_factory=lambda: [0.4, 0.3, 0.3])
    layer_atr_depths: List[float] = field(default_factory=lambda: [1.0, 1.5, 2.0])
    
    # Hunt detection thresholds
    low_float_threshold: float = 10_000_000
    low_volume_threshold: float = 500_000
    obvious_level_proximity_pct: float = 0.02


@dataclass
class SetupStopRules:
    """Stop rules specific to a trading setup type"""
    setup_type: str
    initial_stop_atr_mult: float = 1.5
    trailing_mode: TrailingMode = TrailingMode.ATR
    trailing_atr_mult: float = 2.0
    breakeven_r_target: float = 1.0
    scale_out_r_targets: List[float] = field(default_factory=list)
    min_stop_pct: float = 0.02
    max_stop_pct: float = 0.08
    use_swing_levels: bool = True
    use_volume_profile: bool = True
    respect_regime: bool = True
    description: str = ""


@dataclass
class VolumeProfile:
    """Volume profile analysis results"""
    poc: float              # Point of Control
    vah: float              # Value Area High
    val: float              # Value Area Low
    hvn_levels: List[float] # High Volume Nodes
    lvn_levels: List[float] # Low Volume Nodes
    total_volume: float
    
    def get_nearest_support(self, price: float) -> Optional[float]:
        supports = [self.val, self.poc] + self.hvn_levels
        below = [s for s in supports if s < price]
        return max(below) if below else None
    
    def get_nearest_resistance(self, price: float) -> Optional[float]:
        resistances = [self.vah, self.poc] + self.hvn_levels
        above = [r for r in resistances if r > price]
        return min(above) if above else None


@dataclass
class SmartStopResult:
    """Complete result from smart stop calculation"""
    # Primary stop
    stop_price: float
    stop_distance_pct: float
    stop_distance_atr: float
    
    # Mode and reasoning
    stop_mode: str
    primary_factor: str
    factors_considered: List[str]
    confidence: float
    
    # Risk assessment
    hunt_risk: str  # LOW, MEDIUM, HIGH
    hunt_risk_score: int
    urgency: StopUrgency
    warnings: List[str]
    
    # Trailing configuration
    trailing_mode: TrailingMode
    trailing_trigger_price: float
    breakeven_trigger_price: float
    
    # Layered exits
    layered_stops: List[Dict]
    scale_out_plan: List[Dict]
    
    # Context data
    volume_profile_support: Optional[float]
    sector_adjustment: float
    regime_adjustment: float
    setup_rules_used: str
    
    # Anti-hunt info
    obvious_zones_avoided: List[float]
    anti_hunt_buffer_applied: float
    
    # Metadata
    symbol: str
    entry_price: float
    direction: str
    calculated_at: str
    valid_until: str


# ============================================================================
# SETUP RULES DEFINITIONS
# ============================================================================

SETUP_STOP_RULES = {
    "breakout": SetupStopRules(
        setup_type="breakout",
        initial_stop_atr_mult=1.0,
        trailing_mode=TrailingMode.CHANDELIER,
        trailing_atr_mult=2.5,
        breakeven_r_target=1.5,
        scale_out_r_targets=[1.5, 2.5, 4.0],
        description="Stop below breakout level, chandelier trail after 1.5R"
    ),
    "pullback": SetupStopRules(
        setup_type="pullback",
        initial_stop_atr_mult=1.5,
        trailing_mode=TrailingMode.ATR,
        trailing_atr_mult=2.0,
        breakeven_r_target=1.0,
        scale_out_r_targets=[1.0, 2.0, 3.0],
        description="Stop below pullback low, break-even at 1R"
    ),
    "mean_reversion": SetupStopRules(
        setup_type="mean_reversion",
        initial_stop_atr_mult=2.5,
        trailing_mode=TrailingMode.PERCENT,
        trailing_atr_mult=3.0,
        breakeven_r_target=0.75,
        scale_out_r_targets=[0.75, 1.5],
        max_stop_pct=0.10,
        use_swing_levels=False,
        description="Wider stops for counter-trend, quick profit-taking"
    ),
    "momentum": SetupStopRules(
        setup_type="momentum",
        initial_stop_atr_mult=1.0,
        trailing_mode=TrailingMode.PARABOLIC,
        trailing_atr_mult=1.5,
        breakeven_r_target=0.5,
        scale_out_r_targets=[0.5, 1.0, 2.0, 3.0],
        min_stop_pct=0.01,
        description="Tight stops, aggressive trailing"
    ),
    "gap_and_go": SetupStopRules(
        setup_type="gap_and_go",
        initial_stop_atr_mult=0.75,
        trailing_mode=TrailingMode.BREAKEVEN_PLUS,
        trailing_atr_mult=1.0,
        breakeven_r_target=0.5,
        scale_out_r_targets=[0.5, 1.0, 1.5],
        min_stop_pct=0.005,
        use_swing_levels=False,
        description="Stop below gap low, move to BE quickly"
    ),
    "vwap_reversal": SetupStopRules(
        setup_type="vwap_reversal",
        initial_stop_atr_mult=1.5,
        trailing_mode=TrailingMode.ATR,
        trailing_atr_mult=2.0,
        breakeven_r_target=1.0,
        scale_out_r_targets=[1.0, 2.0],
        description="Stop beyond VWAP deviation, volume aware"
    ),
    "earnings_play": SetupStopRules(
        setup_type="earnings_play",
        initial_stop_atr_mult=3.0,
        trailing_mode=TrailingMode.PERCENT,
        trailing_atr_mult=4.0,
        breakeven_r_target=1.5,
        scale_out_r_targets=[1.5, 3.0],
        max_stop_pct=0.15,
        respect_regime=False,
        description="Wide stops for earnings volatility"
    ),
    "default": SetupStopRules(
        setup_type="default",
        initial_stop_atr_mult=1.5,
        trailing_mode=TrailingMode.ATR,
        trailing_atr_mult=2.0,
        breakeven_r_target=1.0,
        scale_out_r_targets=[1.0, 2.0, 3.0],
        description="Standard balanced approach"
    )
}


# ============================================================================
# MAIN SERVICE CLASS
# ============================================================================

class SmartStopService:
    """
    Unified Smart Stop System - One service for all stop loss needs.
    
    Combines:
    - 6 stop modes (original, atr_dynamic, anti_hunt, volatility_adjusted, layered, chandelier)
    - 8 setup-based rule sets
    - Volume profile analysis
    - Stop hunt detection
    - Sector correlation
    - Regime awareness
    """
    
    def __init__(self, config: SmartStopConfig = None):
        self.config = config or SmartStopConfig()
        self.setup_rules = SETUP_STOP_RULES
        
        # External services (injected)
        self._regime_service = None
        self._sector_service = None
        self._data_service = None
        self._db = None  # MongoDB connection for historical data
    
    def inject_services(self, regime_service=None, sector_service=None, data_service=None):
        """Inject external services for enhanced analysis"""
        self._regime_service = regime_service
        self._sector_service = sector_service
        self._data_service = data_service
    
    def set_db(self, db):
        """Set MongoDB connection for historical data access"""
        self._db = db
    
    async def _get_historical_bars_from_db(self, symbol: str, limit: int = 50) -> Optional[pd.DataFrame]:
        """
        Get historical bars from unified ib_historical_data collection.
        Used for ATR calculation, volume profile, and other analysis.
        """
        if self._db is None:
            return None
        
        try:
            bars = list(self._db["ib_historical_data"].find(
                {"symbol": symbol.upper(), "bar_size": "1 day"},
                {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
            ).sort("date", -1).limit(limit))
            
            if bars and len(bars) >= 10:
                df = pd.DataFrame(bars)
                # Rename columns if needed
                if 'date' in df.columns:
                    df = df.rename(columns={'date': 'timestamp'})
                return df
        except Exception as e:
            logger.warning(f"Error fetching historical bars for {symbol}: {e}")
        
        return None
    
    # ========================================================================
    # MAIN ENTRY POINTS
    # ========================================================================
    
    def calculate_stop(
        self,
        entry_price: float,
        direction: str,
        symbol: str,
        atr: float,
        mode: StopMode = None,
        support_level: float = None,
        resistance_level: float = None,
        swing_low: float = None,
        swing_high: float = None,
        volatility_regime: str = "normal"
    ) -> Dict[str, Any]:
        """
        Simple stop calculation using a specific mode.
        
        Use this for quick calculations without full analysis.
        For comprehensive analysis, use calculate_intelligent_stop().
        """
        mode = mode or self.config.default_mode
        
        if mode == StopMode.ORIGINAL:
            return self._calc_original_stop(entry_price, direction, atr, swing_low, swing_high, support_level, resistance_level)
        elif mode == StopMode.ATR_DYNAMIC:
            return self._calc_atr_stop(entry_price, direction, atr)
        elif mode == StopMode.ANTI_HUNT:
            return self._calc_anti_hunt_stop(entry_price, direction, atr, swing_low, swing_high, support_level, resistance_level)
        elif mode == StopMode.VOLATILITY_ADJUSTED:
            return self._calc_volatility_stop(entry_price, direction, atr, volatility_regime)
        elif mode == StopMode.LAYERED:
            return self._calc_layered_stop(entry_price, direction, atr)
        elif mode == StopMode.CHANDELIER:
            return self._calc_chandelier_stop(entry_price, direction, atr, swing_high, swing_low)
        else:
            return self._calc_atr_stop(entry_price, direction, atr)
    
    async def calculate_intelligent_stop(
        self,
        symbol: str,
        entry_price: float,
        current_price: float,
        direction: str,
        setup_type: str,
        position_size: int,
        atr: float,
        swing_low: float = None,
        swing_high: float = None,
        support_levels: List[float] = None,
        resistance_levels: List[float] = None,
        historical_bars: pd.DataFrame = None,
        float_shares: float = None,
        avg_volume: float = None,
        max_risk_dollars: float = None,
        max_risk_percent: float = 0.02
    ) -> SmartStopResult:
        """
        Full intelligent stop calculation with all analysis factors.
        
        This is the comprehensive method that considers:
        - Setup-specific rules
        - Volume profile
        - Stop hunt risk
        - Sector correlation
        - Regime context
        - Layered exits
        - Scale-out plans
        """
        factors = []
        warnings = []
        
        # Auto-fetch historical bars from ib_historical_data if not provided
        if historical_bars is None:
            historical_bars = await self._get_historical_bars_from_db(symbol, limit=50)
            if historical_bars is not None:
                factors.append("Using IB historical data for volume profile")
        
        # 1. Get setup rules
        rules = self._get_setup_rules(setup_type)
        factors.append(f"Setup: {rules.setup_type}")
        
        # 2. Volume profile analysis
        volume_profile = None
        volume_support = None
        if historical_bars is not None and len(historical_bars) >= 20:
            volume_profile = self._calculate_volume_profile(historical_bars)
            if direction == 'long':
                volume_support = volume_profile.get_nearest_support(current_price)
            else:
                volume_support = volume_profile.get_nearest_resistance(current_price)
            if volume_support:
                factors.append(f"Volume {'support' if direction == 'long' else 'resistance'}: ${volume_support:.2f}")
        
        # 3. Stop hunt risk assessment
        hunt_risk = self._assess_hunt_risk(
            current_price, direction, atr,
            swing_low, swing_high, support_levels, resistance_levels,
            float_shares, avg_volume
        )
        factors.append(f"Hunt risk: {hunt_risk['level']}")
        if hunt_risk['level'] == 'HIGH':
            warnings.append(f"High stop-hunt risk near {hunt_risk['obvious_levels']}")
        
        # 4. Sector context
        sector_adjustment = 1.0
        if self._sector_service:
            try:
                sector_adj = await self._get_sector_adjustment(symbol, direction)
                if sector_adj != 1.0:
                    sector_adjustment = sector_adj
                    factors.append(f"Sector adjustment: {sector_adj:.2f}x")
            except Exception as e:
                logger.warning(f"Sector analysis failed: {e}")
        
        # 5. Regime context
        regime_adjustment = 1.0
        regime_name = "HOLD"
        if self._regime_service and rules.respect_regime:
            try:
                regime_data = await self._regime_service.get_current_regime()
                regime_name = regime_data.get("state", "HOLD")
                regime_adjustment = self._get_regime_multiplier(regime_name, direction)
                factors.append(f"Regime: {regime_name} (adj: {regime_adjustment:.2f}x)")
            except Exception as e:
                logger.warning(f"Regime fetch failed: {e}")
        
        # 6. Calculate base stop
        base_stop = self._calculate_base_stop(
            entry_price, direction, atr, rules,
            swing_low, swing_high, support_levels, resistance_levels, volume_profile
        )
        
        # 7. Apply adjustments
        adjusted_stop = base_stop
        anti_hunt_buffer = 0
        
        # Sector adjustment
        if sector_adjustment != 1.0:
            adj = (base_stop - entry_price) * (sector_adjustment - 1)
            adjusted_stop += adj if direction == 'long' else -adj
        
        # Regime adjustment
        if regime_adjustment != 1.0:
            adj = (adjusted_stop - entry_price) * (regime_adjustment - 1)
            adjusted_stop += adj if direction == 'long' else -adj
        
        # Anti-hunt buffer for high risk
        if hunt_risk['level'] == 'HIGH':
            anti_hunt_buffer = atr * self.config.anti_hunt_extra_atr
            adjusted_stop = adjusted_stop - anti_hunt_buffer if direction == 'long' else adjusted_stop + anti_hunt_buffer
            factors.append(f"Anti-hunt buffer: ${anti_hunt_buffer:.2f}")
        
        # 8. Enforce constraints
        adjusted_stop = self._enforce_constraints(
            adjusted_stop, entry_price, direction,
            rules.min_stop_pct, rules.max_stop_pct,
            max_risk_dollars, position_size
        )
        
        # 9. Avoid round numbers
        if self.config.avoid_round_numbers:
            adjusted_stop = self._avoid_round_number(adjusted_stop, direction)
        
        # 10. Calculate derived values
        stop_distance_pct = abs(adjusted_stop - entry_price) / entry_price
        stop_distance_atr = abs(adjusted_stop - entry_price) / atr if atr > 0 else 0
        
        # 11. Trailing configuration
        trailing_trigger = self._calc_trailing_trigger(entry_price, direction, atr, rules)
        breakeven_trigger = self._calc_breakeven_trigger(entry_price, direction, atr, rules)
        
        # 12. Layered stops
        layered_stops = self._create_layered_stops(entry_price, direction, atr)
        
        # 13. Scale-out plan
        scale_out_plan = self._create_scale_out_plan(entry_price, direction, atr, rules, position_size)
        
        # 14. Urgency
        urgency = self._determine_urgency(current_price, adjusted_stop, direction, hunt_risk, regime_name)
        
        # 15. Confidence
        confidence = self._calculate_confidence(factors, warnings, volume_profile is not None, rules.setup_type != "default")
        
        # 16. Primary factor
        primary_factor = self._determine_primary_factor(rules, volume_profile, hunt_risk)
        
        return SmartStopResult(
            stop_price=round(adjusted_stop, 2),
            stop_distance_pct=round(stop_distance_pct, 4),
            stop_distance_atr=round(stop_distance_atr, 2),
            stop_mode=rules.trailing_mode.value,
            primary_factor=primary_factor,
            factors_considered=factors,
            confidence=confidence,
            hunt_risk=hunt_risk['level'],
            hunt_risk_score=hunt_risk['score'],
            urgency=urgency,
            warnings=warnings,
            trailing_mode=rules.trailing_mode,
            trailing_trigger_price=round(trailing_trigger, 2),
            breakeven_trigger_price=round(breakeven_trigger, 2),
            layered_stops=layered_stops,
            scale_out_plan=scale_out_plan,
            volume_profile_support=round(volume_support, 2) if volume_support else None,
            sector_adjustment=round(sector_adjustment, 2),
            regime_adjustment=round(regime_adjustment, 2),
            setup_rules_used=rules.setup_type,
            obvious_zones_avoided=hunt_risk.get('obvious_levels', []),
            anti_hunt_buffer_applied=round(anti_hunt_buffer, 2),
            symbol=symbol,
            entry_price=entry_price,
            direction=direction,
            calculated_at=datetime.now(timezone.utc).isoformat(),
            valid_until=(datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        )
    
    def compare_all_modes(
        self,
        entry_price: float,
        direction: str,
        atr: float,
        support: float = None,
        resistance: float = None
    ) -> Dict[str, Dict]:
        """Compare all stop modes for a given setup"""
        results = {}
        for mode in StopMode:
            try:
                result = self.calculate_stop(
                    entry_price=entry_price,
                    direction=direction,
                    symbol="COMPARE",
                    atr=atr,
                    mode=mode,
                    support_level=support,
                    resistance_level=resistance
                )
                risk_pct = abs(entry_price - result['stop_price']) / entry_price * 100
                results[mode.value] = {
                    'stop_price': result['stop_price'],
                    'risk_percent': round(risk_pct, 2),
                    'hunt_risk': result.get('hunt_risk', 'MEDIUM'),
                    'reasoning': result.get('stop_reasoning', '')
                }
            except Exception as e:
                results[mode.value] = {'error': str(e)}
        return results
    
    def get_recommended_mode(
        self,
        symbol: str,
        float_shares: float = None,
        avg_volume: float = None,
        volatility_regime: str = "normal",
        time_of_day: str = "regular"
    ) -> StopMode:
        """Recommend best stop mode based on stock characteristics"""
        if float_shares and float_shares < self.config.low_float_threshold:
            return StopMode.ANTI_HUNT
        if avg_volume and avg_volume < self.config.low_volume_threshold:
            return StopMode.ANTI_HUNT
        if volatility_regime in ['high', 'extreme']:
            return StopMode.VOLATILITY_ADJUSTED
        if time_of_day in ['premarket', 'afterhours']:
            return StopMode.ANTI_HUNT
        return StopMode.ATR_DYNAMIC
    
    # ========================================================================
    # STOP MODE CALCULATIONS
    # ========================================================================
    
    def _calc_original_stop(self, entry, direction, atr, swing_low, swing_high, support, resistance):
        """Traditional stop with small buffer"""
        buffer = atr * 0.3
        if direction == 'long':
            base = swing_low or support or (entry * 0.98)
            stop = round(base - buffer, 2)
        else:
            base = swing_high or resistance or (entry * 1.02)
            stop = round(base + buffer, 2)
        return {
            'stop_price': stop,
            'stop_reasoning': f"Traditional stop {'below' if direction == 'long' else 'above'} key level with small buffer",
            'buffer_applied': buffer,
            'hunt_risk': 'HIGH'
        }
    
    def _calc_atr_stop(self, entry, direction, atr):
        """ATR-based dynamic stop"""
        buffer = atr * self.config.atr_multiplier
        if direction == 'long':
            stop = round(entry - buffer, 2)
        else:
            stop = round(entry + buffer, 2)
        return {
            'stop_price': stop,
            'stop_reasoning': f"ATR-dynamic: Entry {'minus' if direction == 'long' else 'plus'} {self.config.atr_multiplier}x ATR",
            'buffer_applied': buffer,
            'hunt_risk': 'MEDIUM'
        }
    
    def _calc_anti_hunt_stop(self, entry, direction, atr, swing_low, swing_high, support, resistance):
        """Stop beyond obvious levels to avoid sweeps"""
        obvious_zones = []
        
        if direction == 'long':
            for level in [swing_low, support]:
                if level and level < entry:
                    obvious_zones.append(level)
            deepest = min(obvious_zones) if obvious_zones else entry * 0.97
            buffer = atr * 1.5
            stop = round(deepest - buffer, 2)
        else:
            for level in [swing_high, resistance]:
                if level and level > entry:
                    obvious_zones.append(level)
            deepest = max(obvious_zones) if obvious_zones else entry * 1.03
            buffer = atr * 1.5
            stop = round(deepest + buffer, 2)
        
        return {
            'stop_price': stop,
            'stop_reasoning': "Anti-hunt: Beyond obvious levels with 1.5x ATR buffer",
            'buffer_applied': buffer,
            'obvious_zones_avoided': obvious_zones,
            'hunt_risk': 'LOW'
        }
    
    def _calc_volatility_stop(self, entry, direction, atr, vol_regime):
        """Volatility-adjusted stop"""
        multipliers = {'low': 1.0, 'normal': 1.5, 'high': 2.5, 'extreme': 3.0}
        mult = multipliers.get(vol_regime, 1.5)
        buffer = atr * mult
        if direction == 'long':
            stop = round(entry - buffer, 2)
        else:
            stop = round(entry + buffer, 2)
        return {
            'stop_price': stop,
            'stop_reasoning': f"Volatility-adjusted ({vol_regime}): {mult}x ATR",
            'buffer_applied': buffer,
            'volatility_multiplier': mult,
            'hunt_risk': 'LOW' if vol_regime in ['high', 'extreme'] else 'MEDIUM'
        }
    
    def _calc_layered_stop(self, entry, direction, atr):
        """Layered stops for partial exits"""
        layers = []
        for i, (pct, depth) in enumerate(zip(self.config.layer_percentages, self.config.layer_atr_depths)):
            buffer = atr * depth
            if direction == 'long':
                stop = round(entry - buffer, 2)
            else:
                stop = round(entry + buffer, 2)
            layers.append({
                'level': i + 1,
                'stop_price': stop,
                'position_pct': pct,
                'atr_depth': depth
            })
        return {
            'stop_price': layers[0]['stop_price'],
            'stop_reasoning': f"Layered: {len(layers)} levels at {self.config.layer_atr_depths} ATR depths",
            'buffer_applied': atr * self.config.layer_atr_depths[0],
            'layered_stops': layers,
            'hunt_risk': 'LOW'
        }
    
    def _calc_chandelier_stop(self, entry, direction, atr, swing_high, swing_low):
        """Chandelier exit from high/low"""
        buffer = atr * self.config.chandelier_multiplier
        if direction == 'long':
            ref = swing_high if swing_high and swing_high >= entry else entry
            stop = round(ref - buffer, 2)
        else:
            ref = swing_low if swing_low and swing_low <= entry else entry
            stop = round(ref + buffer, 2)
        return {
            'stop_price': stop,
            'stop_reasoning': f"Chandelier: Reference ${ref:.2f} minus {self.config.chandelier_multiplier}x ATR",
            'buffer_applied': buffer,
            'reference_price': ref,
            'hunt_risk': 'MEDIUM'
        }
    
    # ========================================================================
    # HELPER METHODS
    # ========================================================================
    
    def _get_setup_rules(self, setup_type: str) -> SetupStopRules:
        """Get rules for a setup type"""
        normalized = setup_type.lower().replace(" ", "_").replace("-", "_")
        if normalized in self.setup_rules:
            return self.setup_rules[normalized]
        for key in self.setup_rules:
            if key in normalized or normalized in key:
                return self.setup_rules[key]
        return self.setup_rules["default"]
    
    def _calculate_volume_profile(self, df: pd.DataFrame) -> VolumeProfile:
        """Calculate volume profile from price data"""
        if len(df) < 20:
            return VolumeProfile(
                poc=df['close'].mean(), vah=df['high'].max(), val=df['low'].min(),
                hvn_levels=[], lvn_levels=[], total_volume=df['volume'].sum()
            )
        
        price_min, price_max = df['low'].min(), df['high'].max()
        num_bins = min(50, max(20, int((price_max - price_min) / (df['close'].mean() * 0.005))))
        bins = np.linspace(price_min, price_max, num_bins + 1)
        bin_centers = (bins[:-1] + bins[1:]) / 2
        volume_at_price = np.zeros(num_bins)
        
        for _, row in df.iterrows():
            for i, (bin_low, bin_high) in enumerate(zip(bins[:-1], bins[1:])):
                overlap_low = max(row['low'], bin_low)
                overlap_high = min(row['high'], bin_high)
                if overlap_high > overlap_low:
                    bar_range = row['high'] - row['low']
                    overlap_pct = (overlap_high - overlap_low) / bar_range if bar_range > 0 else 0
                    volume_at_price[i] += row['volume'] * overlap_pct
        
        poc_idx = np.argmax(volume_at_price)
        poc = bin_centers[poc_idx]
        
        # Value area (70% of volume)
        total_vol = volume_at_price.sum()
        target_vol = total_vol * 0.70
        low_idx, high_idx = poc_idx, poc_idx
        current_vol = volume_at_price[poc_idx]
        
        while current_vol < target_vol and (low_idx > 0 or high_idx < num_bins - 1):
            low_vol = volume_at_price[low_idx - 1] if low_idx > 0 else 0
            high_vol = volume_at_price[high_idx + 1] if high_idx < num_bins - 1 else 0
            if low_vol >= high_vol and low_idx > 0:
                low_idx -= 1
                current_vol += low_vol
            elif high_idx < num_bins - 1:
                high_idx += 1
                current_vol += high_vol
            else:
                break
        
        val, vah = bin_centers[low_idx], bin_centers[high_idx]
        
        # HVN/LVN
        avg_vol, std_vol = volume_at_price.mean(), volume_at_price.std()
        hvn = [bin_centers[i] for i, v in enumerate(volume_at_price) if v > avg_vol + std_vol]
        lvn = [bin_centers[i] for i, v in enumerate(volume_at_price) if v < avg_vol - 0.5 * std_vol]
        
        return VolumeProfile(
            poc=round(poc, 2), vah=round(vah, 2), val=round(val, 2),
            hvn_levels=[round(h, 2) for h in hvn[:5]],
            lvn_levels=[round(l, 2) for l in lvn[:5]],
            total_volume=total_vol
        )
    
    def _assess_hunt_risk(self, price, direction, atr, swing_low, swing_high, supports, resistances, float_shares, avg_volume):
        """Assess stop hunt risk"""
        score = 0
        obvious = []
        
        # Proximity to key levels
        levels = ([swing_low] + (supports or [])) if direction == 'long' else ([swing_high] + (resistances or []))
        for level in [l for l in levels if l]:
            if abs(price - level) / price < self.config.obvious_level_proximity_pct:
                score += 30
                obvious.append(f"${level:.2f}")
        
        # Round numbers
        for div in [100, 50, 25]:
            nearest = round(price / div) * div
            if abs(price - nearest) / price < 0.01:
                score += 20
                if f"${nearest:.0f}" not in obvious:
                    obvious.append(f"${nearest:.0f}")
        
        # Float/volume
        if float_shares and float_shares < self.config.low_float_threshold:
            score += 25
        if avg_volume and avg_volume < self.config.low_volume_threshold:
            score += 25
        
        level = 'HIGH' if score >= 50 else 'MEDIUM' if score >= 30 else 'LOW'
        return {'level': level, 'score': min(100, score), 'obvious_levels': obvious}
    
    async def _get_sector_adjustment(self, symbol, direction):
        """Get sector-based adjustment"""
        try:
            ctx = await self._sector_service.get_stock_sector_context(symbol)
            if not ctx:
                return 1.0
            stock_chg = getattr(ctx, 'stock_change_pct', 0) or 0
            sector_chg = getattr(ctx, 'sector_change_pct', 0) or 0
            if stock_chg < -1.0 and sector_chg > -0.5:
                return 0.8  # Tighten
            if stock_chg > -0.5 and sector_chg < -1.5:
                return 1.2  # Widen - showing relative strength
            return 1.0
        except Exception:
            return 1.0
    
    def _get_regime_multiplier(self, regime, direction):
        """Get regime-based multiplier"""
        adjustments = {
            "RISK_ON": {"long": 0.9, "short": 1.3},
            "HOLD": {"long": 1.0, "short": 1.0},
            "RISK_OFF": {"long": 1.2, "short": 1.0},
            "CONFIRMED_DOWN": {"long": 1.4, "short": 0.85}
        }
        return adjustments.get(regime, {}).get(direction, 1.0)
    
    def _calculate_base_stop(self, entry, direction, atr, rules, swing_low, swing_high, supports, resistances, vol_profile):
        """Calculate base stop price"""
        candidates = []
        
        # ATR-based
        atr_dist = atr * rules.initial_stop_atr_mult
        atr_stop = (entry - atr_dist) if direction == 'long' else (entry + atr_dist)
        candidates.append(atr_stop)
        
        # Swing levels
        if rules.use_swing_levels:
            if direction == 'long' and swing_low and swing_low < entry:
                candidates.append(swing_low - atr * 0.3)
            elif direction == 'short' and swing_high and swing_high > entry:
                candidates.append(swing_high + atr * 0.3)
        
        # Support/resistance
        if supports and direction == 'long':
            below = [s for s in supports if s < entry]
            if below:
                candidates.append(max(below) - atr * 0.3)
        elif resistances and direction == 'short':
            above = [r for r in resistances if r > entry]
            if above:
                candidates.append(min(above) + atr * 0.3)
        
        # Volume profile
        if rules.use_volume_profile and vol_profile:
            if direction == 'long':
                vol_sup = vol_profile.get_nearest_support(entry)
                if vol_sup:
                    candidates.append(vol_sup - atr * 0.5)
            else:
                vol_res = vol_profile.get_nearest_resistance(entry)
                if vol_res:
                    candidates.append(vol_res + atr * 0.5)
        
        # Select best (most protective but reasonable)
        if direction == 'long':
            valid = [c for c in candidates if c < entry]
            return max(valid) if valid else atr_stop
        else:
            valid = [c for c in candidates if c > entry]
            return min(valid) if valid else atr_stop
    
    def _enforce_constraints(self, stop, entry, direction, min_pct, max_pct, max_dollars, position_size):
        """Enforce stop constraints"""
        min_dist = entry * min_pct
        max_dist = entry * max_pct
        
        if direction == 'long':
            stop = max(entry - max_dist, min(entry - min_dist, stop))
        else:
            stop = min(entry + max_dist, max(entry + min_dist, stop))
        
        if max_dollars and position_size > 0:
            max_per_share = max_dollars / position_size
            if direction == 'long':
                stop = max(stop, entry - max_per_share)
            else:
                stop = min(stop, entry + max_per_share)
        
        return stop
    
    def _avoid_round_number(self, stop, direction):
        """Adjust stop to avoid round numbers"""
        for div in [100, 50, 25, 10]:
            nearest = round(stop / div) * div
            if abs(stop - nearest) / stop < self.config.round_number_buffer_pct:
                buffer = stop * self.config.round_number_buffer_pct
                stop = (nearest - buffer) if direction == 'long' else (nearest + buffer)
                break
        return round(stop, 2)
    
    def _calc_trailing_trigger(self, entry, direction, atr, rules):
        """Calculate trailing stop trigger price"""
        risk = atr * rules.initial_stop_atr_mult
        if direction == 'long':
            return entry + risk
        return entry - risk
    
    def _calc_breakeven_trigger(self, entry, direction, atr, rules):
        """Calculate break-even trigger price"""
        risk = atr * rules.initial_stop_atr_mult
        profit = risk * rules.breakeven_r_target
        if direction == 'long':
            return entry + profit
        return entry - profit
    
    def _create_layered_stops(self, entry, direction, atr):
        """Create layered stops"""
        layers = []
        for i, (pct, depth) in enumerate(zip(self.config.layer_percentages, self.config.layer_atr_depths)):
            buffer = atr * depth
            stop = (entry - buffer) if direction == 'long' else (entry + buffer)
            stop = self._avoid_round_number(stop, direction)
            layers.append({'level': i + 1, 'stop_price': round(stop, 2), 'position_pct': pct, 'atr_depth': depth})
        return layers
    
    def _create_scale_out_plan(self, entry, direction, atr, rules, position_size):
        """Create scale-out profit plan"""
        if not rules.scale_out_r_targets:
            return []
        risk = atr * rules.initial_stop_atr_mult
        plan = []
        remaining = 1.0
        for i, r_target in enumerate(rules.scale_out_r_targets):
            profit = risk * r_target
            target = (entry + profit) if direction == 'long' else (entry - profit)
            exit_pct = 0.25 if i < len(rules.scale_out_r_targets) - 1 else remaining
            plan.append({
                'level': i + 1, 'r_target': r_target, 'target_price': round(target, 2),
                'exit_pct': exit_pct, 'shares': int(position_size * exit_pct)
            })
            remaining -= exit_pct
        return plan
    
    def _determine_urgency(self, current, stop, direction, hunt_risk, regime):
        """Determine stop management urgency"""
        dist_pct = (current - stop) / current if direction == 'long' else (stop - current) / current
        if dist_pct < 0.01:
            return StopUrgency.EMERGENCY
        if hunt_risk['level'] == 'HIGH' and dist_pct < 0.02:
            return StopUrgency.HIGH_ALERT
        if regime == 'CONFIRMED_DOWN' and direction == 'long':
            return StopUrgency.CAUTION
        return StopUrgency.NORMAL
    
    def _calculate_confidence(self, factors, warnings, has_volume, has_setup):
        """Calculate confidence score"""
        conf = 60
        if has_volume:
            conf += 15
        if has_setup:
            conf += 10
        conf -= len(warnings) * 5
        return max(30, min(100, conf))
    
    def _determine_primary_factor(self, rules, volume_profile, hunt_risk):
        """Determine primary decision factor"""
        if hunt_risk['level'] == 'HIGH':
            return "Anti-hunt protection (high manipulation risk)"
        if rules.setup_type != "default":
            return f"Setup rules ({rules.setup_type})"
        if volume_profile:
            return "Volume profile support/resistance"
        return "ATR-based standard stop"


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

_smart_stop_service: SmartStopService = None


def get_smart_stop_service() -> SmartStopService:
    global _smart_stop_service
    if _smart_stop_service is None:
        _smart_stop_service = SmartStopService()
    return _smart_stop_service


def init_smart_stop_service(config: SmartStopConfig = None, regime_service=None, sector_service=None, data_service=None) -> SmartStopService:
    global _smart_stop_service
    _smart_stop_service = SmartStopService(config=config)
    _smart_stop_service.inject_services(regime_service, sector_service, data_service)
    return _smart_stop_service
