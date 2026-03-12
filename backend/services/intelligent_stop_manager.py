"""
Intelligent Stop Manager - Advanced Stop Loss Management System
================================================================

Combines multiple factors to make the smartest possible stop decisions:

1. VOLUME PROFILE ANALYSIS
   - Point of Control (POC) - highest volume price
   - Value Area High/Low (VAH/VAL) - 70% of volume range
   - High Volume Nodes (HVN) - support/resistance
   - Low Volume Nodes (LVN) - fast price movement zones

2. LIQUIDITY/STOP HUNT DETECTION
   - Identify obvious stop clusters
   - Real-time sweep pattern detection
   - Institutional order flow awareness

3. SETUP-BASED STOP RULES
   - Different setups need different stop strategies
   - Breakout: Below breakout level
   - Pullback: Below pullback low
   - Mean reversion: Wider stops
   - Momentum: Tighter trailing

4. SECTOR/MARKET CORRELATION
   - Compare stock movement to sector
   - If sector holds but stock drops = concerning
   - Relative strength affects stop urgency

5. TRAILING STOP MODES
   - ATR-based trailing
   - Chandelier exit
   - Break-even after 1R
   - Parabolic acceleration

6. SUPPORT/RESISTANCE
   - Multi-timeframe levels
   - Volume-weighted levels
   - Historical pivots

7. REGIME CONTEXT
   - Wider in RISK_OFF/DOWN
   - Tighter trailing in RISK_ON
   - Quick exits in extreme volatility
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
from collections import defaultdict

logger = logging.getLogger(__name__)


class StopUrgency(Enum):
    """How urgently the stop should be tightened or executed"""
    NORMAL = "normal"           # Standard behavior
    CAUTION = "caution"         # Consider tightening
    HIGH_ALERT = "high_alert"   # Actively tighten
    EMERGENCY = "emergency"     # Execute immediately if possible


class TrailingMode(Enum):
    """Trailing stop behavior modes"""
    NONE = "none"               # Static stop
    ATR = "atr"                 # Trail by ATR
    PERCENT = "percent"         # Trail by percentage
    CHANDELIER = "chandelier"   # Trail from highest high
    BREAKEVEN_PLUS = "breakeven_plus"  # Break-even after profit target
    PARABOLIC = "parabolic"     # Accelerating trail


@dataclass
class VolumeProfile:
    """Volume profile analysis for a symbol"""
    poc: float                  # Point of Control (highest volume price)
    vah: float                  # Value Area High
    val: float                  # Value Area Low
    hvn_levels: List[float]     # High Volume Nodes
    lvn_levels: List[float]     # Low Volume Nodes
    total_volume: float
    analysis_period: str        # "daily", "weekly", etc.
    
    def get_nearest_support(self, current_price: float) -> Optional[float]:
        """Get nearest volume-based support below current price"""
        supports = [self.val, self.poc] + self.hvn_levels
        below = [s for s in supports if s < current_price]
        return max(below) if below else None
    
    def get_nearest_resistance(self, current_price: float) -> Optional[float]:
        """Get nearest volume-based resistance above current price"""
        resistances = [self.vah, self.poc] + self.hvn_levels
        above = [r for r in resistances if r > current_price]
        return min(above) if above else None
    
    def is_in_lvn(self, price: float, tolerance: float = 0.005) -> bool:
        """Check if price is in a low volume node (fast movement zone)"""
        for lvn in self.lvn_levels:
            if abs(price - lvn) / lvn < tolerance:
                return True
        return False


@dataclass
class SetupStopRules:
    """Stop rules specific to a trading setup type"""
    setup_type: str
    initial_stop_atr_mult: float = 1.5
    use_swing_levels: bool = True
    use_volume_profile: bool = True
    trailing_mode: TrailingMode = TrailingMode.ATR
    trailing_atr_mult: float = 2.0
    breakeven_r_target: float = 1.0  # Move to break-even after this R
    scale_out_levels: List[float] = field(default_factory=list)
    max_stop_distance_pct: float = 0.08
    min_stop_distance_pct: float = 0.02
    respect_regime: bool = True
    description: str = ""


# Default stop rules for different setup types
SETUP_STOP_RULES = {
    # Breakout trades - stop below breakout level
    "breakout": SetupStopRules(
        setup_type="breakout",
        initial_stop_atr_mult=1.0,
        use_swing_levels=True,
        trailing_mode=TrailingMode.CHANDELIER,
        trailing_atr_mult=2.5,
        breakeven_r_target=1.5,
        scale_out_levels=[1.5, 2.5, 4.0],
        description="Stop below breakout level, trail with chandelier after 1.5R"
    ),
    
    # Pullback trades - stop below pullback low
    "pullback": SetupStopRules(
        setup_type="pullback",
        initial_stop_atr_mult=1.5,
        use_swing_levels=True,
        trailing_mode=TrailingMode.ATR,
        trailing_atr_mult=2.0,
        breakeven_r_target=1.0,
        scale_out_levels=[1.0, 2.0, 3.0],
        description="Stop below pullback low, break-even at 1R"
    ),
    
    # Mean reversion - wider stops, quick exits
    "mean_reversion": SetupStopRules(
        setup_type="mean_reversion",
        initial_stop_atr_mult=2.5,
        use_swing_levels=False,
        trailing_mode=TrailingMode.PERCENT,
        trailing_atr_mult=3.0,
        breakeven_r_target=0.75,
        scale_out_levels=[0.75, 1.5],
        max_stop_distance_pct=0.10,
        description="Wider stops for counter-trend, quick profit-taking"
    ),
    
    # Momentum trades - tight trailing
    "momentum": SetupStopRules(
        setup_type="momentum",
        initial_stop_atr_mult=1.0,
        use_swing_levels=True,
        trailing_mode=TrailingMode.PARABOLIC,
        trailing_atr_mult=1.5,
        breakeven_r_target=0.5,
        scale_out_levels=[0.5, 1.0, 2.0, 3.0],
        min_stop_distance_pct=0.01,
        description="Tight stops, aggressive trailing, quick scale-outs"
    ),
    
    # Gap trades - specific gap rules
    "gap_and_go": SetupStopRules(
        setup_type="gap_and_go",
        initial_stop_atr_mult=0.75,
        use_swing_levels=False,
        trailing_mode=TrailingMode.BREAKEVEN_PLUS,
        trailing_atr_mult=1.0,
        breakeven_r_target=0.5,
        scale_out_levels=[0.5, 1.0, 1.5],
        min_stop_distance_pct=0.005,
        description="Stop below gap low, move to BE quickly"
    ),
    
    # VWAP plays
    "vwap_reversal": SetupStopRules(
        setup_type="vwap_reversal",
        initial_stop_atr_mult=1.5,
        use_swing_levels=True,
        use_volume_profile=True,
        trailing_mode=TrailingMode.ATR,
        trailing_atr_mult=2.0,
        breakeven_r_target=1.0,
        scale_out_levels=[1.0, 2.0],
        description="Stop beyond VWAP deviation, volume profile aware"
    ),
    
    # Earnings plays - wider stops
    "earnings_play": SetupStopRules(
        setup_type="earnings_play",
        initial_stop_atr_mult=3.0,
        use_swing_levels=False,
        trailing_mode=TrailingMode.PERCENT,
        trailing_atr_mult=4.0,
        breakeven_r_target=1.5,
        scale_out_levels=[1.5, 3.0],
        max_stop_distance_pct=0.15,
        respect_regime=False,  # Earnings override regime
        description="Wide stops for earnings volatility"
    ),
    
    # Default fallback
    "default": SetupStopRules(
        setup_type="default",
        initial_stop_atr_mult=1.5,
        use_swing_levels=True,
        trailing_mode=TrailingMode.ATR,
        trailing_atr_mult=2.0,
        breakeven_r_target=1.0,
        scale_out_levels=[1.0, 2.0, 3.0],
        description="Standard balanced approach"
    )
}


@dataclass
class SectorContext:
    """Sector and market context for a trade"""
    sector: str
    sector_change_pct: float      # Sector performance today
    stock_change_pct: float       # Stock performance today
    relative_strength: float      # Stock vs sector (-1 to 1)
    spy_change_pct: float         # SPY performance today
    is_sector_leader: bool
    is_sector_laggard: bool
    sector_trend: str             # "up", "down", "neutral"
    
    def get_stop_adjustment(self) -> float:
        """
        Get stop adjustment multiplier based on sector context.
        
        If stock is underperforming sector significantly = tighten
        If stock is outperforming while sector weak = give room
        """
        # Stock dropping while sector holds = concerning
        if self.stock_change_pct < -1.0 and self.sector_change_pct > -0.5:
            return 0.8  # Tighten stops by 20%
        
        # Stock holding while sector drops = relative strength
        if self.stock_change_pct > -0.5 and self.sector_change_pct < -1.5:
            return 1.2  # Widen stops by 20% - showing strength
        
        # Both moving together = normal
        return 1.0


@dataclass 
class IntelligentStopResult:
    """Result from intelligent stop calculation"""
    # Primary stop
    stop_price: float
    stop_distance_pct: float
    stop_distance_atr: float
    
    # Reasoning
    primary_factor: str           # What drove the stop decision
    factors_considered: List[str]
    confidence: float             # 0-100
    
    # Alerts
    urgency: StopUrgency
    warnings: List[str]
    
    # Trailing
    trailing_mode: TrailingMode
    trailing_trigger_price: float  # Price at which trailing activates
    breakeven_trigger_price: float
    
    # Layered exits
    layered_stops: List[Dict]
    scale_out_plan: List[Dict]
    
    # Context
    volume_profile_support: Optional[float]
    sector_adjustment: float
    regime_adjustment: float
    setup_rules: str
    
    # Metadata
    calculated_at: str
    valid_until: str              # Recalculate after this time


class IntelligentStopManager:
    """
    Advanced stop loss management combining multiple analysis factors.
    """
    
    def __init__(self):
        self.setup_rules = SETUP_STOP_RULES
        self._volume_cache = {}
        self._sector_cache = {}
        self._regime_service = None
        self._sector_service = None
        self._data_service = None
        
    def inject_services(
        self,
        regime_service=None,
        sector_service=None,
        data_service=None
    ):
        """Inject external services for enhanced analysis"""
        self._regime_service = regime_service
        self._sector_service = sector_service
        self._data_service = data_service
    
    async def calculate_intelligent_stop(
        self,
        symbol: str,
        entry_price: float,
        current_price: float,
        direction: str,  # 'long' or 'short'
        setup_type: str,
        position_size: int,
        atr: float,
        # Optional enhanced inputs
        swing_low: float = None,
        swing_high: float = None,
        support_levels: List[float] = None,
        resistance_levels: List[float] = None,
        historical_bars: pd.DataFrame = None,
        float_shares: float = None,
        avg_volume: float = None,
        # Risk parameters
        max_risk_dollars: float = None,
        max_risk_percent: float = 0.02,
        account_balance: float = None
    ) -> IntelligentStopResult:
        """
        Calculate the most intelligent stop loss considering all factors.
        
        This is the main entry point that orchestrates all analysis.
        """
        factors_considered = []
        warnings = []
        
        # Get setup-specific rules
        rules = self._get_setup_rules(setup_type)
        factors_considered.append(f"Setup: {rules.setup_type}")
        
        # 1. VOLUME PROFILE ANALYSIS
        volume_profile = None
        volume_support = None
        if historical_bars is not None and len(historical_bars) > 20:
            volume_profile = self._calculate_volume_profile(historical_bars)
            if direction == 'long':
                volume_support = volume_profile.get_nearest_support(current_price)
                if volume_support:
                    factors_considered.append(f"Volume support: ${volume_support:.2f}")
            else:
                volume_support = volume_profile.get_nearest_resistance(current_price)
                if volume_support:
                    factors_considered.append(f"Volume resistance: ${volume_support:.2f}")
        
        # 2. SECTOR/MARKET CONTEXT
        sector_context = await self._get_sector_context(symbol)
        sector_adjustment = 1.0
        if sector_context:
            sector_adjustment = sector_context.get_stop_adjustment()
            factors_considered.append(f"Sector: {sector_context.sector} (RS: {sector_context.relative_strength:.2f})")
            
            # Warning if stock diverging from sector
            if abs(sector_context.stock_change_pct - sector_context.sector_change_pct) > 2.0:
                warnings.append(f"Stock diverging from sector by {abs(sector_context.stock_change_pct - sector_context.sector_change_pct):.1f}%")
        
        # 3. REGIME CONTEXT
        regime_adjustment = 1.0
        regime_name = "HOLD"
        if self._regime_service:
            try:
                regime_data = await self._regime_service.get_current_regime()
                regime_name = regime_data.get("state", "HOLD")
                regime_adjustment = self._get_regime_adjustment(regime_name, direction)
                factors_considered.append(f"Regime: {regime_name} (adj: {regime_adjustment:.2f}x)")
            except Exception as e:
                logger.warning(f"Failed to get regime: {e}")
        
        # 4. STOP HUNT RISK ASSESSMENT
        hunt_risk = self._assess_stop_hunt_risk(
            symbol, current_price, direction, atr,
            swing_low, swing_high, support_levels, resistance_levels,
            float_shares, avg_volume
        )
        factors_considered.append(f"Hunt risk: {hunt_risk['level']}")
        
        if hunt_risk['level'] == 'HIGH':
            warnings.append(f"High stop-hunt risk near {hunt_risk['obvious_levels']}")
        
        # 5. CALCULATE BASE STOP
        base_stop = self._calculate_base_stop(
            entry_price, current_price, direction, atr, rules,
            swing_low, swing_high, support_levels, resistance_levels,
            volume_profile
        )
        
        # 6. APPLY ADJUSTMENTS
        adjusted_stop = base_stop
        
        # Sector adjustment
        if sector_adjustment != 1.0:
            adjustment = (base_stop - entry_price) * (sector_adjustment - 1)
            adjusted_stop += adjustment if direction == 'long' else -adjustment
        
        # Regime adjustment (if rules allow)
        if rules.respect_regime and regime_adjustment != 1.0:
            adjustment = (adjusted_stop - entry_price) * (regime_adjustment - 1)
            adjusted_stop += adjustment if direction == 'long' else -adjustment
        
        # Anti-hunt buffer for high-risk situations
        if hunt_risk['level'] == 'HIGH':
            anti_hunt_buffer = atr * 0.5
            if direction == 'long':
                adjusted_stop -= anti_hunt_buffer
            else:
                adjusted_stop += anti_hunt_buffer
            factors_considered.append(f"Anti-hunt buffer: ${anti_hunt_buffer:.2f}")
        
        # 7. ENFORCE CONSTRAINTS
        adjusted_stop = self._enforce_constraints(
            adjusted_stop, entry_price, direction, 
            rules.min_stop_distance_pct, rules.max_stop_distance_pct,
            max_risk_dollars, position_size
        )
        
        # 8. AVOID ROUND NUMBERS
        adjusted_stop = self._avoid_round_numbers(adjusted_stop, direction)
        
        # 9. CALCULATE DERIVED VALUES
        stop_distance_pct = abs(adjusted_stop - entry_price) / entry_price
        stop_distance_atr = abs(adjusted_stop - entry_price) / atr if atr > 0 else 0
        
        # 10. DETERMINE TRAILING BEHAVIOR
        trailing_mode = rules.trailing_mode
        trailing_trigger = self._calculate_trailing_trigger(
            entry_price, direction, atr, rules
        )
        breakeven_trigger = self._calculate_breakeven_trigger(
            entry_price, direction, atr, rules
        )
        
        # 11. CREATE LAYERED STOPS
        layered_stops = self._create_layered_stops(
            adjusted_stop, entry_price, direction, atr, rules
        )
        
        # 12. CREATE SCALE-OUT PLAN
        scale_out_plan = self._create_scale_out_plan(
            entry_price, direction, atr, rules, position_size
        )
        
        # 13. DETERMINE URGENCY
        urgency = self._determine_urgency(
            current_price, adjusted_stop, direction, 
            sector_context, regime_name, hunt_risk
        )
        
        # 14. CALCULATE CONFIDENCE
        confidence = self._calculate_confidence(
            factors_considered, warnings, volume_profile is not None,
            sector_context is not None, rules.setup_type != "default"
        )
        
        # Determine primary factor
        primary_factor = self._determine_primary_factor(
            rules, volume_profile, sector_context, hunt_risk
        )
        
        return IntelligentStopResult(
            stop_price=round(adjusted_stop, 2),
            stop_distance_pct=round(stop_distance_pct, 4),
            stop_distance_atr=round(stop_distance_atr, 2),
            primary_factor=primary_factor,
            factors_considered=factors_considered,
            confidence=confidence,
            urgency=urgency,
            warnings=warnings,
            trailing_mode=trailing_mode,
            trailing_trigger_price=round(trailing_trigger, 2),
            breakeven_trigger_price=round(breakeven_trigger, 2),
            layered_stops=layered_stops,
            scale_out_plan=scale_out_plan,
            volume_profile_support=round(volume_support, 2) if volume_support else None,
            sector_adjustment=round(sector_adjustment, 2),
            regime_adjustment=round(regime_adjustment, 2),
            setup_rules=rules.setup_type,
            calculated_at=datetime.now(timezone.utc).isoformat(),
            valid_until=(datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        )
    
    def _get_setup_rules(self, setup_type: str) -> SetupStopRules:
        """Get stop rules for a setup type"""
        # Normalize setup type
        normalized = setup_type.lower().replace(" ", "_").replace("-", "_")
        
        # Try exact match
        if normalized in self.setup_rules:
            return self.setup_rules[normalized]
        
        # Try partial match
        for key in self.setup_rules:
            if key in normalized or normalized in key:
                return self.setup_rules[key]
        
        # Return default
        return self.setup_rules["default"]
    
    def _calculate_volume_profile(
        self, 
        df: pd.DataFrame, 
        value_area_pct: float = 0.70
    ) -> VolumeProfile:
        """
        Calculate volume profile from price bars.
        
        Volume Profile shows where volume was transacted at each price level.
        - POC: Price with most volume (strongest S/R)
        - VAH/VAL: 70% of volume is between these levels
        - HVN: High volume nodes (likely S/R)
        - LVN: Low volume nodes (price moves fast through these)
        """
        if len(df) < 20:
            return VolumeProfile(
                poc=df['close'].mean(),
                vah=df['high'].max(),
                val=df['low'].min(),
                hvn_levels=[],
                lvn_levels=[],
                total_volume=df['volume'].sum(),
                analysis_period="insufficient_data"
            )
        
        # Create price bins
        price_min = df['low'].min()
        price_max = df['high'].max()
        num_bins = min(50, max(20, int((price_max - price_min) / (df['close'].mean() * 0.005))))
        
        bins = np.linspace(price_min, price_max, num_bins + 1)
        bin_centers = (bins[:-1] + bins[1:]) / 2
        
        # Distribute volume across price range for each bar
        volume_at_price = np.zeros(num_bins)
        
        for _, row in df.iterrows():
            bar_low, bar_high = row['low'], row['high']
            bar_volume = row['volume']
            
            # Find bins that this bar covers
            for i, (bin_low, bin_high) in enumerate(zip(bins[:-1], bins[1:])):
                # Calculate overlap between bar range and bin
                overlap_low = max(bar_low, bin_low)
                overlap_high = min(bar_high, bin_high)
                
                if overlap_high > overlap_low:
                    # Distribute volume proportionally
                    bar_range = bar_high - bar_low
                    overlap_pct = (overlap_high - overlap_low) / bar_range if bar_range > 0 else 0
                    volume_at_price[i] += bar_volume * overlap_pct
        
        # Find POC (highest volume price)
        poc_idx = np.argmax(volume_at_price)
        poc = bin_centers[poc_idx]
        
        # Calculate Value Area (70% of volume)
        total_vol = volume_at_price.sum()
        target_vol = total_vol * value_area_pct
        
        # Expand from POC until we have 70%
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
                low_idx -= 1
                current_vol += low_vol
        
        val = bin_centers[low_idx]
        vah = bin_centers[high_idx]
        
        # Find HVN and LVN
        avg_vol = volume_at_price.mean()
        std_vol = volume_at_price.std()
        
        hvn_levels = []
        lvn_levels = []
        
        for i, (vol, price) in enumerate(zip(volume_at_price, bin_centers)):
            if vol > avg_vol + std_vol:  # High volume node
                hvn_levels.append(price)
            elif vol < avg_vol - 0.5 * std_vol:  # Low volume node
                lvn_levels.append(price)
        
        return VolumeProfile(
            poc=round(poc, 2),
            vah=round(vah, 2),
            val=round(val, 2),
            hvn_levels=[round(h, 2) for h in hvn_levels[:5]],
            lvn_levels=[round(lvl, 2) for lvl in lvn_levels[:5]],
            total_volume=total_vol,
            analysis_period="custom"
        )
    
    async def _get_sector_context(self, symbol: str) -> Optional[SectorContext]:
        """Get sector and market context for a symbol"""
        if not self._sector_service:
            return None
        
        try:
            context = await self._sector_service.get_stock_sector_context(symbol)
            if not context:
                return None
            
            return SectorContext(
                sector=context.sector,
                sector_change_pct=context.sector_change_pct or 0,
                stock_change_pct=context.stock_change_pct or 0,
                relative_strength=context.relative_strength or 0,
                spy_change_pct=context.spy_change_pct or 0,
                is_sector_leader=context.is_sector_leader,
                is_sector_laggard=context.is_sector_laggard,
                sector_trend=context.sector_trend or "neutral"
            )
        except Exception as e:
            logger.warning(f"Failed to get sector context: {e}")
            return None
    
    def _get_regime_adjustment(self, regime: str, direction: str) -> float:
        """
        Get stop distance multiplier based on market regime.
        
        RISK_ON: Tighter stops okay (trend is favorable)
        RISK_OFF: Wider stops (choppy, more noise)
        CONFIRMED_DOWN: Wider for longs (fighting trend), tighter for shorts
        """
        adjustments = {
            "RISK_ON": {
                "long": 0.9,   # Trend favorable, can be tighter
                "short": 1.3   # Counter-trend, need more room
            },
            "HOLD": {
                "long": 1.0,
                "short": 1.0
            },
            "RISK_OFF": {
                "long": 1.2,   # Choppy market, need room
                "short": 1.0
            },
            "CONFIRMED_DOWN": {
                "long": 1.4,   # Fighting the trend, need room
                "short": 0.85  # Trend favorable for shorts
            }
        }
        
        return adjustments.get(regime, {}).get(direction, 1.0)
    
    def _assess_stop_hunt_risk(
        self,
        symbol: str,
        current_price: float,
        direction: str,
        atr: float,
        swing_low: float,
        swing_high: float,
        support_levels: List[float],
        resistance_levels: List[float],
        float_shares: float,
        avg_volume: float
    ) -> Dict[str, Any]:
        """
        Assess the risk of stop hunting at current levels.
        
        High risk if:
        - Price near obvious stop zones
        - Low float/volume (easier to manipulate)
        - Near round numbers
        - Near well-known technical levels
        """
        risk_score = 0
        obvious_levels = []
        
        # Check proximity to swing levels
        if direction == 'long':
            key_levels = [level for level in [swing_low] + (support_levels or []) if level]
            for level in key_levels:
                distance_pct = abs(current_price - level) / current_price
                if distance_pct < 0.02:  # Within 2%
                    risk_score += 30
                    obvious_levels.append(f"${level:.2f}")
        else:
            key_levels = [level for level in [swing_high] + (resistance_levels or []) if level]
            for level in key_levels:
                distance_pct = abs(current_price - level) / current_price
                if distance_pct < 0.02:
                    risk_score += 30
                    obvious_levels.append(f"${level:.2f}")
        
        # Check round numbers
        for divisor in [100, 50, 25]:
            nearest_round = round(current_price / divisor) * divisor
            if abs(current_price - nearest_round) / current_price < 0.01:
                risk_score += 20
                if f"${nearest_round:.0f}" not in obvious_levels:
                    obvious_levels.append(f"${nearest_round:.0f}")
        
        # Low float increases risk
        if float_shares and float_shares < 10_000_000:
            risk_score += 25
        elif float_shares and float_shares < 20_000_000:
            risk_score += 10
        
        # Low volume increases risk
        if avg_volume and avg_volume < 500_000:
            risk_score += 25
        elif avg_volume and avg_volume < 1_000_000:
            risk_score += 10
        
        # Determine risk level
        if risk_score >= 50:
            level = "HIGH"
        elif risk_score >= 30:
            level = "MEDIUM"
        else:
            level = "LOW"
        
        return {
            "level": level,
            "score": min(100, risk_score),
            "obvious_levels": obvious_levels,
            "factors": {
                "near_swing_levels": risk_score >= 30,
                "near_round_numbers": any("$" in lvl and lvl.replace("$", "").replace(".", "").isdigit() for lvl in obvious_levels),
                "low_float": float_shares and float_shares < 20_000_000,
                "low_volume": avg_volume and avg_volume < 1_000_000
            }
        }
    
    def _calculate_base_stop(
        self,
        entry_price: float,
        current_price: float,
        direction: str,
        atr: float,
        rules: SetupStopRules,
        swing_low: float,
        swing_high: float,
        support_levels: List[float],
        resistance_levels: List[float],
        volume_profile: VolumeProfile
    ) -> float:
        """Calculate the base stop before adjustments"""
        candidates = []
        
        # ATR-based stop
        atr_stop_distance = atr * rules.initial_stop_atr_mult
        if direction == 'long':
            atr_stop = entry_price - atr_stop_distance
            candidates.append(("atr", atr_stop))
        else:
            atr_stop = entry_price + atr_stop_distance
            candidates.append(("atr", atr_stop))
        
        # Swing level stop
        if rules.use_swing_levels:
            if direction == 'long' and swing_low and swing_low < entry_price:
                swing_stop = swing_low - (atr * 0.3)  # Small buffer below swing
                candidates.append(("swing", swing_stop))
            elif direction == 'short' and swing_high and swing_high > entry_price:
                swing_stop = swing_high + (atr * 0.3)
                candidates.append(("swing", swing_stop))
        
        # Support/Resistance stop
        if support_levels and direction == 'long':
            below_entry = [s for s in support_levels if s < entry_price]
            if below_entry:
                sr_stop = max(below_entry) - (atr * 0.3)
                candidates.append(("support", sr_stop))
        elif resistance_levels and direction == 'short':
            above_entry = [r for r in resistance_levels if r > entry_price]
            if above_entry:
                sr_stop = min(above_entry) + (atr * 0.3)
                candidates.append(("resistance", sr_stop))
        
        # Volume profile stop
        if rules.use_volume_profile and volume_profile:
            if direction == 'long':
                vol_support = volume_profile.get_nearest_support(current_price)
                if vol_support and vol_support < entry_price:
                    vol_stop = vol_support - (atr * 0.5)  # Deeper buffer for volume levels
                    candidates.append(("volume", vol_stop))
            else:
                vol_resist = volume_profile.get_nearest_resistance(current_price)
                if vol_resist and vol_resist > entry_price:
                    vol_stop = vol_resist + (atr * 0.5)
                    candidates.append(("volume", vol_stop))
        
        # Select best stop (most protective while reasonable)
        if direction == 'long':
            # For longs, lowest stop is most protective but might be too far
            # Choose the highest stop that's still below entry
            valid = [(name, price) for name, price in candidates if price < entry_price]
            if valid:
                return max(valid, key=lambda x: x[1])[1]
        else:
            # For shorts, highest stop is most protective
            valid = [(name, price) for name, price in candidates if price > entry_price]
            if valid:
                return min(valid, key=lambda x: x[1])[1]
        
        # Fallback to ATR stop
        return atr_stop
    
    def _enforce_constraints(
        self,
        stop_price: float,
        entry_price: float,
        direction: str,
        min_pct: float,
        max_pct: float,
        max_risk_dollars: float,
        position_size: int
    ) -> float:
        """Enforce min/max stop distance and dollar risk constraints"""
        # Percent constraints
        min_distance = entry_price * min_pct
        max_distance = entry_price * max_pct
        
        if direction == 'long':
            min_stop = entry_price - max_distance
            max_stop = entry_price - min_distance
            stop_price = max(min_stop, min(max_stop, stop_price))
        else:
            min_stop = entry_price + min_distance
            max_stop = entry_price + max_distance
            stop_price = min(max_stop, max(min_stop, stop_price))
        
        # Dollar risk constraint
        if max_risk_dollars and position_size > 0:
            max_per_share_risk = max_risk_dollars / position_size
            
            if direction == 'long':
                min_stop_by_dollars = entry_price - max_per_share_risk
                stop_price = max(stop_price, min_stop_by_dollars)
            else:
                max_stop_by_dollars = entry_price + max_per_share_risk
                stop_price = min(stop_price, max_stop_by_dollars)
        
        return stop_price
    
    def _avoid_round_numbers(self, stop_price: float, direction: str) -> float:
        """Adjust stop to avoid obvious round numbers"""
        buffer_pct = 0.002  # 0.2%
        
        for divisor in [100, 50, 25, 10]:
            nearest_round = round(stop_price / divisor) * divisor
            distance_pct = abs(stop_price - nearest_round) / stop_price
            
            if distance_pct < buffer_pct:
                buffer = stop_price * buffer_pct
                if direction == 'long':
                    stop_price = nearest_round - buffer
                else:
                    stop_price = nearest_round + buffer
                break
        
        return round(stop_price, 2)
    
    def _calculate_trailing_trigger(
        self,
        entry_price: float,
        direction: str,
        atr: float,
        rules: SetupStopRules
    ) -> float:
        """Calculate price at which trailing stop activates"""
        # Trail after 1R profit by default
        risk = atr * rules.initial_stop_atr_mult
        trigger_profit = risk * 1.0  # 1R
        
        if direction == 'long':
            return entry_price + trigger_profit
        else:
            return entry_price - trigger_profit
    
    def _calculate_breakeven_trigger(
        self,
        entry_price: float,
        direction: str,
        atr: float,
        rules: SetupStopRules
    ) -> float:
        """Calculate price at which stop moves to break-even"""
        risk = atr * rules.initial_stop_atr_mult
        trigger_profit = risk * rules.breakeven_r_target
        
        if direction == 'long':
            return entry_price + trigger_profit
        else:
            return entry_price - trigger_profit
    
    def _create_layered_stops(
        self,
        base_stop: float,
        entry_price: float,
        direction: str,
        atr: float,
        rules: SetupStopRules
    ) -> List[Dict]:
        """Create layered stop levels for partial exits"""
        layers = [
            {"level": 1, "pct": 0.40, "atr_mult": 1.0},
            {"level": 2, "pct": 0.30, "atr_mult": 1.5},
            {"level": 3, "pct": 0.30, "atr_mult": 2.0}
        ]
        
        result = []
        for layer in layers:
            buffer = atr * layer["atr_mult"]
            if direction == 'long':
                stop = entry_price - buffer
            else:
                stop = entry_price + buffer
            
            stop = self._avoid_round_numbers(stop, direction)
            
            result.append({
                "level": layer["level"],
                "stop_price": round(stop, 2),
                "position_pct": layer["pct"],
                "atr_depth": layer["atr_mult"]
            })
        
        return result
    
    def _create_scale_out_plan(
        self,
        entry_price: float,
        direction: str,
        atr: float,
        rules: SetupStopRules,
        position_size: int
    ) -> List[Dict]:
        """Create scale-out profit-taking plan"""
        if not rules.scale_out_levels:
            return []
        
        risk = atr * rules.initial_stop_atr_mult
        result = []
        
        remaining_pct = 1.0
        for i, r_target in enumerate(rules.scale_out_levels):
            # Calculate target price
            profit = risk * r_target
            if direction == 'long':
                target_price = entry_price + profit
            else:
                target_price = entry_price - profit
            
            # Determine exit percentage
            if i < len(rules.scale_out_levels) - 1:
                exit_pct = 0.25  # 25% at each intermediate target
            else:
                exit_pct = remaining_pct  # Rest at final target
            
            result.append({
                "level": i + 1,
                "r_target": r_target,
                "target_price": round(target_price, 2),
                "exit_pct": exit_pct,
                "shares": int(position_size * exit_pct)
            })
            
            remaining_pct -= exit_pct
        
        return result
    
    def _determine_urgency(
        self,
        current_price: float,
        stop_price: float,
        direction: str,
        sector_context: SectorContext,
        regime: str,
        hunt_risk: Dict
    ) -> StopUrgency:
        """Determine how urgently the stop should be managed"""
        # Check how close price is to stop
        if direction == 'long':
            distance_pct = (current_price - stop_price) / current_price
        else:
            distance_pct = (stop_price - current_price) / current_price
        
        # Very close to stop
        if distance_pct < 0.01:
            return StopUrgency.EMERGENCY
        
        # High hunt risk near stop
        if hunt_risk['level'] == 'HIGH' and distance_pct < 0.02:
            return StopUrgency.HIGH_ALERT
        
        # Stock diverging from sector in bad way
        if sector_context:
            if direction == 'long' and sector_context.stock_change_pct < sector_context.sector_change_pct - 1.5:
                return StopUrgency.CAUTION
            elif direction == 'short' and sector_context.stock_change_pct > sector_context.sector_change_pct + 1.5:
                return StopUrgency.CAUTION
        
        # Regime unfavorable
        if regime == 'CONFIRMED_DOWN' and direction == 'long':
            return StopUrgency.CAUTION
        
        return StopUrgency.NORMAL
    
    def _calculate_confidence(
        self,
        factors: List[str],
        warnings: List[str],
        has_volume_profile: bool,
        has_sector_context: bool,
        has_setup_rules: bool
    ) -> float:
        """Calculate confidence in the stop calculation"""
        base_confidence = 60
        
        # Add for each data source
        if has_volume_profile:
            base_confidence += 15
        if has_sector_context:
            base_confidence += 10
        if has_setup_rules:
            base_confidence += 10
        
        # Reduce for warnings
        base_confidence -= len(warnings) * 5
        
        return max(30, min(100, base_confidence))
    
    def _determine_primary_factor(
        self,
        rules: SetupStopRules,
        volume_profile: VolumeProfile,
        sector_context: SectorContext,
        hunt_risk: Dict
    ) -> str:
        """Determine the primary factor driving stop placement"""
        if hunt_risk['level'] == 'HIGH':
            return "Anti-hunt protection (high manipulation risk)"
        
        if rules.setup_type != "default":
            return f"Setup rules ({rules.setup_type})"
        
        if volume_profile:
            return "Volume profile support/resistance"
        
        if sector_context and abs(sector_context.get_stop_adjustment() - 1.0) > 0.1:
            return f"Sector divergence ({sector_context.sector})"
        
        return "ATR-based standard stop"


# Global instance
_intelligent_stop_manager: IntelligentStopManager = None


def get_intelligent_stop_manager() -> IntelligentStopManager:
    """Get or create the IntelligentStopManager instance"""
    global _intelligent_stop_manager
    if _intelligent_stop_manager is None:
        _intelligent_stop_manager = IntelligentStopManager()
    return _intelligent_stop_manager


def init_intelligent_stop_manager(
    regime_service=None,
    sector_service=None,
    data_service=None
) -> IntelligentStopManager:
    """Initialize the IntelligentStopManager with services"""
    global _intelligent_stop_manager
    _intelligent_stop_manager = IntelligentStopManager()
    _intelligent_stop_manager.inject_services(
        regime_service=regime_service,
        sector_service=sector_service,
        data_service=data_service
    )
    return _intelligent_stop_manager
