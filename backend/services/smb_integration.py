"""
SMB Capital Integration Module

This module provides the core SMB Capital trading methodology integration:
- Trade Style Classification (Move2Move / Trade2Hold / A+)
- SMB 5-Variable Scoring System
- Setup Categorization with Direction Bias
- Earnings Catalyst Scoring (-10 to +10)
- Setup Alias Mapping

Integrates with existing enhanced_scanner.py and ev_tracking_service.py
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


# ==================== TRADE STYLE CLASSIFICATION ====================

class TradeStyle(Enum):
    """
    Trade execution styles that determine how to manage the trade.
    
    SCALP: Quick in-and-out capturing immediate move (minutes to 1 hour)
    INTRADAY: Hold for intraday swing until Reason2Sell trigger (1-6 hours)
    MULTI_DAY: Max conviction multi-day hold when all 5 variables align (1-5 days)
    
    Note: "A+" now refers to GRADE (quality) not STYLE.
    A scalp can be A+ quality, and a multi-day hold can be C quality.
    """
    SCALP = "scalp"              # Target 1R, 60-70% win rate, minutes to 1 hour
    INTRADAY = "intraday"        # Target 3-5R, 40-50% win rate, 1-6 hours  
    MULTI_DAY = "multi_day"      # Target 10R+, max conviction, 1-5 days
    
    # Backwards compatibility aliases (deprecated - will be removed)
    MOVE_2_MOVE = "scalp"        # DEPRECATED: Use SCALP
    TRADE_2_HOLD = "intraday"    # DEPRECATED: Use INTRADAY
    A_PLUS = "multi_day"         # DEPRECATED: Use MULTI_DAY


class SetupDirection(Enum):
    """Primary direction bias for a setup"""
    LONG = "long"
    SHORT = "short"
    BOTH = "both"  # Can work either direction


class SetupCategory(Enum):
    """SMB-style setup categories"""
    TREND_MOMENTUM = "trend_momentum"      # Go with the flow
    CATALYST_DRIVEN = "catalyst_driven"    # News/earnings based
    REVERSAL = "reversal"                  # Counter-trend/mean reversion
    CONSOLIDATION = "consolidation"        # Flag breaks, squeezes
    SPECIALIZED = "specialized"            # Time-specific or unique


# ==================== SETUP CONFIGURATION ====================

@dataclass
class SetupConfig:
    """Configuration for a trading setup"""
    name: str                           # Canonical name (your naming)
    display_name: str                   # Human-readable name
    category: SetupCategory             # SMB category
    default_style: TradeStyle           # Default execution style
    direction: SetupDirection           # Primary direction bias
    
    # SMB metadata
    smb_aliases: List[str] = field(default_factory=list)  # SMB original names that map here
    typical_r_target: float = 2.0       # Typical R-multiple target
    typical_win_rate: float = 0.55      # Historical win rate baseline
    
    # Trading rules
    requires_tape_confirmation: bool = True
    requires_catalyst: bool = False
    min_rvol: float = 1.0
    
    # Time and regime
    valid_time_windows: List[str] = field(default_factory=list)
    valid_regimes: List[str] = field(default_factory=list)


# Complete setup registry with direction classification
SETUP_REGISTRY: Dict[str, SetupConfig] = {
    # ==================== OPENING SETUPS (9:30-9:45) ====================
    
    "first_vwap_pullback": SetupConfig(
        name="first_vwap_pullback",
        display_name="First VWAP Pullback",
        category=SetupCategory.CATALYST_DRIVEN,
        default_style=TradeStyle.INTRADAY,
        direction=SetupDirection.BOTH,
        typical_r_target=2.5,
        requires_catalyst=True,
        valid_time_windows=["opening_auction", "opening_drive"],
        valid_regimes=["momentum", "strong_uptrend", "strong_downtrend"]
    ),
    
    "first_move_up": SetupConfig(
        name="first_move_up",
        display_name="First Move Up (Fade)",
        category=SetupCategory.REVERSAL,
        default_style=TradeStyle.SCALP,
        direction=SetupDirection.SHORT,  # Fade the first move UP = short
        typical_r_target=1.5,
        valid_time_windows=["opening_auction"],
        valid_regimes=["range_bound", "fade"]
    ),
    
    "first_move_down": SetupConfig(
        name="first_move_down",
        display_name="First Move Down (Fade)",
        category=SetupCategory.REVERSAL,
        default_style=TradeStyle.SCALP,
        direction=SetupDirection.LONG,  # Fade the first move DOWN = long
        typical_r_target=1.5,
        valid_time_windows=["opening_auction"],
        valid_regimes=["range_bound", "fade"]
    ),
    
    "bella_fade": SetupConfig(
        name="bella_fade",
        display_name="Bella Fade",
        category=SetupCategory.REVERSAL,
        default_style=TradeStyle.SCALP,
        direction=SetupDirection.BOTH,  # Fade extreme in either direction
        typical_r_target=2.0,
        valid_time_windows=["opening_auction", "opening_drive"],
        valid_regimes=["volatile", "fade"]
    ),
    
    "back_through_open": SetupConfig(
        name="back_through_open",
        display_name="Back Through Open",
        category=SetupCategory.CATALYST_DRIVEN,
        default_style=TradeStyle.INTRADAY,
        direction=SetupDirection.LONG,  # Gap up, dip, back through = long
        smb_aliases=["back_through"],
        typical_r_target=3.0,
        requires_catalyst=True,
        valid_time_windows=["opening_auction"],
        valid_regimes=["momentum", "strong_uptrend"]
    ),
    
    "up_through_open": SetupConfig(
        name="up_through_open",
        display_name="Up Through Open",
        category=SetupCategory.CATALYST_DRIVEN,
        default_style=TradeStyle.INTRADAY,
        direction=SetupDirection.LONG,  # Gap down, reverse up through open = long
        typical_r_target=3.0,
        requires_catalyst=True,
        valid_time_windows=["opening_auction"],
        valid_regimes=["momentum", "fade"]
    ),
    
    "opening_drive": SetupConfig(
        name="opening_drive",
        display_name="Opening Drive",
        category=SetupCategory.TREND_MOMENTUM,
        default_style=TradeStyle.INTRADAY,
        direction=SetupDirection.BOTH,  # Go with strong directional open
        typical_r_target=3.0,
        requires_catalyst=True,
        min_rvol=2.0,
        valid_time_windows=["opening_auction", "opening_drive"],
        valid_regimes=["momentum", "strong_uptrend", "strong_downtrend"]
    ),
    
    # ==================== MORNING MOMENTUM SETUPS (9:45-10:30) ====================
    
    "orb": SetupConfig(
        name="orb",
        display_name="Opening Range Breakout",
        category=SetupCategory.TREND_MOMENTUM,
        default_style=TradeStyle.INTRADAY,
        direction=SetupDirection.BOTH,
        smb_aliases=["opening_range_breakout"],
        typical_r_target=2.5,
        min_rvol=1.5,
        valid_time_windows=["opening_drive", "morning_momentum", "morning_session"],
        valid_regimes=["momentum", "strong_uptrend", "strong_downtrend"]
    ),
    
    "hitchhiker": SetupConfig(
        name="hitchhiker",
        display_name="HitchHiker Scalp",
        category=SetupCategory.TREND_MOMENTUM,
        default_style=TradeStyle.SCALP,
        direction=SetupDirection.LONG,  # Ride strong momentum leaders
        smb_aliases=["market_play"],
        typical_r_target=1.9,
        typical_win_rate=0.58,
        min_rvol=2.0,
        valid_time_windows=["opening_drive", "morning_momentum"],
        valid_regimes=["momentum", "strong_uptrend"]
    ),
    
    "gap_give_go": SetupConfig(
        name="gap_give_go",
        display_name="Gap Give and Go",
        category=SetupCategory.CATALYST_DRIVEN,
        default_style=TradeStyle.SCALP,
        direction=SetupDirection.LONG,  # Gap up, pullback, continue up
        smb_aliases=["gap_and_go"],
        typical_r_target=2.0,
        requires_catalyst=True,
        valid_time_windows=["opening_drive", "morning_momentum"],
        valid_regimes=["momentum", "strong_uptrend"]
    ),
    
    "gap_pick_roll": SetupConfig(
        name="gap_pick_roll",
        display_name="Gap Pick and Roll",
        category=SetupCategory.CATALYST_DRIVEN,
        default_style=TradeStyle.SCALP,
        direction=SetupDirection.SHORT,  # Gap down, pop, fail, roll down
        typical_r_target=2.0,
        requires_catalyst=True,
        valid_time_windows=["opening_drive", "morning_momentum"],
        valid_regimes=["momentum", "strong_downtrend"]
    ),
    
    # ==================== CORE SESSION SETUPS (10:00-13:30) ====================
    
    "spencer_scalp": SetupConfig(
        name="spencer_scalp",
        display_name="Spencer Scalp",
        category=SetupCategory.CONSOLIDATION,
        default_style=TradeStyle.SCALP,
        direction=SetupDirection.BOTH,
        smb_aliases=["scalp"],  # Removed dr_s, elite_101 as requested
        typical_r_target=1.5,
        typical_win_rate=0.60,
        valid_time_windows=["morning_momentum", "morning_session", "late_morning", "midday"],
        valid_regimes=["momentum", "strong_uptrend", "strong_downtrend"]
    ),
    
    "second_chance": SetupConfig(
        name="second_chance",
        display_name="Second Chance Scalp",
        category=SetupCategory.SPECIALIZED,
        default_style=TradeStyle.SCALP,
        direction=SetupDirection.BOTH,  # Re-entry after pullback
        typical_r_target=2.0,
        typical_win_rate=0.55,
        valid_time_windows=["morning_momentum", "morning_session", "late_morning", "midday", "afternoon"],
        valid_regimes=["momentum", "strong_uptrend", "strong_downtrend"]
    ),
    
    "backside": SetupConfig(
        name="backside",
        display_name="Backside Scalp",
        category=SetupCategory.REVERSAL,
        default_style=TradeStyle.SCALP,
        direction=SetupDirection.LONG,  # Reversal after extended down move
        typical_r_target=1.5,
        valid_time_windows=["morning_session", "late_morning", "midday"],
        valid_regimes=["strong_uptrend", "strong_downtrend"]
    ),
    
    "off_sides": SetupConfig(
        name="off_sides",
        display_name="Off Sides Scalp",
        category=SetupCategory.REVERSAL,
        default_style=TradeStyle.SCALP,
        direction=SetupDirection.BOTH,  # Fade extreme intraday move
        smb_aliases=["stuffed"],
        typical_r_target=1.5,
        valid_time_windows=["morning_session", "late_morning", "midday"],
        valid_regimes=["range_bound", "fade"]
    ),
    
    "fashionably_late": SetupConfig(
        name="fashionably_late",
        display_name="Fashionably Late",
        category=SetupCategory.SPECIALIZED,
        default_style=TradeStyle.SCALP,
        direction=SetupDirection.LONG,  # Late entry after 9 EMA crosses VWAP
        typical_r_target=3.0,
        typical_win_rate=0.60,
        valid_time_windows=["morning_session", "late_morning", "midday"],
        valid_regimes=["strong_uptrend", "strong_downtrend"]
    ),
    
    # ==================== MEAN REVERSION SETUPS ====================
    
    "rubber_band_long": SetupConfig(
        name="rubber_band_long",
        display_name="Rubber Band Scalp (Long)",
        category=SetupCategory.REVERSAL,
        default_style=TradeStyle.SCALP,
        direction=SetupDirection.LONG,  # Snapback from oversold
        smb_aliases=["bounce"],
        typical_r_target=1.5,
        valid_time_windows=["morning_momentum", "morning_session", "late_morning", "midday", "afternoon"],
        valid_regimes=["range_bound", "fade", "volatile"]
    ),
    
    "rubber_band_short": SetupConfig(
        name="rubber_band_short",
        display_name="Rubber Band Scalp (Short)",
        category=SetupCategory.REVERSAL,
        default_style=TradeStyle.SCALP,
        direction=SetupDirection.SHORT,  # Snapback from overbought
        typical_r_target=1.5,
        valid_time_windows=["morning_momentum", "morning_session", "late_morning", "midday", "afternoon"],
        valid_regimes=["range_bound", "fade", "volatile"]
    ),
    
    # Keep original rubber_band for backwards compatibility (maps to both)
    "rubber_band": SetupConfig(
        name="rubber_band",
        display_name="Rubber Band Scalp",
        category=SetupCategory.REVERSAL,
        default_style=TradeStyle.SCALP,
        direction=SetupDirection.BOTH,
        smb_aliases=["bounce"],
        typical_r_target=1.5,
        valid_time_windows=["morning_momentum", "morning_session", "late_morning", "midday", "afternoon"],
        valid_regimes=["range_bound", "fade", "volatile"]
    ),
    
    "vwap_bounce": SetupConfig(
        name="vwap_bounce",
        display_name="VWAP Bounce",
        category=SetupCategory.REVERSAL,
        default_style=TradeStyle.INTRADAY,
        direction=SetupDirection.LONG,  # Bounce off VWAP support
        typical_r_target=2.0,
        valid_time_windows=["morning_momentum", "morning_session", "late_morning", "midday", "afternoon"],
        valid_regimes=["range_bound", "strong_uptrend"]
    ),
    
    "vwap_fade": SetupConfig(
        name="vwap_fade",
        display_name="VWAP Fade",
        category=SetupCategory.REVERSAL,
        default_style=TradeStyle.SCALP,
        # 2026-04-21: DISABLED short side — audit showed vwap_fade_short bled
        # -9.57R/trade across 51 trades. Only long side remains allowed until
        # IB bracket orders + ATR-based min-stop check are in place.
        # See /app/memory/IB_BRACKET_ORDER_MIGRATION.md
        direction=SetupDirection.LONG,
        typical_r_target=1.5,
        valid_time_windows=["morning_session", "late_morning", "midday", "afternoon"],
        valid_regimes=["range_bound", "fade"]
    ),
    
    "tidal_wave": SetupConfig(
        name="tidal_wave",
        display_name="Tidal Wave / Bouncy Ball",
        category=SetupCategory.REVERSAL,
        default_style=TradeStyle.SCALP,
        direction=SetupDirection.SHORT,  # Short after weaker bounces
        typical_r_target=2.5,
        valid_time_windows=["morning_session", "late_morning", "midday", "afternoon"],
        valid_regimes=["strong_downtrend", "fade"]
    ),
    
    "mean_reversion": SetupConfig(
        name="mean_reversion",
        display_name="Mean Reversion",
        category=SetupCategory.REVERSAL,
        default_style=TradeStyle.SCALP,
        direction=SetupDirection.BOTH,
        typical_r_target=1.5,
        valid_time_windows=["morning_momentum", "morning_session", "late_morning", "midday", "afternoon"],
        valid_regimes=["range_bound", "fade"]
    ),
    
    # ==================== CONSOLIDATION SETUPS ====================
    
    "big_dog": SetupConfig(
        name="big_dog",
        display_name="Big Dog Consolidation",
        category=SetupCategory.CONSOLIDATION,
        default_style=TradeStyle.INTRADAY,
        direction=SetupDirection.BOTH,
        smb_aliases=["big_dawg"],
        typical_r_target=3.0,
        valid_time_windows=["morning_session", "late_morning", "midday"],
        valid_regimes=["momentum", "strong_uptrend", "strong_downtrend"]
    ),
    
    "puppy_dog": SetupConfig(
        name="puppy_dog",
        display_name="Puppy Dog Consolidation",
        category=SetupCategory.CONSOLIDATION,
        default_style=TradeStyle.SCALP,
        direction=SetupDirection.BOTH,
        typical_r_target=2.0,
        valid_time_windows=["morning_session", "late_morning", "midday"],
        valid_regimes=["momentum", "strong_uptrend", "strong_downtrend"]
    ),
    
    "9_ema_scalp": SetupConfig(
        name="9_ema_scalp",
        display_name="9 EMA Scalp",
        category=SetupCategory.SPECIALIZED,
        default_style=TradeStyle.SCALP,
        direction=SetupDirection.BOTH,  # Scalp bounces off 9 EMA
        typical_r_target=1.5,
        valid_time_windows=["morning_momentum", "morning_session", "late_morning"],
        valid_regimes=["momentum", "strong_uptrend"]
    ),
    
    "abc_scalp": SetupConfig(
        name="abc_scalp",
        display_name="ABC Scalp",
        category=SetupCategory.SPECIALIZED,
        default_style=TradeStyle.SCALP,
        direction=SetupDirection.BOTH,
        typical_r_target=1.5,
        valid_time_windows=["morning_session", "late_morning", "midday"],
        valid_regimes=["momentum", "strong_uptrend", "strong_downtrend"]
    ),
    
    "squeeze": SetupConfig(
        name="squeeze",
        display_name="Volatility Squeeze",
        category=SetupCategory.CONSOLIDATION,
        default_style=TradeStyle.INTRADAY,
        direction=SetupDirection.BOTH,
        typical_r_target=2.5,
        valid_time_windows=["morning_session", "late_morning", "midday", "afternoon"],
        valid_regimes=["range_bound", "momentum"]
    ),
    
    # ==================== AFTERNOON SETUPS (13:30-16:00) ====================
    
    "hod_breakout": SetupConfig(
        name="hod_breakout",
        display_name="HOD Breakout (Above the Clouds)",
        category=SetupCategory.TREND_MOMENTUM,
        default_style=TradeStyle.INTRADAY,
        direction=SetupDirection.LONG,  # Break of high of day
        smb_aliases=["above_the_clouds", "afternoon_to_light"],
        typical_r_target=2.5,
        requires_catalyst=True,
        valid_time_windows=["afternoon", "close"],
        valid_regimes=["momentum", "strong_uptrend"]
    ),
    
    "lod_breakdown": SetupConfig(
        name="lod_breakdown",
        display_name="LOD Breakdown",
        category=SetupCategory.TREND_MOMENTUM,
        default_style=TradeStyle.INTRADAY,
        direction=SetupDirection.SHORT,  # Break of low of day
        typical_r_target=2.5,
        requires_catalyst=True,
        valid_time_windows=["afternoon", "close"],
        valid_regimes=["momentum", "strong_downtrend"]
    ),
    
    "time_of_day_fade": SetupConfig(
        name="time_of_day_fade",
        display_name="Time of Day Fade",
        category=SetupCategory.REVERSAL,
        default_style=TradeStyle.SCALP,
        direction=SetupDirection.BOTH,  # Fade extended move into close
        typical_r_target=1.5,
        valid_time_windows=["close"],
        valid_regimes=["range_bound", "fade"]
    ),
    
    # ==================== SPECIAL/CATALYST SETUPS ====================
    
    "breaking_news": SetupConfig(
        name="breaking_news",
        display_name="Breaking News",
        category=SetupCategory.CATALYST_DRIVEN,
        default_style=TradeStyle.INTRADAY,
        direction=SetupDirection.BOTH,
        smb_aliases=["changing_fundamentals"],
        typical_r_target=3.0,
        requires_catalyst=True,
        min_rvol=3.0,
        valid_time_windows=["opening_auction", "opening_drive", "morning_momentum", 
                           "morning_session", "late_morning", "midday", "afternoon", "close"],
        valid_regimes=["momentum", "volatile"]
    ),
    
    "volume_capitulation": SetupConfig(
        name="volume_capitulation",
        display_name="Volume Capitulation",
        category=SetupCategory.REVERSAL,
        default_style=TradeStyle.SCALP,
        direction=SetupDirection.BOTH,  # Reversal after volume spike
        typical_r_target=2.0,
        min_rvol=5.0,
        valid_time_windows=["morning_session", "late_morning", "midday", "afternoon"],
        valid_regimes=["volatile", "strong_uptrend", "strong_downtrend"]
    ),
    
    "range_break": SetupConfig(
        name="range_break",
        display_name="Range Break",
        category=SetupCategory.CONSOLIDATION,
        default_style=TradeStyle.INTRADAY,
        direction=SetupDirection.BOTH,
        typical_r_target=2.0,
        valid_time_windows=["morning_session", "late_morning", "midday", "afternoon"],
        valid_regimes=["momentum", "range_bound"]
    ),
    
    "breakout": SetupConfig(
        name="breakout",
        display_name="Breakout",
        category=SetupCategory.TREND_MOMENTUM,
        default_style=TradeStyle.INTRADAY,
        direction=SetupDirection.LONG,  # Classic breakout above resistance
        typical_r_target=2.5,
        valid_time_windows=["morning_session", "late_morning", "midday", "afternoon"],
        valid_regimes=["momentum", "strong_uptrend"]
    ),
    
    "breakdown": SetupConfig(
        name="breakdown",
        display_name="Breakdown",
        category=SetupCategory.TREND_MOMENTUM,
        default_style=TradeStyle.INTRADAY,
        direction=SetupDirection.SHORT,  # Classic breakdown below support
        typical_r_target=2.5,
        valid_time_windows=["morning_session", "late_morning", "midday", "afternoon"],
        valid_regimes=["momentum", "strong_downtrend"]
    ),
    
    "relative_strength": SetupConfig(
        name="relative_strength",
        display_name="Relative Strength",
        category=SetupCategory.TREND_MOMENTUM,
        default_style=TradeStyle.INTRADAY,
        direction=SetupDirection.LONG,  # Outperforming SPY
        typical_r_target=2.0,
        valid_time_windows=["morning_momentum", "morning_session", "late_morning", "midday", "afternoon"],
        valid_regimes=["momentum", "strong_uptrend", "range_bound"]
    ),
    
    "relative_weakness": SetupConfig(
        name="relative_weakness",
        display_name="Relative Weakness",
        category=SetupCategory.TREND_MOMENTUM,
        default_style=TradeStyle.INTRADAY,
        direction=SetupDirection.SHORT,  # Underperforming SPY
        typical_r_target=2.0,
        valid_time_windows=["morning_momentum", "morning_session", "late_morning", "midday", "afternoon"],
        valid_regimes=["momentum", "strong_downtrend", "range_bound"]
    ),
    
    "gap_fade": SetupConfig(
        name="gap_fade",
        display_name="Gap Fade",
        category=SetupCategory.REVERSAL,
        default_style=TradeStyle.SCALP,
        direction=SetupDirection.BOTH,  # Fade failing gap
        typical_r_target=1.5,
        valid_time_windows=["opening_drive", "morning_momentum"],
        valid_regimes=["fade", "range_bound"]
    ),
    
    "chart_pattern": SetupConfig(
        name="chart_pattern",
        display_name="Chart Pattern",
        category=SetupCategory.CONSOLIDATION,
        default_style=TradeStyle.INTRADAY,
        direction=SetupDirection.BOTH,
        typical_r_target=2.0,
        valid_time_windows=["morning_session", "late_morning", "midday", "afternoon"],
        valid_regimes=["momentum", "range_bound"]
    ),
}


# ==================== SMB ALIAS MAPPING ====================

# Maps SMB original terminology to your implementation names
SMB_SETUP_ALIASES: Dict[str, str] = {
    "big_dawg": "big_dog",
    "gap_and_go": "gap_give_go",
    "bounce": "rubber_band",
    "stuffed": "off_sides",
    "scalp": "spencer_scalp",
    "market_play": "hitchhiker",
    "changing_fundamentals": "breaking_news",
    "above_the_clouds": "hod_breakout",
    "afternoon_to_light": "hod_breakout",
    "back_through": "back_through_open",
    "opening_range_breakout": "orb",
}


def resolve_setup_name(name: str) -> str:
    """Resolve an alias to the canonical setup name"""
    return SMB_SETUP_ALIASES.get(name.lower(), name.lower())


def get_setup_config(name: str) -> Optional[SetupConfig]:
    """Get setup configuration by name or alias"""
    canonical_name = resolve_setup_name(name)
    return SETUP_REGISTRY.get(canonical_name)


# ==================== SMB 5-VARIABLE SCORING ====================

@dataclass
class SMBVariableScore:
    """
    SMB Capital's 5-Variable Scoring System
    
    Each variable is scored 1-10:
    - Big Picture: Market/sector alignment (SPY trend, sector strength)
    - Intraday Fundamental: Catalyst strength and freshness
    - Technical Level: Clarity of S/R levels to trade against
    - Tape Reading: Order flow quality (bids, absorption, momentum)
    - Intuition: Pattern recognition confidence based on experience
    
    Total score of 40+ with no variable below 7 = A+ Setup
    """
    big_picture: int = 5          # Market/sector alignment
    intraday_fundamental: int = 5  # Catalyst strength
    technical_level: int = 5       # S/R clarity
    tape_reading: int = 5          # Order flow quality
    intuition: int = 5             # Pattern confidence
    
    # Individual variable notes
    big_picture_notes: str = ""
    fundamental_notes: str = ""
    technical_notes: str = ""
    tape_notes: str = ""
    intuition_notes: str = ""
    
    @property
    def total_score(self) -> int:
        """Total score out of 50"""
        return (self.big_picture + self.intraday_fundamental + 
                self.technical_level + self.tape_reading + self.intuition)
    
    @property
    def min_variable(self) -> int:
        """Lowest variable score"""
        return min(self.big_picture, self.intraday_fundamental,
                   self.technical_level, self.tape_reading, self.intuition)
    
    @property
    def is_a_plus(self) -> bool:
        """A+ setup: total >= 40 AND no variable below 7"""
        return self.total_score >= 40 and self.min_variable >= 7
    
    @property
    def grade(self) -> str:
        """Grade based on total score and consistency"""
        if self.is_a_plus:
            return "A+"
        elif self.total_score >= 35 and self.min_variable >= 6:
            return "A"
        elif self.total_score >= 30 and self.min_variable >= 5:
            return "B+"
        elif self.total_score >= 25:
            return "B"
        elif self.total_score >= 20:
            return "C"
        else:
            return "D"
    
    @property
    def trade_style_recommendation(self) -> TradeStyle:
        """Recommend trade style based on score"""
        if self.is_a_plus:
            return TradeStyle.MULTI_DAY
        elif self.total_score >= 30:
            return TradeStyle.INTRADAY
        else:
            return TradeStyle.SCALP
    
    @property
    def size_multiplier(self) -> float:
        """Position size multiplier based on grade"""
        multipliers = {
            "A+": 1.5,
            "A": 1.25,
            "B+": 1.0,
            "B": 0.85,
            "C": 0.5,
            "D": 0.0  # Don't trade
        }
        return multipliers.get(self.grade, 1.0)
    
    def to_dict(self) -> Dict:
        return {
            "big_picture": self.big_picture,
            "intraday_fundamental": self.intraday_fundamental,
            "technical_level": self.technical_level,
            "tape_reading": self.tape_reading,
            "intuition": self.intuition,
            "total_score": self.total_score,
            "min_variable": self.min_variable,
            "grade": self.grade,
            "is_a_plus": self.is_a_plus,
            "trade_style": self.trade_style_recommendation.value,
            "size_multiplier": self.size_multiplier,
            "notes": {
                "big_picture": self.big_picture_notes,
                "fundamental": self.fundamental_notes,
                "technical": self.technical_notes,
                "tape": self.tape_notes,
                "intuition": self.intuition_notes
            }
        }


def calculate_smb_score(
    # Big Picture inputs
    spy_trend: str = "neutral",  # "strong_up", "up", "neutral", "down", "strong_down"
    sector_alignment: bool = True,
    market_regime: str = "range_bound",
    
    # Fundamental inputs
    catalyst_score: float = 5.0,  # 1-10
    has_news: bool = False,
    earnings_score: int = 0,  # -10 to +10
    
    # Technical inputs
    support_clarity: float = 5.0,  # 1-10 how clear is support
    resistance_clarity: float = 5.0,  # 1-10 how clear is resistance
    atr_reasonable: bool = True,
    
    # Tape inputs
    tape_score: float = 5.0,  # -10 to 10 from tape reading
    bid_ask_healthy: bool = True,
    volume_confirming: bool = True,
    
    # Intuition inputs (pattern recognition)
    setup_confidence: float = 5.0,  # 1-10
    similar_patterns_won: bool = True
) -> SMBVariableScore:
    """
    Calculate SMB 5-Variable score from raw inputs.
    
    This function translates various data points into the 5-variable framework.
    """
    score = SMBVariableScore()
    
    # 1. BIG PICTURE (1-10)
    bp_score = 5
    bp_notes = []
    
    if spy_trend == "strong_up":
        bp_score += 3
        bp_notes.append("SPY strong uptrend")
    elif spy_trend == "up":
        bp_score += 2
        bp_notes.append("SPY uptrend")
    elif spy_trend == "strong_down":
        bp_score += 2  # Can still be good for shorts
        bp_notes.append("SPY strong downtrend (good for shorts)")
    elif spy_trend == "down":
        bp_score += 1
        bp_notes.append("SPY downtrend")
    
    if sector_alignment:
        bp_score += 1
        bp_notes.append("Sector aligned")
    else:
        bp_score -= 1
        bp_notes.append("Sector diverging")
    
    if market_regime in ["momentum", "strong_uptrend", "strong_downtrend"]:
        bp_score += 1
        bp_notes.append(f"Favorable regime: {market_regime}")
    
    score.big_picture = max(1, min(10, bp_score))
    score.big_picture_notes = ", ".join(bp_notes)
    
    # 2. INTRADAY FUNDAMENTAL (1-10)
    fund_score = 5
    fund_notes = []
    
    # Catalyst score directly maps
    fund_score = int(catalyst_score)
    
    if has_news:
        fund_score += 1
        fund_notes.append("Fresh news catalyst")
    
    # Earnings score adjustment
    if abs(earnings_score) >= 9:
        fund_score += 2
        fund_notes.append(f"Strong earnings catalyst ({earnings_score:+d})")
    elif abs(earnings_score) >= 8:
        fund_score += 1
        fund_notes.append(f"Good earnings catalyst ({earnings_score:+d})")
    
    score.intraday_fundamental = max(1, min(10, fund_score))
    score.fundamental_notes = ", ".join(fund_notes) if fund_notes else f"Catalyst: {catalyst_score}/10"
    
    # 3. TECHNICAL LEVEL (1-10)
    tech_score = 5
    tech_notes = []
    
    # Average of S/R clarity
    tech_score = int((support_clarity + resistance_clarity) / 2)
    
    if support_clarity >= 7:
        tech_notes.append("Clear support")
    if resistance_clarity >= 7:
        tech_notes.append("Clear resistance")
    
    if atr_reasonable:
        tech_score += 1
        tech_notes.append("ATR reasonable")
    else:
        tech_score -= 1
        tech_notes.append("ATR stretched")
    
    score.technical_level = max(1, min(10, tech_score))
    score.technical_notes = ", ".join(tech_notes) if tech_notes else f"S/R clarity: {tech_score}/10"
    
    # 4. TAPE READING (1-10)
    tape_var = 5
    tape_notes = []
    
    # Convert -10 to 10 tape score to 1-10
    tape_var = int(5 + (tape_score / 2))
    
    if bid_ask_healthy:
        tape_var += 1
        tape_notes.append("Healthy bid/ask")
    else:
        tape_var -= 1
        tape_notes.append("Wide spread warning")
    
    if volume_confirming:
        tape_var += 1
        tape_notes.append("Volume confirming")
    
    score.tape_reading = max(1, min(10, tape_var))
    score.tape_notes = ", ".join(tape_notes) if tape_notes else f"Tape: {tape_score}"
    
    # 5. INTUITION (1-10)
    int_score = int(setup_confidence)
    int_notes = []
    
    if similar_patterns_won:
        int_score += 1
        int_notes.append("Similar patterns historically profitable")
    else:
        int_score -= 1
        int_notes.append("Pattern has mixed history")
    
    score.intuition = max(1, min(10, int_score))
    score.intuition_notes = ", ".join(int_notes) if int_notes else f"Confidence: {setup_confidence}/10"
    
    return score


# ==================== SETUP-TO-STYLE MAPPING ====================

def get_default_trade_style(setup_name: str, context: Dict = None) -> TradeStyle:
    """
    Get the default trade style for a setup.
    
    Context can override based on:
    - Market regime
    - Tape quality
    - SMB variable score
    """
    config = get_setup_config(setup_name)
    if not config:
        return TradeStyle.SCALP  # Safe default
    
    default_style = config.default_style
    
    if context:
        # Override based on SMB score if available
        smb_score = context.get("smb_score")
        if smb_score and isinstance(smb_score, SMBVariableScore):
            if smb_score.is_a_plus:
                return TradeStyle.MULTI_DAY
            elif smb_score.total_score >= 35:
                return TradeStyle.INTRADAY
        
        # Override based on market regime
        regime = context.get("market_regime", "").lower()
        if regime in ["momentum", "strong_uptrend", "strong_downtrend"]:
            # Trending markets favor T2H
            if default_style == TradeStyle.SCALP:
                tape_score = context.get("tape_score", 50)
                if tape_score >= 70:  # Strong tape = hold longer
                    return TradeStyle.INTRADAY
        elif regime in ["range_bound", "fade", "volatile"]:
            # Choppy markets favor M2M
            if default_style == TradeStyle.INTRADAY:
                return TradeStyle.SCALP
    
    return default_style


def get_setup_direction(setup_name: str) -> SetupDirection:
    """Get the primary direction for a setup"""
    config = get_setup_config(setup_name)
    if config:
        return config.direction
    return SetupDirection.BOTH


def get_directional_setup_name(setup_name: str, direction: str) -> str:
    """
    Get direction-specific setup name for setups that work both ways.
    
    Example: rubber_band + "long" -> "rubber_band_long"
    """
    config = get_setup_config(setup_name)
    if not config:
        return setup_name
    
    # If setup already has a direction, return as-is
    if config.direction != SetupDirection.BOTH:
        return setup_name
    
    # Check if direction-specific version exists
    directional_name = f"{setup_name}_{direction}"
    if directional_name in SETUP_REGISTRY:
        return directional_name
    
    return setup_name


# ==================== CATEGORY HELPERS ====================

def get_setups_by_category(category: SetupCategory) -> List[str]:
    """Get all setup names in a category"""
    return [name for name, config in SETUP_REGISTRY.items() 
            if config.category == category]


def get_setups_by_direction(direction: SetupDirection) -> List[str]:
    """Get all setup names with a specific direction bias"""
    return [name for name, config in SETUP_REGISTRY.items() 
            if config.direction == direction]


def get_setups_by_style(style: TradeStyle) -> List[str]:
    """Get all setup names with a specific default trade style"""
    return [name for name, config in SETUP_REGISTRY.items() 
            if config.default_style == style]


def get_all_long_setups() -> List[str]:
    """Get all primarily long setups"""
    return [name for name, config in SETUP_REGISTRY.items() 
            if config.direction == SetupDirection.LONG]


def get_all_short_setups() -> List[str]:
    """Get all primarily short setups"""
    return [name for name, config in SETUP_REGISTRY.items() 
            if config.direction == SetupDirection.SHORT]


# ==================== TRADE STYLE R-MULTIPLE TARGETS ====================

TRADE_STYLE_TARGETS = {
    TradeStyle.SCALP: {
        "target_r": 1.0,
        "max_r": 1.5,
        "typical_win_rate": 0.65,
        "exit_rule": "Exit on first momentum pause or target",
        "management": "Full exit at target, tight trail if extended"
    },
    TradeStyle.INTRADAY: {
        "target_r": 3.0,
        "max_r": 5.0,
        "typical_win_rate": 0.45,
        "exit_rule": "Only exit on Reason2Sell trigger",
        "management": "Partial at 1R, hold core for 3R+, trail with 9 EMA"
    },
    TradeStyle.MULTI_DAY: {
        "target_r": 5.0,
        "max_r": 10.0,
        "typical_win_rate": 0.50,
        "exit_rule": "Hold until major thesis invalidation",
        "management": "Scale in on confirmation, max size, wide trail"
    }
}


def get_style_targets(style: TradeStyle) -> Dict:
    """Get target R-multiples and management rules for a trade style"""
    return TRADE_STYLE_TARGETS.get(style, TRADE_STYLE_TARGETS[TradeStyle.SCALP])


# ==================== LOGGING ====================

logger.info(f"📊 SMB Integration Module loaded with {len(SETUP_REGISTRY)} setups")
logger.info(f"   - Long setups: {len(get_all_long_setups())}")
logger.info(f"   - Short setups: {len(get_all_short_setups())}")
logger.info(f"   - Bidirectional setups: {len(get_setups_by_direction(SetupDirection.BOTH))}")
