"""
Autonomous Trading Bot Service
Scans for opportunities, evaluates trades, calculates position sizing,
executes trades, and manages open positions with full explanation logging.

Features:
- Real-time opportunity scanning using existing alert system
- Trade scoring and evaluation using TradingIntelligenceService
- Position sizing based on risk management rules
- Autonomous or confirmation-based trade execution
- Trade explanation generation for every decision
- P&L tracking and daily statistics
- Session persistence (trades, stats, config survive restarts)
- EOD auto-close (closes all positions at configurable time)
"""
import os
import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import uuid
import json

logger = logging.getLogger(__name__)


class BotMode(str, Enum):
    """Bot operating mode"""
    AUTONOMOUS = "autonomous"      # Execute trades without confirmation
    CONFIRMATION = "confirmation"  # Require user approval before execution
    PAUSED = "paused"             # Don't scan or execute


class TradeStatus(str, Enum):
    """Status of a bot trade"""
    PENDING = "pending"           # Awaiting confirmation (in confirmation mode)
    OPEN = "open"                # Position is open
    PARTIAL = "partial"          # Partially filled or partially closed
    CLOSED = "closed"            # Position fully closed
    CANCELLED = "cancelled"      # Broker cancelled order before fill (real IB/Alpaca cancel)
    REJECTED = "rejected"        # Trade rejected by user or system
    # Bot-side pre-execution filters (2026-04-22) — these never touch the
    # broker and must NOT pollute the CANCELLED bucket on execution-health
    # dashboards.
    PAPER = "paper"              # Strategy in PAPER phase — logged, not executed
    SIMULATED = "simulated"      # Strategy in SIMULATION phase — skipped entirely
    VETOED = "vetoed"            # Pre-trade guardrail rejected (tight stop, oversized notional)


class TradeDirection(str, Enum):
    LONG = "long"
    SHORT = "short"


class TradeTimeframe(str, Enum):
    """Trade timeframe classification"""
    SCALP = "scalp"           # Minutes to 1 hour, close at EOD
    INTRADAY = "intraday"     # 1-4 hours, close at EOD
    SWING = "swing"           # 1-5 days, hold overnight
    POSITION = "position"     # Weeks to months, hold overnight


# Strategy-based configuration
STRATEGY_CONFIG = {
    # ==================== OPENING STRATEGIES ====================
    "first_vwap_pullback": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "opening_drive": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "first_move_up": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.5],
        "close_at_eod": True
    },
    "first_move_down": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.5],
        "close_at_eod": True
    },
    "bella_fade": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.5],
        "close_at_eod": True
    },
    
    # ==================== MORNING MOMENTUM ====================
    "orb": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    "orb_long": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    "orb_short": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    "hitchhiker": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.5],  # ONE AND DONE style
        "close_at_eod": True
    },
    "gap_give_go": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "gap_pick_roll": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    
    # ==================== CORE SESSION ====================
    "spencer_scalp": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.33, 0.33, 0.34],  # 1R, 2R, 3R scale
        "close_at_eod": True
    },
    "second_chance": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "backside": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.5],  # ONE AND DONE
        "close_at_eod": True
    },
    "off_sides": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.5],  # ONE ATTEMPT ONLY
        "close_at_eod": True
    },
    "off_sides_short": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.5],
        "close_at_eod": True
    },
    "fashionably_late": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    
    # ==================== MEAN REVERSION ====================
    "rubber_band": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "rubber_band_long": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "rubber_band_short": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "vwap_bounce": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "vwap_fade": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "vwap_fade_long": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "vwap_fade_short": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "tidal_wave": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    
    # ==================== CONSOLIDATION ====================
    "big_dog": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    "puppy_dog": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "9_ema_scalp": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "abc_scalp": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    
    # ==================== AFTERNOON ====================
    "hod_breakout": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    "time_of_day_fade": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.5],
        "close_at_eod": True
    },
    
    # ==================== SPECIAL ====================
    "breaking_news": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "volume_capitulation": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "range_break": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    "range_break_long": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    "breakout": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    
    # ==================== SWING/POSITION ====================
    "squeeze": {
        "timeframe": TradeTimeframe.SWING,
        "trail_pct": 0.025,
        "scale_out_pcts": [0.25, 0.25, 0.5],
        "close_at_eod": False
    },
    "trend_continuation": {
        "timeframe": TradeTimeframe.SWING,
        "trail_pct": 0.025,
        "scale_out_pcts": [0.25, 0.25, 0.5],
        "close_at_eod": False
    },
    "daily_squeeze": {
        "timeframe": TradeTimeframe.SWING,
        "trail_pct": 0.03,
        "scale_out_pcts": [0.25, 0.25, 0.5],
        "close_at_eod": False
    },
    "daily_breakout": {
        "timeframe": TradeTimeframe.SWING,
        "trail_pct": 0.025,
        "scale_out_pcts": [0.25, 0.25, 0.5],
        "close_at_eod": False
    },
    "earnings_momentum": {
        "timeframe": TradeTimeframe.SWING,
        "trail_pct": 0.03,
        "scale_out_pcts": [0.25, 0.25, 0.5],
        "close_at_eod": False
    },
    "sector_rotation": {
        "timeframe": TradeTimeframe.SWING,
        "trail_pct": 0.025,
        "scale_out_pcts": [0.25, 0.25, 0.5],
        "close_at_eod": False
    },
    "base_breakout": {
        "timeframe": TradeTimeframe.POSITION,
        "trail_pct": 0.04,
        "scale_out_pcts": [0.2, 0.3, 0.5],
        "close_at_eod": False
    },
    "accumulation_entry": {
        "timeframe": TradeTimeframe.POSITION,
        "trail_pct": 0.05,
        "scale_out_pcts": [0.2, 0.3, 0.5],
        "close_at_eod": False
    },
    "relative_strength_position": {
        "timeframe": TradeTimeframe.POSITION,
        "trail_pct": 0.04,
        "scale_out_pcts": [0.2, 0.3, 0.5],
        "close_at_eod": False
    },
    "position_trade": {
        "timeframe": TradeTimeframe.POSITION,
        "trail_pct": 0.03,
        "scale_out_pcts": [0.2, 0.3, 0.5],
        "close_at_eod": False
    },
    
    # ==================== CONFIRMED BREAKOUTS (INTRADAY) ====================
    "breakout_confirmed": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    "range_break_confirmed": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    "orb_long_confirmed": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    "chart_pattern": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    "gap_fade": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "mean_reversion_long": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    "mean_reversion_short": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    
    # ==================== APPROACHING (Alerts — trade on confirmation) ====================
    "approaching_breakout": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    "approaching_hod": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    "approaching_orb": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    "approaching_range_break": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    
    # ==================== SHORT SETUPS ====================
    "breakdown_confirmed": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    "gap_fade_daily": {
        "timeframe": TradeTimeframe.SWING,
        "trail_pct": 0.025,
        "scale_out_pcts": [0.25, 0.25, 0.5],
        "close_at_eod": False
    },
    "short_squeeze_fade": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
}

# Default config for unknown setups
DEFAULT_STRATEGY_CONFIG = {
    "timeframe": TradeTimeframe.INTRADAY,
    "trail_pct": 0.02,
    "scale_out_pcts": [0.33, 0.33, 0.34],
    "close_at_eod": True
}


@dataclass
class RiskParameters:
    """Risk management parameters with volatility-adjusted sizing"""
    max_risk_per_trade: float = 2500.0      # Maximum $ risk per trade
    max_daily_loss_pct: float = 1.0          # Maximum daily loss as % of account (1% = stop trading)
    max_daily_loss: float = 0.0              # Calculated from account value (set dynamically)
    starting_capital: float = 100000.0       # Account capital for position sizing (updated from IB)
    max_position_pct: float = 50.0           # Maximum % of capital per position (user requested 50%)
    max_notional_per_trade: float = 100000.0  # Hard absolute notional ceiling per trade ($) — belt-and-braces vs `max_position_pct` (which floats with equity). 0 = disabled. (added 2026-04-30 v19.4)
    max_open_positions: int = 10             # Maximum concurrent positions (unlimited = high number)
    # 2026-05-01 v19.21 — Operator picked 1.7 as the global floor after the
    # HOOD gap_fade R:R 2.05 < 2.5 reject taught us that 2.5 is too strict
    # for mean-reversion plays with bounded targets. See `setup_min_rr`
    # below for per-setup overrides where this floor is intentionally too
    # tight (gap fades, VWAP fades, etc. naturally cap at ~1.5-2.0 R:R).
    min_risk_reward: float = 1.7             # Minimum risk/reward ratio (1.7:1 = risk $1 to make $1.70)
    # 2026-05-01 v19.21 — Per-setup R:R overrides. The global `min_risk_reward`
    # acts as the catch-all floor; setups in this dict override it. Mean-
    # reversion plays (gap_fade, vwap_fade, mean_reversion, rubber_band,
    # bouncy_ball, squeeze) have BOUNDED targets — prev close, VWAP, EMA9 —
    # so their R:R is mathematically capped by the stop distance. Demanding
    # 1.7+ on those rejects 60-80% of valid alerts; demanding 1.5 still
    # filters the trash while letting bounded-target plays through.
    # Trend / breakout setups have UNBOUNDED targets (the next swing high/
    # low can run 3-5× risk), so we keep them at 2.0 as a quality bar.
    setup_min_rr: Dict[str, float] = field(default_factory=lambda: {
        # Mean-reversion (bounded targets) — relax floor.
        "gap_fade":            1.5,
        "vwap_fade":           1.5,
        "vwap_fade_long":      1.5,
        "vwap_fade_short":     1.5,
        "vwap_bounce":         1.5,
        "mean_reversion":      1.5,
        "mean_reversion_long": 1.5,
        "mean_reversion_short": 1.5,
        "rubber_band":         1.5,
        "rubber_band_long":    1.5,
        "rubber_band_short":   1.5,
        "rubber_band_scalp":   1.5,
        "bouncy_ball":         1.5,
        "squeeze":             1.5,
        "tidal_wave":          1.5,
        # Trend / breakout (unbounded targets) — keep tighter.
        "breakout":            2.0,
        "base_breakout":       2.0,
        "hod_breakout":        2.0,
        "orb":                 2.0,
        "orb_long":            2.0,
        "orb_short":           2.0,
        "trend_continuation":  2.0,
        "vwap_continuation":   2.0,
        "the_3_30_trade":      2.0,
        "premarket_high_break": 2.0,
        "9_ema_scalp":         2.0,
        "nine_ema_scalp":      2.0,
    })
    max_slippage_pct: float = 0.5           # Maximum acceptable slippage %

    # 2026-05-01 v19.24 — Defaults for `POST /api/trading-bot/reconcile`.
    # When the bot claims an IB-only (orphan) position that it didn't
    # originate, it has NO setup context to anchor stop/target on. These
    # are the "wide-but-finite" fallback defaults — 2.0% stop gives the
    # orphan breathing room so it isn't insta-stopped on noise, 2.0 R:R
    # keeps math symmetric. The trailing-stop manager ratchets the stop
    # up as price moves in our favor, so it's a STARTING stance, not a
    # permanent wide stop. Operator can override per-request via the
    # endpoint's `stop_pct` / `rr` body params.
    reconciled_default_stop_pct: float = 2.0   # % from avgCost for orphan reconcile
    reconciled_default_rr: float = 2.0         # R:R applied to the default bracket

    # Trading hours (Eastern Time)
    trading_start_hour: int = 7              # Start trading at 7:30 AM ET
    trading_start_minute: int = 30
    trading_end_hour: int = 17               # Stop trading at 5:00 PM ET
    trading_end_minute: int = 0

    # Volatility-adjusted position sizing
    use_volatility_sizing: bool = True       # Enable ATR-based position sizing
    base_atr_multiplier: float = 1.5         # Stop distance = ATR * multiplier
    volatility_scale_factor: float = 1.0     # Scale position size by volatility (1.0 = neutral)
    min_atr_multiplier: float = 1.0          # Minimum stop distance in ATRs
    max_atr_multiplier: float = 3.0          # Maximum stop distance in ATRs

    def effective_min_rr(self, setup_type: str) -> float:
        """Return the effective R:R floor for a setup — per-setup override
        if defined, else the global `min_risk_reward`. Strips _long/_short/
        _confirmed suffixes so e.g. `vwap_fade_long` resolves to the
        `vwap_fade_long` override (or `vwap_fade` if only the base is set).
        """
        if not setup_type:
            return self.min_risk_reward
        # Direct match first.
        if setup_type in self.setup_min_rr:
            return self.setup_min_rr[setup_type]
        # Suffix-stripped match.
        base = (
            setup_type
            .rsplit("_long", 1)[0]
            .rsplit("_short", 1)[0]
            .rsplit("_confirmed", 1)[0]
        )
        if base in self.setup_min_rr:
            return self.setup_min_rr[base]
        return self.min_risk_reward


@dataclass
class TradeExplanation:
    """Detailed explanation of trade logic"""
    summary: str
    setup_identified: str
    technical_reasons: List[str]
    fundamental_reasons: List[str]
    risk_analysis: Dict[str, Any]
    entry_logic: str
    exit_logic: str
    position_sizing_logic: str
    confidence_factors: List[str]
    warnings: List[str]
    ai_evaluation: str = ""
    ai_verdict: str = ""


@dataclass
class BotTrade:
    """Complete bot trade record"""
    id: str
    symbol: str
    direction: TradeDirection
    status: TradeStatus
    
    # Setup details
    setup_type: str
    timeframe: str
    quality_score: int
    quality_grade: str
    
    # Price levels (required fields before defaults)
    entry_price: float
    current_price: float
    stop_price: float
    target_prices: List[float]
    
    # Position details (required)
    shares: int
    risk_amount: float
    potential_reward: float
    risk_reward_ratio: float
    
    # SMB Integration fields (with defaults)
    trade_style: str = "trade_2_hold"  # "move_2_move", "trade_2_hold", "a_plus"
    smb_grade: str = "B"              # A+, A, B+, B, C, D
    tape_score: int = 5               # 1-10
    target_r_multiple: float = 2.0    # Target R based on trade style
    direction_bias: str = "both"      # Setup's primary direction
    
    # Scale-out tracking (with defaults)
    original_shares: int = 0  # Original position size before scale-outs
    remaining_shares: int = 0  # Shares still held after scale-outs
    scale_out_config: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "targets_hit": [],  # List of target indices that have been hit
        "scale_out_pcts": [0.33, 0.33, 0.34],  # Percentage to sell at each target
        "partial_exits": []  # List of {target_idx, shares_sold, price, pnl, timestamp}
    })
    
    # Trailing stop configuration
    trailing_stop_config: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "mode": "original",  # "original", "breakeven", "trailing"
        "original_stop": 0.0,  # Original stop price
        "current_stop": 0.0,   # Current effective stop price
        "trail_pct": 0.02,     # Trail by 2% from high (for longs) or low (for shorts)
        "trail_atr_mult": 1.5, # Alternative: trail by 1.5x ATR
        "high_water_mark": 0.0,  # Highest price since T2 hit (for longs)
        "low_water_mark": 0.0,   # Lowest price since T2 hit (for shorts)
        "stop_adjustments": []   # History of stop adjustments
    })
    
    # Execution details
    fill_price: Optional[float] = None
    exit_price: Optional[float] = None
    
    # P&L
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0  # Cumulative from all scale-outs + final exit
    pnl_pct: float = 0.0
    
    # Commission tracking (IB tiered: ~$0.005/share, $1.00 min per order)
    commission_per_share: float = 0.005
    commission_min: float = 1.00
    total_commissions: float = 0.0  # Running total of all commissions for this trade
    net_pnl: float = 0.0  # realized_pnl - total_commissions
    
    # Timing
    created_at: str = ""
    executed_at: Optional[str] = None
    closed_at: Optional[str] = None
    estimated_duration: str = ""  # e.g., "30min-2hr" for scalp
    
    # Close reason (manual, stop_loss, target_hit, target_1, target_2, target_3, eod_close, etc.)
    close_reason: Optional[str] = None
    
    # EOD close flag (from strategy config)
    close_at_eod: bool = True
    
    # Explanation
    explanation: Optional[TradeExplanation] = None
    
    # Notes for tracking (e.g., [SIMULATED], error messages, etc.)
    notes: Optional[str] = None
    
    # Market regime at time of trade entry
    market_regime: str = "UNKNOWN"  # RISK_ON, CAUTION, RISK_OFF, CONFIRMED_DOWN
    regime_score: float = 50.0      # Composite score at entry (0-100)
    regime_position_multiplier: float = 1.0  # Position size adjustment applied
    
    # Order IDs (from broker)
    entry_order_id: Optional[str] = None
    stop_order_id: Optional[str] = None
    target_order_ids: List[str] = field(default_factory=list)
    
    # === RICHER TRADE LOGGING ===
    
    # Pattern variant: granular SMB setup name (e.g., "spencer_scalp", "vwap_bounce")
    # while setup_type holds the broad AI category (e.g., "SCALP", "VWAP")
    setup_variant: str = ""
    
    # Entry context: signals and conditions that aligned for this trade
    entry_context: Dict[str, Any] = field(default_factory=dict)
    
    # MFE (Maximum Favorable Excursion) - best unrealized profit during trade
    mfe_price: float = 0.0    # Best favorable price since fill
    mfe_pct: float = 0.0      # MFE as % from entry
    mfe_r: float = 0.0        # MFE in R-multiples (relative to risk)
    
    # MAE (Maximum Adverse Excursion) - worst unrealized loss during trade
    mae_price: float = 0.0    # Worst adverse price since fill
    mae_pct: float = 0.0      # MAE as % from entry (always negative)
    mae_r: float = 0.0        # MAE in R-multiples (always negative)

    # v19.31.13 — Trade origin classification.
    # "paper" — bot fired against IB paper account (DUN…/paperesw…)
    # "live"  — bot fired against IB live account (esw…/U… without DU prefix)
    # "shadow"— never set on bot_trades (shadow lives in shadow_decisions
    #           with `was_executed=False`); reserved here for forward-compat
    #           if we ever materialize a paper-only test fill row.
    # "unknown"— pusher offline at fill time / account guard unconfigured.
    # Stamped at execution time from `account_guard.classify_account_id`
    # so historical truth is preserved even when the operator flips
    # IB_ACCOUNT_ACTIVE between paper and live.
    trade_type: str = "unknown"
    account_id_at_fill: Optional[str] = None

    # v19.34.3 (2026-05-04) — Provenance + reconcile-conflict metadata.
    # `entered_by`:
    #   "bot_fired"         — bot's own evaluation + execution path opened it.
    #   "reconciled_external"— position_reconciler adopted an IB orphan
    #                         the bot didn't open. Operator MUST treat
    #                         this as "manage carefully" — synthetic
    #                         SL/PT may not match the bot's real verdict.
    #   "manual"            — created via manual API call.
    # Stamped at materialization time. Historical truth.
    entered_by: str = "bot_fired"
    # When `entered_by == "reconciled_external"`, this holds the bot's
    # last 5 verdicts on this symbol pulled from `sentcom_thoughts` at
    # reconcile time. Lets the UI show "prior verdict: REJECT (R:R 1.19)"
    # so the operator never silently inherits a setup the bot rejected.
    prior_verdicts: List[Dict[str, Any]] = field(default_factory=list)
    # True when ≥2 of the last 3 verdicts were rejections — signals a
    # high-confidence "this position contradicts my recent verdicts"
    # situation. Triggers a HIGH-priority warning event at reconcile.
    prior_verdict_conflict: bool = False
    # Where the synthetic SL/PT came from:
    #   "last_verdict" — pulled from a recent rejection's computed numbers.
    #   "default_pct"  — fell back to RiskParameters.reconciled_default_*.
    # Lets the UI show which logic was used.
    synthetic_source: Optional[str] = None
    # 2026-05-05 v19.34.6 — Pre-execution Mongo-first sanity gate.
    # ISO timestamp stamped IMMEDIATELY before submitting the trade to
    # the broker. The trade is upserted to `bot_trades` with
    # status=PENDING + this field BEFORE any broker call. After fill,
    # post-fill `_save_trade` overwrites with status=OPEN. If the bot
    # crashes between the pre-submit write and the fill confirmation,
    # the orphan-recovery loop sees a stuck PENDING row + uses this
    # timestamp to detect a crashed in-flight order.
    pre_submit_at: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        d = asdict(self)
        d['direction'] = self.direction.value if isinstance(self.direction, TradeDirection) else self.direction
        d['status'] = self.status.value if isinstance(self.status, TradeStatus) else self.status
        d['timeframe'] = self.timeframe
        d['close_at_eod'] = self.close_at_eod
        # Ensure regime fields are included
        d['market_regime'] = self.market_regime
        d['regime_score'] = self.regime_score
        d['regime_position_multiplier'] = self.regime_position_multiplier
        # Ensure richer logging fields are included
        d['setup_variant'] = self.setup_variant
        d['entry_context'] = self.entry_context
        d['mfe_price'] = self.mfe_price
        d['mfe_pct'] = self.mfe_pct
        d['mfe_r'] = self.mfe_r
        d['mae_price'] = self.mae_price
        d['mae_pct'] = self.mae_pct
        d['mae_r'] = self.mae_r
        d['total_commissions'] = self.total_commissions
        d['net_pnl'] = self.net_pnl
        # v19.31.13 — trade-type taxonomy fields
        d['trade_type'] = self.trade_type
        d['account_id_at_fill'] = self.account_id_at_fill
        # v19.34.3 — provenance + reconcile-conflict metadata
        d['entered_by'] = self.entered_by
        d['prior_verdicts'] = self.prior_verdicts
        d['prior_verdict_conflict'] = self.prior_verdict_conflict
        d['synthetic_source'] = self.synthetic_source
        # v19.34.6 — Pre-submit Mongo sanity timestamp.
        d['pre_submit_at'] = self.pre_submit_at
        return d


@dataclass
class DailyStats:
    """Daily trading statistics"""
    date: str
    trades_executed: int = 0
    trades_won: int = 0
    trades_lost: int = 0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    win_rate: float = 0.0
    daily_limit_hit: bool = False


class TradingBotService:
    """
    Main trading bot service that orchestrates scanning, evaluation,
    execution, and position management.
    """
    
    def __init__(self):
        self._mode = BotMode.AUTONOMOUS  # Start in autonomous mode for auto-trading
        self._running = False
        self._scan_task: Optional[asyncio.Task] = None
        
        # Risk parameters
        self.risk_params = RiskParameters()
        
        # State
        self._pending_trades: Dict[str, BotTrade] = {}
        self._open_trades: Dict[str, BotTrade] = {}
        self._closed_trades: List[BotTrade] = []
        self._daily_stats = DailyStats(date=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        
        # Configuration - Enable all major strategies for autonomous trading
        self._enabled_setups = [
            # Opening strategies
            "first_vwap_pullback", "opening_drive", "first_move_up", "first_move_down", "bella_fade",
            # Morning momentum
            "orb", "orb_long", "orb_short", "hitchhiker", "gap_give_go", "gap_pick_roll",
            # Core session
            "spencer_scalp", "second_chance", "backside", "off_sides", "fashionably_late",
            # Mean reversion
            "rubber_band", "rubber_band_scalp", "vwap_bounce", "vwap_fade", "tidal_wave",
            # Consolidation
            "big_dog", "puppy_dog", "nine_ema_scalp", "abc_scalp", "9_ema_scalp",
            # Afternoon
            "hod_breakout", "time_of_day_fade",
            # Special
            "breaking_news", "volume_capitulation", "range_break", "breakout",
            # New strategies
            "squeeze", "relative_strength", "relative_strength_leader", "relative_strength_laggard",
            "mean_reversion", "gap_fade", "chart_pattern",
            # REVERSAL-family scanner bases (2026-04-24) — required for
            # SHORT_REVERSAL (Sharpe 1.94, +7.6pp edge, promoted) to actually
            # receive scanner alerts. Without these bases in the filter the
            # alerts would be rejected at the enabled-setups gate before
            # reaching predict_for_setup → the SHORT_REVERSAL model.
            "reversal", "halfback_reversal", "halfback",
            # Additional VWAP scanner bases (2026-04-24) — for SHORT_VWAP
            # (Sharpe 1.76, promoted) beyond vwap_bounce/vwap_fade already covered
            "vwap_reclaim", "vwap_rejection",
            # 2026-05-01 v19.20 — ENABLE real playbook setups that were built into
            # the scanner (have their own detectors) but were silently missing from
            # the bot's enabled list. Operator saw these as "setup_disabled" spam
            # every cycle even though they are valid, live, Bellafiore-aligned trades.
            # All have dedicated `_check_*` methods in enhanced_scanner.py.
            "bouncy_ball",           # Bellafiore SHORT playbook: failed bounce + support break
            "the_3_30_trade",        # Bellafiore LONG playbook: power-hour range break
            "vwap_continuation",     # VWAP momentum continuation (both long/short)
            "premarket_high_break",  # Gap & Go continuation: break of PMH on volume
            "trend_continuation",    # Intraday trend continuation
            "base_breakout",         # Chart pattern: base/flag breakout
            "accumulation_entry",    # Smart-money accumulation entry
            "back_through_open",     # Reversal through the opening print
            "up_through_open",       # Reversal through the opening print (long)
            "daily_breakout",        # Daily timeframe breakout (EOD setup)
            "daily_squeeze",         # Daily timeframe squeeze (EOD setup)
        ]

        # 2026-05-01 v19.20 — WATCHLIST-ONLY setups: these fire from the scanner
        # for TOMORROW'S plan (EOD carry-forward / next-day watchlist) or as
        # pre-trigger proximity warnings. They are NOT live-tradeable signals
        # and must skip the bot evaluator entirely so the Stream/Deep Feed
        # doesn't get flooded with "setup_disabled" messages every cycle.
        # Consumed silently by gameplan_service for journal watchlists.
        self._watchlist_only_setups = {
            # EOD carry-forward tags (promoted near close for tomorrow's plan)
            "day_2_continuation", "carry_forward_watch", "gap_fill_open",
            # Pre-trigger proximity warnings (scanner early-warning system)
            "approaching_breakout", "approaching_hod",
            "approaching_orb", "approaching_range_break",
        }
        self._scan_interval = 30  # seconds - faster scanning for autonomous trading
        self._watchlist: List[str] = []
        
        # EOD Auto-Close Configuration
        # 2026-04-30 v19.14 — moved from 3:57 → 3:55 PM ET so intraday
        # closes complete a full 5 min before the 4:00 PM bell, leaving
        # margin for IB roundtrip latency / partial-fail retries. Only
        # applies to trades flagged `close_at_eod=True` (intraday/scalp/day
        # — see `check_eod_close` filter); swing/position trades are
        # explicitly kept overnight.
        self._eod_close_enabled = True
        self._eod_close_hour = 15  # 3 PM ET
        self._eod_close_minute = 55  # 3:55 PM ET
        self._eod_close_executed_today = False
        self._last_eod_check_date = None
        
        # Services (injected)
        self._alert_system = None
        self._trading_intelligence = None
        self._alpaca_service = None
        self._trade_executor = None
        self._db = None
        
        # Enhanced intelligence services (lazy loaded)
        self._web_research = None
        self._market_intelligence = None
        self._technical_service = None
        self._quality_service = None
        self._news_service = None
        
        # Learning Loop integration (Phase 1)
        self._learning_loop = None
        
        # Market Regime Engine integration
        self._market_regime_engine = None
        self._current_regime = "RISK_ON"  # Default to risk-on
        self._regime_position_multipliers = {
            "RISK_ON": 1.0,           # Full position sizing
            "CAUTION": 0.75,          # Reduce by 25%
            "RISK_OFF": 0.5,          # Reduce by 50%
            "CONFIRMED_DOWN": 0.25    # Reduce by 75% for longs, normal for shorts
        }
        
        # Regime Performance Tracking
        self._regime_performance_service = None
        
        # Trade Journal Service (auto-record trades)
        self._trade_journal = None
        
        # AI Trade Consultation (Phase 2 Integration)
        self._ai_consultation = None
        
        # Strategy Promotion Service (SIM → PAPER → LIVE lifecycle)
        self._strategy_promotion_service = None
        
        # Callbacks for real-time updates
        self._trade_callbacks: List[callable] = []
        
        # =====================================================================
        # SMART STRATEGY FILTERING - Win rate based trade filtering
        # =====================================================================
        # Stores recent "skipped trade" reasoning to show in Bot's Thoughts
        self._strategy_filter_thoughts: List[Dict] = []  # [{text, timestamp, symbol, setup_type, win_rate, action}]
        self._max_filter_thoughts = 20  # Keep last 20 filtered trade reasons
        
        # Enhanced scanner reference for strategy stats
        self._enhanced_scanner = None
        
        # AI Confidence Gate (pre-trade regime + model consensus check)
        self._confidence_gate = None
        
        # Smart filtering (delegated to SmartFilter module)
        from services.smart_filter import SmartFilter
        self._smart_filter = SmartFilter()
        self._smart_filter_config = self._smart_filter.config
        
        # Extracted modules (Phase: refactoring)
        from services.stop_manager import StopManager
        from services.trade_intelligence import TradeIntelligence
        from services.trade_execution import TradeExecution
        from services.position_reconciler import PositionReconciler
        from services.position_manager import PositionManager
        from services.bot_persistence import BotPersistence
        from services.opportunity_evaluator import OpportunityEvaluator
        from services.scanner_integration import ScannerIntegration
        self._stop_manager = StopManager()
        self._trade_intel = TradeIntelligence()
        self._trade_execution = TradeExecution()
        self._position_reconciler = PositionReconciler()
        self._position_manager = PositionManager()
        self._persistence = BotPersistence()
        self._opportunity_evaluator = OpportunityEvaluator()
        self._scanner_integration = ScannerIntegration()
        
        logger.info("TradingBotService initialized in AUTONOMOUS mode")
    
    def set_services(self, alert_system, trading_intelligence, alpaca_service, trade_executor, db):
        """Inject service dependencies"""
        self._alert_system = alert_system
        self._trading_intelligence = trading_intelligence
        self._alpaca_service = alpaca_service
        self._trade_executor = trade_executor
        self._db = db
        # 2026-04-29: liquidity-aware stop trail (Q1) — give the
        # extracted StopManager DB access so it can call into
        # smart_levels_service.compute_trailing_stop_snap.
        if hasattr(self._stop_manager, "set_db"):
            self._stop_manager.set_db(db)
        logger.info("TradingBotService services configured")
    
    def set_market_regime_engine(self, regime_engine):
        """Set market regime engine for regime-aware position sizing"""
        self._market_regime_engine = regime_engine
        logger.info("TradingBotService: Market Regime Engine connected")
    
    def set_regime_performance_service(self, performance_service):
        """Set regime performance service for trade logging"""
        self._regime_performance_service = performance_service
        logger.info("TradingBotService: Regime Performance Service connected")
    
    def set_enhanced_scanner(self, scanner):
        """Set enhanced scanner for strategy stats access (Smart Strategy Filtering)"""
        self._enhanced_scanner = scanner
        logger.info("TradingBotService: Enhanced Scanner connected for Smart Strategy Filtering")
    
    def set_trade_journal(self, journal_service):
        """Set trade journal service for auto-recording trades"""
        self._trade_journal = journal_service
        logger.info("TradingBotService: Trade Journal connected for auto-recording")
    
    def set_ai_consultation(self, ai_consultation):
        """
        Set AI Trade Consultation service for pre-trade analysis.
        
        When enabled, every trade runs through:
        - Bull/Bear Debate
        - AI Risk Manager
        - Institutional Flow analysis
        - Volume anomaly detection
        
        In Shadow Mode: AI analyzes and logs but doesn't block trades
        In Live Mode: AI can block or reduce trade sizes
        """
        self._ai_consultation = ai_consultation
        logger.info("TradingBotService: AI Trade Consultation connected")
        if ai_consultation:
            status = ai_consultation.get_status()
            logger.info(f"  - Shadow Mode: {status.get('shadow_mode', True)}")
            logger.info(f"  - Modules enabled: {status.get('modules_enabled', {})}")
    
    def set_strategy_promotion_service(self, promotion_service):
        """
        Set Strategy Promotion Service for SIM → PAPER → LIVE lifecycle management.
        
        When connected, the trading bot will:
        - Check each strategy's phase before executing trades
        - LIVE strategies: Execute real trades
        - PAPER strategies: Record paper trades (no real execution)
        - SIMULATION strategies: Skip real-time trading entirely
        """
        self._strategy_promotion_service = promotion_service
        logger.info("TradingBotService: Strategy Promotion Service connected")
        if promotion_service:
            phases = promotion_service.get_all_phases()
            live_count = sum(1 for p in phases.values() if p == "live")
            paper_count = sum(1 for p in phases.values() if p == "paper")
            logger.info(f"  - Tracking {len(phases)} strategies: {live_count} LIVE, {paper_count} PAPER")

    def set_confidence_gate(self, confidence_gate):
        """
        Set AI Confidence Gate for pre-trade regime + model consensus evaluation.

        Flow: Setup Detected → Smart Filter → **Confidence Gate** → Position Sizing → Execute
        
        The gate evaluates:
        - Current market regime (rule-based + AI)
        - Model consensus for this setup type
        - Returns GO / REDUCE / SKIP with position multiplier
        """
        self._confidence_gate = confidence_gate
        logger.info("TradingBotService: AI Confidence Gate connected")
        logger.info("  - Pre-trade flow: Smart Filter → Confidence Gate → Position Sizing → Execute")

    @staticmethod
    def _calculate_commission(shares: int, per_share: float = 0.005, minimum: float = 1.00) -> float:
        """
        Calculate commission for an order.
        IB Tiered: ~$0.005/share, $1.00 min, capped at 1% of trade value.
        """
        return max(minimum, round(shares * per_share, 2))

    def _apply_commission(self, trade, shares: int):
        """Add commission for an order (entry or exit) to the trade's running total."""
        commission = self._calculate_commission(shares, trade.commission_per_share, trade.commission_min)
        trade.total_commissions = round(trade.total_commissions + commission, 2)
        trade.net_pnl = round(trade.realized_pnl - trade.total_commissions, 2)
        return commission
    
    # ==================== SMART STRATEGY FILTERING ====================
    
    def get_strategy_historical_stats(self, setup_type: str) -> Dict[str, Any]:
        """
        Get user's historical performance stats for a specific setup type.
        Used for Smart Strategy Filtering - adjusts trade decisions based on past performance.
        
        Returns:
            dict with win_rate, sample_size, avg_r, expected_value, recommendation
        """
        if not self._enhanced_scanner:
            return {"available": False, "reason": "Scanner not connected"}
        
        try:
            # Get base setup type (remove _long/_short suffix for stats lookup)
            base_setup = setup_type.split("_long")[0].split("_short")[0]
            
            # Try to get stats from enhanced scanner
            stats = self._enhanced_scanner.get_strategy_stats(base_setup)
            
            if not stats:
                return {
                    "available": False,
                    "reason": "No historical data",
                    "setup_type": base_setup
                }
            
            sample_size = stats.get("alerts_triggered", 0) or stats.get("total_alerts", 0)
            win_rate = stats.get("win_rate", 0)
            avg_r = stats.get("avg_rr_achieved", 0)
            expected_value = stats.get("expected_value_r", 0)
            
            return {
                "available": True,
                "setup_type": base_setup,
                "win_rate": win_rate,
                "sample_size": sample_size,
                "avg_r": avg_r,
                "expected_value": expected_value,
                "profit_factor": stats.get("profit_factor", 0),
                "total_pnl": stats.get("total_pnl", 0),
                "wins": stats.get("alerts_won", 0),
                "losses": stats.get("alerts_lost", 0)
            }
            
        except Exception as e:
            logger.warning(f"Could not get strategy stats for {setup_type}: {e}")
            return {"available": False, "reason": str(e)}
    
    def _evaluate_strategy_filter(self, setup_type: str, quality_score: int, symbol: str) -> Dict[str, Any]:
        """
        Evaluate if a trade should be filtered based on historical performance.
        Delegates to the SmartFilter module for the actual decision logic.
        """
        stats = self.get_strategy_historical_stats(setup_type)
        return self._smart_filter.evaluate(setup_type, quality_score, symbol, stats)
    
    def _add_filter_thought(self, thought: Dict):
        """Add a strategy filter reasoning to the thoughts list"""
        self._smart_filter.add_thought(thought)
        # Also keep local reference for backward compat
        self._strategy_filter_thoughts = self._smart_filter.get_thoughts(self._max_filter_thoughts)
    
    def get_filter_thoughts(self, limit: int = 10) -> List[Dict]:
        """Get recent strategy filter thoughts for Bot's Brain display"""
        return self._smart_filter.get_thoughts(limit)

    # ============================================================
    # Rejection narrative composer (added 2026-04-28)
    # ------------------------------------------------------------
    # Operator preference: "I really want to know what the bot is
    # thinking and doing at all times." Setup-found narrative lives
    # in sentcom_service. THIS composes the symmetrical
    # "why didn't I take this trade?" line for every rejection gate
    # (dedup, position-exists, pending, setup-disabled, confidence
    # gate, account guard, EOD, regime mismatch, …).
    # ============================================================
    def record_rejection(
        self,
        symbol: str,
        setup_type: str,
        direction: str,
        reason_code: str,
        context: Optional[Dict] = None,
    ) -> str:
        """
        Compose a wordy 1-2 sentence rejection narrative and push it
        into the same `_strategy_filter_thoughts` buffer the UI's
        Bot's Brain panel already streams. Returns the narrative
        string for caller-side logging too.

        `reason_code` is a stable enum-like key
        (e.g. "dedup_open_position"); `context` carries setup-specific
        details the composer can weave into the sentence (cooldown
        seconds left, existing position symbol, etc.). Future PRs
        adding a new gate just need a new reason_code branch in
        `_compose_rejection_narrative` — the buffer / streaming path
        is already wired.
        """
        ctx = context or {}
        # 2026-05-01 v19.20 — Rejection dedup. The Deep Feed was being
        # flooded with the same (symbol, setup_type, reason_code) rejection
        # every 30-60 seconds for the entire dedup cooldown window (several
        # minutes). The buffer and stream are now suppressed for duplicates
        # within _REJECTION_DEDUP_WINDOW_SECONDS. The first hit still records
        # — so the operator sees that the bot DID consider it — but the
        # follow-on spam is silenced. TTL auto-evicts so the dict does not
        # grow unbounded.
        now_ts = datetime.now(timezone.utc).timestamp()
        if not hasattr(self, "_rejection_dedup_cache"):
            self._rejection_dedup_cache: Dict[tuple, float] = {}
            self._REJECTION_DEDUP_WINDOW_SECONDS = 120.0
        dedup_key = (symbol, setup_type, reason_code)
        last_emitted = self._rejection_dedup_cache.get(dedup_key)
        if last_emitted and (now_ts - last_emitted) < self._REJECTION_DEDUP_WINDOW_SECONDS:
            # Silent suppression — still mark cycle as "had a rejection" so
            # the evaluator_veto_unknown catch-all upstream doesn't double-
            # count. Return narrative composed for caller logging but skip
            # the buffer/stream emission.
            self._last_evaluator_rejection_recorded = True
            return self._compose_rejection_narrative(
                symbol=symbol, setup_type=setup_type, direction=direction,
                reason_code=reason_code, ctx=ctx,
            )
        # Evict expired entries opportunistically (cheap — dict <2KB typical).
        if len(self._rejection_dedup_cache) > 500:
            stale = [k for k, t in self._rejection_dedup_cache.items()
                     if (now_ts - t) > self._REJECTION_DEDUP_WINDOW_SECONDS]
            for k in stale:
                self._rejection_dedup_cache.pop(k, None)
        self._rejection_dedup_cache[dedup_key] = now_ts

        # 2026-04-29 (afternoon-14): mark that *some* rejection was
        # recorded for the current evaluation cycle so the catch-all
        # `evaluator_veto_unknown` in `_scan_for_setups` doesn't double-
        # count when the evaluator already pinpointed a specific reason.
        # Reset to False at the top of each evaluation iteration.
        self._last_evaluator_rejection_recorded = True
        narrative = self._compose_rejection_narrative(
            symbol=symbol, setup_type=setup_type, direction=direction,
            reason_code=reason_code, ctx=ctx,
        )
        thought = {
            "text": narrative,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "setup_type": setup_type,
            "direction": direction,
            "reason_code": reason_code,
            "action": "rejected",
        }
        try:
            self._smart_filter.add_thought(thought)
            self._strategy_filter_thoughts = self._smart_filter.get_thoughts(self._max_filter_thoughts)
        except Exception as exc:
            # Buffer add must never break the rejection hot path.
            logger.debug(f"record_rejection: buffer add failed: {exc}")
        # Persist into the SentCom unified stream (also writes to
        # `sentcom_thoughts` Mongo collection — survives restarts +
        # available for chat context recall via /api/sentcom/thoughts).
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                from services.sentcom_service import emit_stream_event
                # v19.34.3 (2026-05-04) — surface the full eval context
                # in the persisted metadata so the position_reconciler
                # can later use the bot's actual computed entry/stop/
                # target/RR (the "real" math) when adopting an IB
                # orphan, instead of synthetic 2% defaults that don't
                # reflect bar conditions. Operator-discovered: VALE was
                # being rejected for R:R 1.19 yet reconciled with
                # synthetic R:R 2.0 — the reconciled SL/PT didn't match
                # the bot's actual setup math.
                _meta = {
                    "setup_type": setup_type,
                    "direction": direction,
                    "reason_code": reason_code,
                }
                # Whitelist the numeric/structural keys the reconciler
                # might want — full ctx forwarding could leak large
                # debug blobs into Mongo.
                _ctx_keys = (
                    "rr_ratio", "min_required", "global_min",
                    "entry_price", "stop_price", "primary_target",
                    "target_prices", "shares", "stop_distance_pct",
                    "atr", "confidence_score",
                )
                for _k in _ctx_keys:
                    _v = ctx.get(_k) if isinstance(ctx, dict) else None
                    if _v is not None:
                        _meta[_k] = _v
                loop.create_task(emit_stream_event({
                    "kind": "rejection",
                    "event": f"rejection_{reason_code}",
                    "symbol": symbol,
                    "text": narrative,
                    "metadata": _meta,
                }))
        except Exception as exc:
            logger.debug(f"record_rejection: stream emit failed: {exc}")
        return narrative

    def _compose_rejection_narrative(
        self,
        *,
        symbol: str,
        setup_type: str,
        direction: str,
        reason_code: str,
        ctx: Dict,
    ) -> str:
        """Build the 1-2 sentence "why I passed" narrative."""
        setup_display = (setup_type or "setup").replace("_", " ").title()
        dir_word = (direction or "").lower()
        dir_phrase = "long" if dir_word in ("long", "buy") else (
            "short" if dir_word in ("short", "sell") else "directional"
        )

        if reason_code == "dedup_open_position":
            existing = ctx.get("existing_position", symbol)
            return (
                f"⏭️ Passing on {symbol} {setup_display} — already have an "
                f"open {existing} position from earlier and I'm not stacking "
                f"another lot on the same name. Will re-look once that one's "
                f"closed."
            )
        if reason_code == "dedup_cooldown":
            cooldown_left = ctx.get("cooldown_seconds_left")
            cooldown_phrase = (
                f" Cooldown clears in {int(cooldown_left)}s."
                if cooldown_left else ""
            )
            return (
                f"⏭️ Passing on {symbol} {setup_display} — I just fired this "
                f"exact {dir_phrase} setup on {symbol} a few minutes ago and "
                f"the dedup cooldown is still active. Letting it clear before "
                f"another shot.{cooldown_phrase}"
            )
        if reason_code == "position_exists":
            return (
                f"⏭️ Passing on {symbol} {setup_display} — already in {symbol} "
                f"from a prior fill. Won't double up on the same name in the "
                f"same direction."
            )
        if reason_code == "pending_trade_exists":
            return (
                f"⏭️ Passing on {symbol} {setup_display} — there's already a "
                f"pending {symbol} trade waiting on confirmation. Holding off "
                f"until that decision lands."
            )
        if reason_code == "setup_disabled":
            return (
                f"⏭️ Skipping {symbol} {setup_display} — this strategy is "
                f"currently OFF in my enabled list. Either you turned it off "
                f"in Bot Setup, or it's still in SIMULATION while we collect "
                f"shadow data. Re-enable it in Bot Setup if you want me to "
                f"trade it."
            )
        if reason_code == "max_open_positions":
            cap = ctx.get("cap")
            cap_phrase = f" (cap: {cap})" if cap else ""
            # Gate-level rejection — symbol is usually a placeholder so
            # don't lead with "Passing on —".
            return (
                f"⏸️ Skipping the whole scan cycle — already at my "
                f"max-open-positions cap{cap_phrase}. New ideas have to "
                f"wait for one of the current trades to close before I "
                f"evaluate anything else."
            )
        if reason_code == "tqs_too_low":
            tqs = ctx.get("tqs", 0)
            min_tqs = ctx.get("min_tqs", 60)
            return (
                f"⏭️ Passing on {symbol} {setup_display} — TQS came back at "
                f"{tqs:.0f}/100, below my {min_tqs:.0f} minimum. Quality's "
                f"not there; I'd rather wait for a cleaner read."
            )
        if reason_code == "confidence_gate_veto":
            confidence = ctx.get("confidence")
            min_confidence = ctx.get("min_confidence")
            why = ctx.get("why", "model consensus or regime check failed")
            conf_phrase = (
                f" ({confidence:.0%} vs {min_confidence:.0%} required)"
                if confidence is not None and min_confidence is not None
                else ""
            )
            return (
                f"⏭️ Passing on {symbol} {setup_display} — pre-trade "
                f"confidence gate vetoed it{conf_phrase}: {why}. I want my "
                f"models AND the regime to agree before I commit."
            )
        if reason_code == "regime_mismatch":
            regime = ctx.get("regime", "current")
            return (
                f"⏭️ Passing on {symbol} {setup_display} — {dir_phrase} "
                f"setups don't fit a {regime} regime in my book. Trading "
                f"against the tape is how losses compound; I'd rather sit out."
            )
        if reason_code == "account_guard_veto":
            why = ctx.get("why", "guardrail tripped")
            return (
                f"⏭️ Passing on {symbol} {setup_display} — account guard "
                f"vetoed: {why}. Not risking a margin call or a max-daily-"
                f"loss breach for one alert."
            )
        if reason_code == "eod_blackout":
            return (
                f"⏭️ Passing on {symbol} {setup_display} — too close to the "
                f"close to open a new {dir_phrase}. EOD blackout is on; I'm "
                f"in flatten-only mode now."
            )
        if reason_code == "evaluator_veto":
            why = ctx.get("why", "evaluator didn't see edge")
            return (
                f"⏭️ Passing on {symbol} {setup_display} — opportunity "
                f"evaluator returned no trade: {why}. Either entry/stop "
                f"math didn't work or I couldn't size it within risk caps."
            )
        # 2026-04-29 (afternoon-14) — split the generic `evaluator_veto`
        # into specific reason codes so the rejection-analytics dashboard
        # tells operator exactly which gate dropped the trade.
        if reason_code == "no_price":
            return (
                f"⏭️ Passing on {symbol} {setup_display} — couldn't get a "
                f"current price from the IB pusher OR Alpaca. Likely a "
                f"subscription gap; can't size a trade without a quote."
            )
        if reason_code == "smart_filter_skip":
            why = ctx.get("why", "smart filter rejected this setup")
            wr = ctx.get("win_rate")
            wr_phrase = f" (historical win rate {wr:.0%})" if wr else ""
            return (
                f"⏭️ Passing on {symbol} {setup_display} — smart strategy "
                f"filter said SKIP{wr_phrase}: {why}."
            )
        if reason_code == "gate_skip":
            conf = ctx.get("confidence_score")
            mode = ctx.get("trading_mode", "normal")
            why = ctx.get("why", "gate veto")
            conf_phrase = f" ({conf}% confidence)" if conf is not None else ""
            return (
                f"⏭️ Passing on {symbol} {setup_display} — confidence gate "
                f"voted SKIP{conf_phrase} in {mode} mode. {why}"
            )
        if reason_code == "position_size_zero":
            entry = ctx.get("entry_price")
            stop = ctx.get("stop_price")
            risk = ctx.get("risk_amount")
            return (
                f"⏭️ Passing on {symbol} {setup_display} — position sizer "
                f"returned 0 shares (entry=${entry:.2f}, stop=${stop:.2f}, "
                f"risk=${risk:.2f}). Equity may be unavailable, or risk caps "
                f"are tighter than the entry/stop distance allows."
            )
        if reason_code == "rr_below_min":
            rr = ctx.get("rr_ratio")
            min_rr = ctx.get("min_required")
            return (
                f"⏭️ Passing on {symbol} {setup_display} — risk:reward "
                f"{rr:.2f} below my {min_rr} minimum. Either the target "
                f"is too close or the stop is too far. Lower min_risk_reward "
                f"in risk_params if you want more setups to qualify."
            )
        if reason_code == "ai_consultation_block":
            why = ctx.get("why", "AI veto")
            return (
                f"⏭️ Passing on {symbol} {setup_display} — AI consultation "
                f"blocked the trade: {why}"
            )
        if reason_code == "evaluator_exception":
            err = ctx.get("error", "unknown error")
            return (
                f"⚠️ Skipping {symbol} {setup_display} — evaluator threw an "
                f"exception: {err}. This is a code bug, not a market signal."
            )
        if reason_code == "evaluator_veto_unknown":
            return (
                f"⏭️ Passing on {symbol} {setup_display} — evaluator returned "
                f"no trade without recording a specific reason. New return-"
                f"None path that needs a reason_code added."
            )
        if reason_code == "tight_stop":
            stop_dist = ctx.get("stop_distance_pct")
            phrase = (
                f" (stop only {stop_dist:.2f}% away)"
                if stop_dist is not None else ""
            )
            return (
                f"⏭️ Passing on {symbol} {setup_display} — stop is too tight "
                f"to absorb normal noise{phrase}. Would just get wicked out "
                f"and rebooked at a worse price."
            )
        if reason_code == "oversized_notional":
            return (
                f"⏭️ Passing on {symbol} {setup_display} — required position "
                f"size would blow past my max-notional-per-trade cap. Setup "
                f"is fine, but the trade plan doesn't fit."
            )

        # Generic fallback — never throw, never produce empty text.
        why = ctx.get("why", "did not meet criteria")
        return (
            f"⏭️ Passing on {symbol} {setup_display} — {why}. Reason code: "
            f"{reason_code}."
        )
    
    def get_smart_filter_config(self) -> Dict:
        """Get current smart filter configuration"""
        return self._smart_filter.config
    
    def update_smart_filter_config(self, updates: Dict) -> Dict:
        """Update smart filter configuration"""
        result = self._smart_filter.update_config(updates)
        self._smart_filter_config = result
        return result
    
    async def _update_market_regime(self):
        """Fetch current market regime for position sizing adjustments"""
        if self._market_regime_engine is None:
            return
        
        try:
            regime_data = await self._market_regime_engine.get_current_regime()
            new_regime = regime_data.get("state", "RISK_ON")
            
            if new_regime != self._current_regime:
                old_regime = self._current_regime
                self._current_regime = new_regime
                multiplier = self._regime_position_multipliers.get(new_regime, 1.0)
                logger.info(f"🌡️ Market regime changed: {old_regime} -> {new_regime} (position multiplier: {multiplier}x)")
            
        except Exception as e:
            logger.warning(f"Could not fetch market regime: {e}")
    
    def _get_current_session(self) -> str:
        """Get current trading session (for AI consultation context)"""
        from datetime import time as dt_time
        now_utc = datetime.now(timezone.utc)
        # Convert to ET (rough approximation)
        et_hour = (now_utc.hour - 5) % 24
        
        if et_hour < 9 or (et_hour == 9 and now_utc.minute < 30):
            return "pre_market"
        elif et_hour >= 16:
            return "post_market"
        elif et_hour == 9 and now_utc.minute < 45:
            return "open"
        elif et_hour == 15 and now_utc.minute >= 30:
            return "power_hour"
        elif et_hour < 12:
            return "morning"
        elif et_hour < 15:
            return "afternoon"
        else:
            return "closing"
    
    async def _get_account_value(self) -> float:
        """
        Get current account NetLiquidation. Order of resolution:
          1. IB live account values (pushed from Windows pusher / IB Gateway)
          2. Alpaca (legacy, only if explicitly re-enabled — phase 4 default OFF)
          3. Hardcoded $100k fallback (last resort)

        Before 2026-04-28 this only checked Alpaca, which always
        returned None after Phase 4 Alpaca retirement → bot kept
        sizing on the $100k default no matter what the operator's IB
        account balance was. Now we read NetLiquidation from
        `routers.ib._pushed_ib_data` first, falling back to a direct
        IB-pusher RPC call when the push-loop's payload is empty
        (operator-flagged pre-RTH 2026-04-29: pusher RPC can be up
        and streaming quotes while the POST push-loop is broken
        upstream — the account dict was empty for hours and the bot
        was sizing every trade off the $100k default).
        """
        # 1) IB account from the pushed data (preferred when pusher is up).
        try:
            from routers.ib import _pushed_ib_data, _extract_account_value
            account = (_pushed_ib_data or {}).get("account") or {}
            if account:
                net_liq = _extract_account_value(account, "NetLiquidation", 0)
                if net_liq and net_liq > 0:
                    # Update risk_params.starting_capital so future scans
                    # see the live value too — this also feeds position
                    # sizing helpers that read starting_capital directly.
                    try:
                        self.risk_params.starting_capital = float(net_liq)
                    except Exception:
                        pass
                    return float(net_liq)
        except Exception as exc:
            logger.debug(f"_get_account_value: IB read failed: {exc}")

        # 1b) IB account via direct RPC fallback. Same data source, but
        # bypasses `_pushed_ib_data` so a broken push-loop doesn't leave
        # the bot sizing on the hardcoded default. Synchronous RPC, ~50ms
        # on the LAN — only fires when path #1 came up empty.
        try:
            from services.ib_pusher_rpc import get_account_snapshot
            # v19.30.8 (2026-05-02 evening): wrap in asyncio.to_thread.
            # Same wedge class as Wedge #1 today: get_account_snapshot
            # holds the pusher RPC's threading.Lock + does sync HTTP.
            # `_get_account_value` is awaited from the bot scan loop and
            # the position sizer hot path — a wedge here pins the loop
            # for the full RPC timeout (5s).
            snap = await asyncio.to_thread(get_account_snapshot)
            if snap and isinstance(snap, dict):
                # Pusher exposes NetLiquidation under a few different
                # casings depending on the pusher build — try them all.
                net_liq = None
                for key in ("NetLiquidation", "NetLiquidation-S",
                            "net_liquidation", "netLiquidation",
                            "equity", "account_value"):
                    v = snap.get(key)
                    if v is None:
                        continue
                    if isinstance(v, dict):
                        v = v.get("value") or v.get("amount")
                    try:
                        f = float(v)
                        if f > 0:
                            net_liq = f
                            break
                    except (TypeError, ValueError):
                        continue
                if net_liq:
                    try:
                        self.risk_params.starting_capital = float(net_liq)
                    except Exception:
                        pass
                    logger.info(
                        f"💰 Account value via RPC fallback: ${net_liq:,.0f} "
                        f"(push-loop payload was empty)"
                    )
                    return float(net_liq)
        except Exception as exc:
            logger.debug(f"_get_account_value: pusher RPC fallback failed: {exc}")

        # 2) Alpaca (legacy fallback — almost always None after Phase 4).
        try:
            if self._alpaca_service:
                account = await self._alpaca_service.get_account()
                if account:
                    pv = float(account.get("portfolio_value") or 0)
                    if pv > 0:
                        return pv
        except Exception as e:
            logger.warning(f"Could not get account value from Alpaca: {e}")

        # 3) Last-resort hardcoded fallback. Sized for paper trading
        # so the bot can still produce SOME output when fully offline,
        # but the operator should investigate (no IB push, no Alpaca).
        return float(self.risk_params.starting_capital or 100_000)
    
    async def _restore_state(self):
        """Restore bot state — delegated to BotPersistence module."""
        await self._persistence.restore_state(self)
    
    async def _restore_closed_trades(self):
        """Restore closed trades — delegated to BotPersistence module."""
        await self._persistence.restore_closed_trades(self)
    
    async def _restore_open_trades(self):
        """Restore open trades — delegated to BotPersistence module."""
        await self._persistence.restore_open_trades(self)

    async def _delayed_reconciliation(self):
        """Startup reconciliation — delegated to BotPersistence module."""
        await self._persistence.delayed_reconciliation(self)
    
    async def _save_state(self):
        """Save bot state — delegated to BotPersistence module."""
        await self._persistence.save_state(self)

    def _persist_trade(self, trade: 'BotTrade'):
        """Persist a single trade — delegated to BotPersistence module."""
        self._persistence.persist_trade(trade, self)

    def _persist_all_open_trades(self):
        """Persist all open trades — delegated to BotPersistence module."""
        self._persistence.persist_all_open_trades(self)
    
    # ==================== INTELLIGENCE SERVICE PROPERTIES ====================
    
    @property
    def web_research(self):
        """Lazy load web research service"""
        if self._web_research is None:
            try:
                from services.web_research_service import get_web_research_service
                self._web_research = get_web_research_service()
            except Exception as e:
                logger.warning(f"Web research service not available: {e}")
        return self._web_research
    
    @property
    def market_intelligence(self):
        """Lazy load market intelligence service"""
        if self._market_intelligence is None:
            try:
                from services.ai_market_intelligence import get_ai_market_intelligence
                self._market_intelligence = get_ai_market_intelligence()
            except Exception as e:
                logger.warning(f"Market intelligence service not available: {e}")
        return self._market_intelligence
    
    @property
    def technical_service(self):
        """Lazy load technical analysis service"""
        if self._technical_service is None:
            try:
                from services.realtime_technical_service import get_technical_service
                self._technical_service = get_technical_service()
            except Exception as e:
                logger.warning(f"Technical service not available: {e}")
        return self._technical_service
    
    @property
    def quality_service(self):
        """Lazy load quality scoring service"""
        if self._quality_service is None:
            try:
                from services.quality_service import get_quality_service
                self._quality_service = get_quality_service()
            except Exception as e:
                logger.warning(f"Quality service not available: {e}")
        return self._quality_service
    
    @property
    def news_service(self):
        """Lazy load news service"""
        if self._news_service is None:
            try:
                from services.news_service import get_news_service
                self._news_service = get_news_service()
            except Exception as e:
                logger.warning(f"News service not available: {e}")
        return self._news_service
    
    def add_trade_callback(self, callback: callable):
        """Add callback for trade updates"""
        self._trade_callbacks.append(callback)
    
    async def _notify_trade_update(self, trade: BotTrade, event_type: str):
        """Notify callbacks of trade updates"""
        for callback in self._trade_callbacks:
            try:
                await callback(trade, event_type)
            except Exception as e:
                logger.error(f"Trade callback error: {e}")
    
    # ==================== CONFIGURATION ====================
    
    def set_mode(self, mode: BotMode):
        """Set operating mode + sync scanner auto-execute state.

        2026-04-30: the scanner sync used to live only in the router
        endpoints that called this method, which meant any internal
        call to `set_mode` (scripts, automation) silently bypassed it
        and left scanner auto-execute out of sync. Sync is now
        authoritative — happens whichever path triggers the change."""
        self._mode = mode
        logger.info(f"Bot mode changed to: {mode.value}")
        try:
            from services.enhanced_scanner import get_enhanced_scanner
            scanner = get_enhanced_scanner()
            if scanner is not None:
                scanner.enable_auto_execute(
                    enabled=(mode == BotMode.AUTONOMOUS),
                    min_win_rate=0.55,
                    min_priority="high",
                )
        except Exception as e:
            logger.warning(f"Scanner sync on mode change failed (non-fatal): {e}")
        # Persist state asynchronously
        asyncio.create_task(self._save_state())
    
    def get_mode(self) -> BotMode:
        return self._mode
    
    def update_risk_params(self, **kwargs):
        """Update risk parameters and persist to MongoDB"""
        for key, value in kwargs.items():
            if not hasattr(self.risk_params, key):
                continue
            # 2026-05-01 v19.21 — special-case dict merge for per-setup R:R
            # overrides so a partial PUT doesn't wipe other operator-set
            # entries. PUT { "setup_min_rr": {"squeeze": 1.3} } now merges
            # `squeeze: 1.3` in instead of replacing the whole dict.
            if key == "setup_min_rr" and isinstance(value, dict):
                merged = dict(self.risk_params.setup_min_rr or {})
                for k, v in value.items():
                    try:
                        merged[k] = float(v)
                    except (TypeError, ValueError):
                        continue
                self.risk_params.setup_min_rr = merged
                logger.info(f"Risk param merged: setup_min_rr += {len(value)} entries")
            else:
                setattr(self.risk_params, key, value)
                logger.info(f"Risk param updated: {key} = {value}")
        
        # Persist state after updating risk params
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._save_state())
            else:
                loop.run_until_complete(self._save_state())
        except Exception:
            pass  # State will be saved on next start/stop
    
    def set_watchlist(self, symbols: List[str]):
        """Set symbols to scan"""
        self._watchlist = [s.upper() for s in symbols]
        # Schedule state save (non-blocking)
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._save_state())
            else:
                loop.run_until_complete(self._save_state())
        except Exception:
            pass  # State will be saved on next start/stop
    
    def set_enabled_setups(self, setups: List[str]):
        """Set which setup types to trade"""
        self._enabled_setups = setups
        # Schedule state save (non-blocking)
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._save_state())
            else:
                loop.run_until_complete(self._save_state())
        except Exception:
            pass  # State will be saved on next start/stop
    
    def get_strategy_configs(self) -> Dict[str, Any]:
        """Get all strategy configurations"""
        result = {}
        for key, config in STRATEGY_CONFIG.items():
            result[key] = {
                "timeframe": config["timeframe"].value if isinstance(config["timeframe"], TradeTimeframe) else config["timeframe"],
                "trail_pct": config["trail_pct"],
                "scale_out_pcts": config["scale_out_pcts"],
                "close_at_eod": config["close_at_eod"]
            }
        return result
    
    def update_strategy_config(self, strategy: str, updates: Dict[str, Any]) -> bool:
        """Update a specific strategy configuration"""
        if strategy not in STRATEGY_CONFIG:
            return False
        config = STRATEGY_CONFIG[strategy]
        if "trail_pct" in updates:
            config["trail_pct"] = float(updates["trail_pct"])
        if "close_at_eod" in updates:
            config["close_at_eod"] = bool(updates["close_at_eod"])
        if "scale_out_pcts" in updates:
            pcts = updates["scale_out_pcts"]
            if isinstance(pcts, list) and len(pcts) >= 2:
                config["scale_out_pcts"] = [float(p) for p in pcts]
        if "timeframe" in updates:
            try:
                config["timeframe"] = TradeTimeframe(updates["timeframe"])
            except ValueError:
                pass
        logger.info(f"Strategy config updated: {strategy} -> {config}")
        return True
    
    def get_bot_context_for_ai(self) -> str:
        """Build a context string about bot state for the AI assistant"""
        lines = []
        lines.append("=== TRADING BOT STATUS ===")
        lines.append(f"Running: {self._running} | Mode: {self._mode.value}")
        lines.append(f"Capital: ${self.risk_params.starting_capital:,.0f} | Max Risk/Trade: ${self.risk_params.max_risk_per_trade:,.0f}")
        
        # Daily stats
        ds = self._daily_stats
        lines.append(f"\nToday's Stats: {ds.trades_executed} trades | {ds.trades_won}W/{ds.trades_lost}L | P&L: ${ds.gross_pnl:+,.2f}")
        if ds.trades_executed > 0:
            lines.append(f"Win Rate: {ds.win_rate:.0f}%")
        
        # Pending trades
        if self._pending_trades:
            lines.append(f"\nPENDING TRADES ({len(self._pending_trades)}):")
            for t in self._pending_trades.values():
                lines.append(f"  {t.symbol} {t.direction.value.upper()} | {t.setup_type} ({t.timeframe}) | Entry: ${t.entry_price:.2f} | Stop: ${t.stop_price:.2f} | R:R {t.risk_reward_ratio:.1f}:1 | Grade: {t.quality_grade}")
        
        # Open trades
        if self._open_trades:
            lines.append(f"\nOPEN TRADES ({len(self._open_trades)}):")
            for t in self._open_trades.values():
                pnl_str = f"${t.unrealized_pnl:+,.2f}" if t.unrealized_pnl else "N/A"
                lines.append(f"  {t.symbol} {t.direction.value.upper()} | {t.setup_type} ({t.timeframe}) | Entry: ${t.entry_price:.2f} | Current: ${t.current_price:.2f} | P&L: {pnl_str} | EOD Close: {t.close_at_eod}")
        
        # Closed trades (last 10)
        if self._closed_trades:
            recent_closed = self._closed_trades[-10:]
            lines.append(f"\nRECENT CLOSED TRADES ({len(self._closed_trades)} total, showing last {len(recent_closed)}):")
            for t in reversed(recent_closed):
                lines.append(f"  {t.symbol} {t.direction.value.upper()} | {t.setup_type} ({t.timeframe}) | P&L: ${t.realized_pnl:+,.2f} ({t.pnl_pct:+.1f}%) | Reason: {t.close_reason or 'N/A'}")
        
        # Strategy configs summary
        lines.append("\nSTRATEGY CONFIGS:")
        for key, cfg in STRATEGY_CONFIG.items():
            tf = cfg["timeframe"].value if isinstance(cfg["timeframe"], TradeTimeframe) else cfg["timeframe"]
            lines.append(f"  {key}: {tf} | trail {cfg['trail_pct']*100:.1f}% | EOD close: {cfg['close_at_eod']}")
        
        return "\n".join(lines)
    
    def get_all_trades_summary(self) -> Dict:
        """Get all trades for the AI Command Panel"""
        pending = [t.to_dict() for t in self._pending_trades.values()]
        open_trades = [t.to_dict() for t in self._open_trades.values()]
        closed = [t.to_dict() for t in self._closed_trades]
        return {
            "pending": pending,
            "open": open_trades,
            "closed": closed,
            "daily_stats": asdict(self._daily_stats)
        }
    
    # ==================== BOT CONTROL ====================
    
    def is_within_trading_hours(self) -> bool:
        """Check if current time is within allowed trading hours (Eastern Time)"""
        try:
            from datetime import timezone
            import pytz
            
            et_tz = pytz.timezone('America/New_York')
            now_et = datetime.now(et_tz)
            
            start_time = now_et.replace(
                hour=self.risk_params.trading_start_hour,
                minute=self.risk_params.trading_start_minute,
                second=0,
                microsecond=0
            )
            end_time = now_et.replace(
                hour=self.risk_params.trading_end_hour,
                minute=self.risk_params.trading_end_minute,
                second=0,
                microsecond=0
            )
            
            # Check if it's a weekday (Monday=0, Sunday=6)
            if now_et.weekday() >= 5:  # Saturday or Sunday
                return False
            
            return start_time <= now_et <= end_time
        except Exception as e:
            logger.warning(f"Error checking trading hours: {e}")
            return True  # Default to allowing trades if timezone check fails
    
    def update_account_value_from_ib(self, account_value: float):
        """Update risk parameters based on current account value from IB"""
        if account_value > 0:
            self.risk_params.starting_capital = account_value
            # Calculate max daily loss as 1% of account
            self.risk_params.max_daily_loss = account_value * (self.risk_params.max_daily_loss_pct / 100.0)
            logger.info(f"Updated account value: ${account_value:,.2f}, max daily loss: ${self.risk_params.max_daily_loss:,.2f}")
    
    async def start(self):
        """Start the trading bot"""
        if self._running:
            return
        
        self._running = True
        self._mode = BotMode.AUTONOMOUS if self._mode == BotMode.PAUSED else self._mode
        self._scan_task = asyncio.create_task(self._scan_loop())
        logger.info(f"🤖 Trading bot started in {self._mode.value} mode")
        logger.info(f"📊 Trading hours: {self.risk_params.trading_start_hour}:{self.risk_params.trading_start_minute:02d} - {self.risk_params.trading_end_hour}:{self.risk_params.trading_end_minute:02d} ET")
        logger.info(f"💰 Max position: {self.risk_params.max_position_pct}% of account, Max daily loss: {self.risk_params.max_daily_loss_pct}%")

        # 2026-04-30 — sync scanner auto-execute with the bot's persisted
        # mode on startup. Without this, every backend restart silently
        # leaves `scanner._auto_execute_enabled = False` even when
        # bot_state.mode == "autonomous", so HIGH-priority alerts never
        # auto-fire until the operator manually re-hits POST /trading-bot/mode.
        try:
            from services.enhanced_scanner import get_enhanced_scanner
            scanner = get_enhanced_scanner()
            if scanner is not None:
                scanner.enable_auto_execute(
                    enabled=(self._mode == BotMode.AUTONOMOUS),
                    min_win_rate=0.55,
                    min_priority="high",
                )
                logger.info(
                    f"⚙️  Scanner auto-execute synced from bot mode "
                    f"(mode={self._mode.value}, scanner_enabled="
                    f"{self._mode == BotMode.AUTONOMOUS})"
                )
        except Exception as e:
            logger.warning(f"Scanner sync on bot start failed (non-fatal): {e}")

        # Phase 4 (2026-04-22): Protect any orphan IB positions on startup.
        # Runs in the background — never block start on broker round-trips.
        if self._position_reconciler is not None:
            async def _startup_orphan_guard():
                try:
                    # Small delay so pusher has time to publish the position snapshot
                    await asyncio.sleep(15)
                    report = await self._position_reconciler.protect_orphan_positions(
                        self, dry_run=False,
                    )
                    n_prot = len(report.get("protected", []))
                    if n_prot:
                        logger.warning(f"🛡️ Startup orphan-guard placed {n_prot} emergency stops")
                except Exception as e:
                    logger.warning(f"Startup orphan-guard failed (non-fatal): {e}")
            asyncio.create_task(_startup_orphan_guard())

            # 2026-05-04 v19.31.1 — Auto-reconcile-at-boot.
            # Operator-facing toggle: when AUTO_RECONCILE_AT_BOOT=true is
            # set in backend/.env, every legitimate IB-only carryover
            # gets a `bot_trades` row + `_open_trades` entry materialized
            # the moment the pusher streams the position snapshot. Means
            # the operator literally never sees "RECONCILE 13" in the
            # morning anymore — the bot self-claims its own positions
            # the moment they're visible.
            #
            # Runs AFTER orphan-guard (20s vs 15s) on purpose:
            #   1. Orphan-guard places emergency stops first (fast, safe
            #      net for any positions IB has but bot doesn't track).
            #   2. Auto-reconcile then materializes the proper bot_trades
            #      rows so manage loop can trail/scale-out/EOD-close.
            #
            # Default OFF for safety. The operator who DOESN'T want this
            # (e.g. days they manually trade and don't want the bot
            # stealing tracking) just leaves the env var unset.
            import os as _os
            if _os.environ.get("AUTO_RECONCILE_AT_BOOT", "").strip().lower() in (
                "1", "true", "yes", "on"
            ):
                async def _startup_auto_reconcile():
                    """v19.34.13 (2026-05-06) — boot reconcile + 90s retry pass.

                    Operator reported 1 orphan persistently surviving the
                    initial 20s pass. Root cause: `direction_unstable`
                    skip — the reconciler requires 30s of continuous
                    direction observation, but on a cold boot the
                    observation history is empty. Fix: run a 2nd pass
                    90s later (60s after the first), by which point
                    every observation window has filled.
                    """
                    def _persist_boot_result(result, n_recon, n_skip, n_err, *, retry_pass=False):
                        try:
                            from database import get_database as _gdb
                            _db_br = _gdb()
                            if _db_br is None:
                                return
                            # v19.34.13 — persist skip reasons + retry
                            # marker so `/boot-reconcile-status` can
                            # surface WHY orphans were left behind
                            # instead of just the count.
                            _skipped_rows = [
                                {
                                    "symbol": s.get("symbol"),
                                    "reason": s.get("reason"),
                                    "detail": s.get("detail"),
                                }
                                for s in (result.get("skipped") or [])
                                if s.get("symbol")
                            ][:32]
                            _db_br["bot_state"].update_one(
                                {"_id": "last_auto_reconcile_at_boot"},
                                {"$set": {
                                    "ran_at": datetime.now(timezone.utc).isoformat(),
                                    "reconciled_count": n_recon,
                                    "skipped_count": n_skip,
                                    "errors_count": n_err,
                                    "symbols": [
                                        r.get("symbol") for r in (result.get("reconciled") or [])
                                        if r.get("symbol")
                                    ][:32],
                                    "skipped": _skipped_rows,
                                    "retry_pass": bool(retry_pass),
                                }},
                                upsert=True,
                            )
                        except Exception:
                            pass

                    async def _emit_boot_event(claimed_syms, n_recon, n_skip, n_err, *, retry_pass=False):
                        try:
                            from services.sentcom_service import emit_stream_event
                            tag = " (retry)" if retry_pass else ""
                            await emit_stream_event({
                                "kind": "info",
                                "event": "auto_reconcile_at_boot",
                                "text": (
                                    f"🔁 Auto-reconcile{tag} claimed {n_recon} orphan "
                                    f"position(s) at boot: "
                                    f"{', '.join(claimed_syms[:8])}"
                                    + (f" (+{len(claimed_syms)-8} more)"
                                       if len(claimed_syms) > 8 else "")
                                ),
                                "metadata": {
                                    "reconciled_count": n_recon,
                                    "skipped_count": n_skip,
                                    "errors_count": n_err,
                                    "symbols": claimed_syms,
                                    "retry_pass": retry_pass,
                                },
                            })
                        except Exception:
                            pass

                    async def _do_pass(retry_pass=False):
                        try:
                            result = await self.reconcile_orphan_positions(
                                all_orphans=True,
                            )
                            n_recon = len(result.get("reconciled", []))
                            n_skip = len(result.get("skipped", []))
                            n_err = len(result.get("errors", []))
                            tag = "[v19.34.13 RETRY]" if retry_pass else "[v19.31 AUTO-RECONCILE]"
                            if n_recon:
                                logger.warning(
                                    f"🔁 {tag} Boot reconcile claimed "
                                    f"{n_recon} orphan position(s); skipped={n_skip} "
                                    f"errors={n_err}"
                                )
                                _persist_boot_result(result, n_recon, n_skip, n_err, retry_pass=retry_pass)
                                claimed_syms = [
                                    r.get("symbol") for r in result.get("reconciled", [])
                                    if r.get("symbol")
                                ]
                                await _emit_boot_event(
                                    claimed_syms, n_recon, n_skip, n_err,
                                    retry_pass=retry_pass,
                                )
                            else:
                                logger.info(
                                    f"🔁 {tag} Boot reconcile found "
                                    f"nothing to claim (skipped={n_skip} errors={n_err})"
                                )
                                # Only overwrite the persisted state on
                                # the FIRST pass; retry-pass no-ops keep
                                # the original boot pill untouched.
                                if not retry_pass:
                                    _persist_boot_result(result, 0, n_skip, n_err)
                            return n_skip
                        except Exception as e:
                            logger.warning(
                                f"🔁 [v19.31 AUTO-RECONCILE] Boot reconcile failed "
                                f"(non-fatal): {e}"
                            )
                            return 0

                    try:
                        await asyncio.sleep(20)
                        first_skip = await _do_pass(retry_pass=False)

                        # v19.34.13 — only retry if the first pass left
                        # skipped orphans behind (avoids a useless 2nd
                        # call when there's nothing to clean up).
                        if first_skip > 0:
                            await asyncio.sleep(60)  # total 80s — direction-stability gate (30s) clears for any new arrival
                            await _do_pass(retry_pass=True)
                    except Exception as e:
                        logger.warning(
                            f"🔁 [v19.34.13 AUTO-RECONCILE] startup task failed "
                            f"(non-fatal): {e}"
                        )
                asyncio.create_task(_startup_auto_reconcile())

        # 2026-05-04 v19.31.13 — Realized-PnL auto-sync background task.
        # Operator's "I shouldn't have to click ↻ Recalc per row" feedback
        # after the v19.31.12 retroactive endpoint shipped. Every 30s we
        # scan `bot_trades` for `status=closed AND realized_pnl in (0, null,
        # missing) AND closed_at within last 24h`, dedupe by symbol, and
        # call the same helper as the operator's manual button. Skips
        # silently when no rows need attention so the loop is cheap when
        # the system is healthy.
        #
        # Wrapped in a top-level try/except so a Mongo blip can't crash
        # bot.start(). Honours `REALIZED_PNL_AUTOSYNC_ENABLED=false` env
        # for the rare operator who wants to disable.
        async def _realized_pnl_autosync_loop():
            import os as _os2
            interval_s = int(_os2.environ.get("REALIZED_PNL_AUTOSYNC_INTERVAL_S", "30") or 30)
            if interval_s < 5:
                interval_s = 5  # safety floor
            disabled = (
                _os2.environ.get("REALIZED_PNL_AUTOSYNC_ENABLED", "true").strip().lower()
                in ("0", "false", "no", "off")
            )
            if disabled:
                logger.info("[v19.31.13 PNL-AUTOSYNC] disabled by env")
                return

            # Lazy bind — avoid circular import at module load.
            try:
                from routers.diagnostics import _recalc_realized_pnl_for_symbol
                from database import get_database
            except Exception as e:
                logger.warning(f"[v19.31.13 PNL-AUTOSYNC] import failed: {e}")
                return

            # Initial 45s grace period: pusher snapshot + auto-reconcile
                # should both have completed.
            await asyncio.sleep(45)
            while self._running:
                try:
                    db = get_database()
                    if db is not None:
                        cutoff_iso = (
                            datetime.now(timezone.utc) - timedelta(hours=24)
                        ).isoformat()
                        # Find symbols with closed-but-unstamped rows.
                        cursor = db["bot_trades"].find(
                            {
                                "status": "closed",
                                "$or": [
                                    {"closed_at": {"$gte": cutoff_iso}},
                                    {"closed_at": None,
                                     "executed_at": {"$gte": cutoff_iso}},
                                ],
                                "$and": [{"$or": [
                                    {"realized_pnl": 0},
                                    {"realized_pnl": None},
                                    {"realized_pnl": {"$exists": False}},
                                ]}],
                            },
                            {"_id": 0, "symbol": 1},
                        )
                        symbols_to_recalc = sorted({
                            (r.get("symbol") or "").upper()
                            for r in cursor if r.get("symbol")
                        })
                        if symbols_to_recalc:
                            total_claimed = 0.0
                            total_rows_updated = 0
                            for sym in symbols_to_recalc:
                                try:
                                    res = await _recalc_realized_pnl_for_symbol(
                                        db, sym, days=2,
                                    )
                                    if res.get("success"):
                                        total_claimed += float(res.get("claimed") or 0)
                                        total_rows_updated += len(
                                            res.get("rows_updated") or []
                                        )
                                except Exception as ex:
                                    logger.debug(
                                        f"[v19.31.13 PNL-AUTOSYNC] {sym} skipped: {ex}"
                                    )
                            if total_rows_updated:
                                logger.info(
                                    f"[v19.31.13 PNL-AUTOSYNC] backfilled "
                                    f"{total_rows_updated} row(s) across "
                                    f"{len(symbols_to_recalc)} symbol(s); "
                                    f"net claimed ${total_claimed:+.2f}"
                                )
                                # Soft Unified Stream notice.
                                try:
                                    from services.sentcom_service import emit_stream_event
                                    await emit_stream_event({
                                        "kind": "info",
                                        "event": "realized_pnl_autosync_v19_31_13",
                                        "text": (
                                            f"📒 Realized PnL auto-sync claimed "
                                            f"{total_rows_updated} row(s) across "
                                            f"{len(symbols_to_recalc)} symbol(s)"
                                        ),
                                        "metadata": {
                                            "symbols": symbols_to_recalc[:32],
                                            "rows_updated": total_rows_updated,
                                            "net_claimed": round(total_claimed, 2),
                                        },
                                    })
                                except Exception:
                                    pass
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.debug(f"[v19.31.13 PNL-AUTOSYNC] loop tick failed: {e}")
                try:
                    await asyncio.sleep(interval_s)
                except asyncio.CancelledError:
                    raise

        try:
            self._pnl_autosync_task = asyncio.create_task(_realized_pnl_autosync_loop())
        except Exception as e:
            logger.warning(
                f"[v19.31.13 PNL-AUTOSYNC] failed to schedule (non-fatal): {e}"
            )

        # ─── v19.34 (2026-05-04) — Mid-bar tick stop-eval lifecycle ──
        # Bot's `_open_trades` dict is the source of truth. Every N
        # seconds we walk it and:
        #   • spawn a tick-bus subscriber task for every newly-opened
        #     trade (one task per (trade_id, symbol)) that runs the
        #     mid-bar stop check on each fresh quote.
        #   • cancel + clean up tasks whose trade_id is no longer in
        #     _open_trades (the trade was closed/swept).
        #
        # Wire-up is decoupled from individual insertion sites — there
        # are 8+ places that put into `_open_trades` (alert exec, recon-
        # ciler, lazy-reconcile, persistence load, bot_persistence load,
        # etc.) and instrumenting all of them would be brittle. Reaping
        # by diff every 2s is cheap and self-healing.
        #
        # Feature-flag: MID_BAR_TICK_EVAL_ENABLED=false (default OFF).
        # Even with the flag ON the manage-loop's bar-close stop check
        # still runs as the safety net; mid-bar is purely additive.
        self._midbar_tick_subs: Dict[str, asyncio.Task] = {}

        async def _midbar_tick_lifecycle_loop():
            import os as _os3
            disabled = (
                _os3.environ.get("MID_BAR_TICK_EVAL_ENABLED", "false")
                .strip().lower() in ("0", "false", "no", "off")
            )
            if disabled:
                logger.info(
                    "[v19.34 MID-BAR TICK] disabled by env "
                    "(MID_BAR_TICK_EVAL_ENABLED!=true)"
                )
                return
            try:
                from services.quote_tick_bus import get_quote_tick_bus
            except Exception as e:
                logger.warning(f"[v19.34 MID-BAR TICK] bus import failed: {e}")
                return
            bus = get_quote_tick_bus()
            poll_s = float(_os3.environ.get("MID_BAR_TICK_RECONCILE_S", "2.0") or 2.0)
            await asyncio.sleep(5)  # let the bot finish its initial state restore

            async def _subscriber(trade_id: str, symbol: str):
                """One task per open trade. Pulls ticks, runs mid-bar
                stop eval, exits when the trade is no longer open."""
                from services.position_manager import PositionManager
                pm: PositionManager = self._position_manager
                q, sym_u = bus.subscribe(symbol, queue_size=8)
                try:
                    while self._running:
                        try:
                            tick = await asyncio.wait_for(q.get(), timeout=10.0)
                        except asyncio.TimeoutError:
                            # Heartbeat — check the trade is still open
                            # so we exit promptly when it closes between
                            # ticks (e.g. EOD close, manual close).
                            if trade_id not in self._open_trades:
                                break
                            continue
                        trade = self._open_trades.get(trade_id)
                        if trade is None:
                            break
                        if getattr(trade, "status", None) and \
                                trade.status.value != "open":
                            break
                        # Run the per-trade stop eval. Its own try/except
                        # swallows errors so this loop never dies.
                        await pm.evaluate_single_trade_against_quote(
                            trade, self, tick,
                        )
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning(
                        f"[v19.34 MID-BAR TICK] subscriber {trade_id} "
                        f"sym={symbol} crashed: {e}"
                    )
                finally:
                    bus.unsubscribe(sym_u, q)

            while self._running:
                try:
                    open_ids = set(self._open_trades.keys())
                    sub_ids = set(self._midbar_tick_subs.keys())
                    # Spawn subscribers for newly-opened trades.
                    for tid in open_ids - sub_ids:
                        try:
                            trade = self._open_trades[tid]
                            symbol = trade.symbol
                            t = asyncio.create_task(_subscriber(tid, symbol))
                            self._midbar_tick_subs[tid] = t
                            logger.info(
                                f"[v19.34 MID-BAR TICK] +sub trade_id={tid} "
                                f"sym={symbol}"
                            )
                        except Exception as e:
                            logger.debug(
                                f"[v19.34 MID-BAR TICK] failed to spawn sub "
                                f"for {tid}: {e}"
                            )
                    # Cancel subscribers for trades no longer open.
                    for tid in sub_ids - open_ids:
                        t = self._midbar_tick_subs.pop(tid, None)
                        if t is not None and not t.done():
                            t.cancel()
                            try:
                                await t
                            except asyncio.CancelledError:
                                pass
                            except Exception:
                                pass
                            logger.info(
                                f"[v19.34 MID-BAR TICK] -sub trade_id={tid}"
                            )
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.debug(f"[v19.34 MID-BAR TICK] reconcile failed: {e}")
                try:
                    await asyncio.sleep(poll_s)
                except asyncio.CancelledError:
                    raise

        try:
            self._midbar_tick_lifecycle_task = asyncio.create_task(
                _midbar_tick_lifecycle_loop()
            )
        except Exception as e:
            logger.warning(
                f"[v19.34 MID-BAR TICK] failed to schedule (non-fatal): {e}"
            )

        # 2026-05-05 v19.34.7 — Selective boot zombie-bracket sweeper.
        # Operator-driven: at startup, after the pusher publishes its
        # snapshot (~30s), call POST /api/trading-bot/eod-validate-overnight-orders
        # in DRY-RUN mode and log the report. We intentionally do NOT
        # auto-cancel at boot — the operator should review the wrong-TIF
        # / orphan list before any cancels go through. Auto-cancel can
        # still be triggered manually via the same endpoint with confirm.
        # Feature-flag: BOOT_ZOMBIE_SWEEP_ENABLED=true (default ON).
        if os.environ.get("BOOT_ZOMBIE_SWEEP_ENABLED", "true").lower() in (
            "true", "1", "yes", "on"
        ):
            async def _boot_zombie_sweep():
                try:
                    # Wait for pusher snapshot + auto-reconcile to settle
                    # before we read order_queue (otherwise we may sweep
                    # rows that are about to flip status).
                    await asyncio.sleep(30)
                    from routers.trading_bot import eod_validate_overnight_orders
                    report = await eod_validate_overnight_orders({"dry_run": True})
                    if not report.get("success"):
                        logger.warning(
                            "[v19.34.7 BOOT-SWEEP] dry-run failed: %s",
                            report.get("error"),
                        )
                        return
                    summary = report.get("summary") or {}
                    if (summary.get("orphans", 0) + summary.get("wrong_tif", 0)) > 0:
                        logger.warning(
                            "[v19.34.7 BOOT-SWEEP] flagged %s orphan(s) + %s "
                            "wrong-tif row(s) at startup. Total active=%s, "
                            "ok=%s. Review via POST /api/trading-bot/"
                            "eod-validate-overnight-orders {confirm: \"CANCEL_"
                            "ORPHANS\", dry_run: false} to clean up.",
                            summary.get("orphans"),
                            summary.get("wrong_tif"),
                            summary.get("total_active"),
                            summary.get("ok"),
                        )
                        # Surface the warning in the operator stream
                        try:
                            from services.sentcom_service import emit_stream_event
                            await emit_stream_event({
                                "kind": "alert",
                                "severity": "warning",
                                "event": "boot_zombie_sweep",
                                "text": (
                                    f"⚠️ Boot sweep: {summary.get('orphans')} "
                                    f"orphan + {summary.get('wrong_tif')} wrong-"
                                    f"tif overnight bracket(s) found"
                                ),
                                "metadata": summary,
                            })
                        except Exception:
                            pass
                        # v19.34.16 — Operator-approved per-trade lifecycle
                        # persistence so each flagged orphan / wrong-tif
                        # leg lands a row in `bracket_lifecycle_events`
                        # (TTL 7d). Powers the V5 "📜 History" panel for
                        # boot-detected zombies.
                        try:
                            from services.bracket_reissue_service import (
                                _persist_lifecycle_event,
                            )
                            for r in report.get("rows") or []:
                                cls = r.get("classification")
                                if cls not in ("orphan_no_parent",
                                               "wrong_tif_intraday_parent"):
                                    continue
                                await _persist_lifecycle_event(
                                    bot=self,
                                    event={
                                        "phase": "boot_zombie_sweep",
                                        "reason": cls,
                                        "trade_id": r.get("trade_id"),
                                        "symbol": r.get("symbol"),
                                        "order_id": r.get("order_id"),
                                        "order_type": r.get("order_type"),
                                        "tif_summary": r.get("tif_summary") or {},
                                        "parent_status": r.get("parent_status"),
                                        "parent_trade_style": r.get("parent_trade_style"),
                                        "parent_timeframe": r.get("parent_timeframe"),
                                        "queued_at": r.get("queued_at"),
                                        "detail": r.get("reason"),
                                        "summary_at_sweep": summary,
                                    },
                                )
                        except Exception as e:
                            logger.debug(
                                f"[v19.34.16 BOOT-SWEEP] lifecycle persist failed: {e}"
                            )
                        # v19.34.16 — Persist a sweep-level summary row
                        # only when findings exist (operator approved
                        # "skip clean sweeps to reduce noise").
                        try:
                            from services.bracket_reissue_service import (
                                _persist_lifecycle_event as _p2,
                            )
                            await _p2(
                                bot=self,
                                event={
                                    "phase": "boot_zombie_sweep_summary",
                                    "reason": "boot_sweep_findings",
                                    "trade_id": None,
                                    "symbol": None,
                                    "summary": summary,
                                    "row_count": len(report.get("rows") or []),
                                },
                            )
                        except Exception:
                            pass
                    else:
                        logger.info(
                            "[v19.34.7 BOOT-SWEEP] clean — no orphans / wrong-tif "
                            "rows (active=%s, ok=%s)",
                            summary.get("total_active"), summary.get("ok"),
                        )
                except Exception as e:
                    logger.warning(
                        "[v19.34.7 BOOT-SWEEP] failed (non-fatal): %s", e,
                    )
            try:
                asyncio.create_task(_boot_zombie_sweep())
            except Exception as e:
                logger.debug(f"[v19.34.7 BOOT-SWEEP] schedule failed: {e}")

        # ─── v19.34.17 (2026-05-06) — EOD-close policy migration ──────
        # Operator caught 2026-05-06 EOD: SBUX/ADBE/LITE/LIN reconciled
        # orphan positions stayed OPEN past the 3:55pm flatten window
        # because the v19.24 reconciler stamped `close_at_eod=False`.
        # Operator-approved policy: orphan-reconciled + drift-excess
        # slices ALWAYS flatten at EOD (bot has no thesis tying them to
        # a multi-day swing). The reconciler defaults are now `True`
        # for new spawns; this migration retro-flips already-open trades
        # whose provenance is reconciled. Bot-originated `day_swing`/
        # `position` trades are NOT touched.
        async def _eod_policy_migration():
            try:
                await asyncio.sleep(45)  # let boot reconcile + DB load settle
                flipped = []
                for tid, t in list(self._open_trades.items()):
                    eb = (getattr(t, "entered_by", "") or "").lower()
                    is_reconciled = (
                        eb.startswith("reconciled_") or
                        getattr(t, "trade_style", "") == "reconciled"
                    )
                    if is_reconciled and getattr(t, "close_at_eod", False) is False:
                        t.close_at_eod = True
                        t.notes = (t.notes or "") + (
                            " [v19.34.17 EOD policy migration: close_at_eod False→True]"
                        )
                        flipped.append({"trade_id": tid, "symbol": t.symbol})
                        save_fn = getattr(self, "_save_trade", None) or getattr(self, "_persist_trade", None)
                        if save_fn:
                            try:
                                res = save_fn(t)
                                if asyncio.iscoroutine(res):
                                    await res
                            except Exception:
                                pass
                if flipped:
                    logger.warning(
                        "[v19.34.17 EOD-MIGRATION] flipped close_at_eod False→True "
                        "on %d reconciled trade(s): %s",
                        len(flipped), [f["symbol"] for f in flipped][:8],
                    )
                    try:
                        from services.sentcom_service import emit_stream_event
                        await emit_stream_event({
                            "kind": "info",
                            "event": "eod_policy_migration_v19_34_17",
                            "text": (
                                f"⚙ EOD policy migration: {len(flipped)} reconciled "
                                f"position(s) will now flatten at EOD"
                            ),
                            "metadata": {"flipped": flipped},
                        })
                    except Exception:
                        pass
                else:
                    logger.info("[v19.34.17 EOD-MIGRATION] no reconciled trades needed flipping")
            except Exception as e:
                logger.warning(f"[v19.34.17 EOD-MIGRATION] failed: {e}")
        try:
            asyncio.create_task(_eod_policy_migration())
        except Exception as e:
            logger.debug(f"[v19.34.17 EOD-MIGRATION] schedule failed: {e}")

        # ─── v19.34.15b (2026-05-06) — Share-count drift reconciler ──
        # 24/7 background loop that calls `reconcile_share_drift` every
        # 30s. Closes the gap from the operator-caught UPS bug where
        # `[REJECTED: Bracket unknown]` parent-fill races leak naked
        # shares onto the IB account. The orphan reconciler skips
        # already-tracked symbols, so this is the only path that
        # detects share-COUNT drift on tracked symbols.
        # Feature-flag: SHARE_DRIFT_RECONCILE_ENABLED=true (default ON).
        # Interval: SHARE_DRIFT_RECONCILE_INTERVAL_S=30 (default 30s).
        if os.environ.get("SHARE_DRIFT_RECONCILE_ENABLED", "true").lower() in (
            "true", "1", "yes", "on"
        ):
            interval_s = int(
                os.environ.get("SHARE_DRIFT_RECONCILE_INTERVAL_S", "30") or 30
            )
            if interval_s < 10:
                interval_s = 10  # safety floor

            async def _share_drift_loop():
                # Initial grace so pusher snapshot + boot-reconcile settle.
                await asyncio.sleep(60)
                logger.info(
                    "[v19.34.15b DRIFT-LOOP] started, interval=%ss", interval_s,
                )
                # v19.34.18 — diagnostic state for `/share-drift-status`.
                self._share_drift_diag = {
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "interval_s": interval_s,
                    "tick_count": 0,
                    "last_tick_at": None,
                    "last_tick_status": "pending",
                    "last_tick_error": None,
                    "last_result_summary": None,
                    "last_drifts_detected": [],
                    "last_drifts_resolved": [],
                    "consecutive_failures": 0,
                }
                while self._running:
                    tick_started = datetime.now(timezone.utc)
                    try:
                        from routers.ib import is_pusher_connected
                        if not is_pusher_connected():
                            self._share_drift_diag["last_tick_status"] = "skipped_no_pusher"
                            self._share_drift_diag["last_tick_at"] = tick_started.isoformat()
                            self._share_drift_diag["tick_count"] += 1
                        else:
                            result = await self._position_reconciler.reconcile_share_drift(
                                self,
                                drift_threshold=1,
                                auto_resolve=True,
                            )
                            self._share_drift_diag["tick_count"] += 1
                            self._share_drift_diag["last_tick_at"] = tick_started.isoformat()
                            self._share_drift_diag["last_tick_status"] = "ok" if result.get("success") else "error"
                            self._share_drift_diag["last_tick_error"] = result.get("error")
                            self._share_drift_diag["last_result_summary"] = {
                                "detected": len(result.get("drifts_detected") or []),
                                "resolved": len(result.get("drifts_resolved") or []),
                                "skipped": len(result.get("skipped") or []),
                                "errors": len(result.get("errors") or []),
                            }
                            self._share_drift_diag["last_drifts_detected"] = (result.get("drifts_detected") or [])[:10]
                            self._share_drift_diag["last_drifts_resolved"] = (result.get("drifts_resolved") or [])[:10]
                            self._share_drift_diag["consecutive_failures"] = 0
                            if result.get("drifts_resolved"):
                                logger.warning(
                                    "[v19.34.15b DRIFT-LOOP] resolved %d drift(s): %s",
                                    len(result["drifts_resolved"]),
                                    [d.get("symbol") for d in result["drifts_resolved"]][:8],
                                )
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        self._share_drift_diag["last_tick_status"] = "exception"
                        self._share_drift_diag["last_tick_error"] = f"{type(e).__name__}: {e}"
                        self._share_drift_diag["last_tick_at"] = tick_started.isoformat()
                        self._share_drift_diag["consecutive_failures"] = (
                            self._share_drift_diag.get("consecutive_failures", 0) + 1
                        )
                        logger.warning(f"[v19.34.15b DRIFT-LOOP] tick failed: {e}")
                    try:
                        await asyncio.sleep(interval_s)
                    except asyncio.CancelledError:
                        raise

            try:
                self._share_drift_task = asyncio.create_task(_share_drift_loop())
            except Exception as e:
                logger.warning(
                    f"[v19.34.15b DRIFT-LOOP] failed to schedule (non-fatal): {e}"
                )

        # ─── v19.34.10 (2026-05-06) — State integrity watchdog ──────
        # Catches drift between in-memory `risk_params` and persisted
        # `bot_state.risk_params` in MongoDB (the v19.34.9 root cause
        # class). Per-field policy: capital/limit fields → Mongo wins;
        # setup_min_rr → memory wins. CRITICAL stream event on drift.
        # Default ON; flip via STATE_INTEGRITY_CHECK_ENABLED=false.
        try:
            from services.state_integrity_service import get_state_integrity_service
            self._integrity_service = get_state_integrity_service()
            await self._integrity_service.start(self)
        except Exception as e:
            logger.warning(f"[v19.34.10 INTEGRITY] schedule failed (non-fatal): {e}")

        # Persist state
        await self._save_state()
    
    async def stop(self):
        """Stop the trading bot"""
        self._running = False
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
        # v19.31.13 — also cancel the realized-PnL auto-sync background task.
        task = getattr(self, "_pnl_autosync_task", None)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        # v19.34.15b — cancel the share-count drift loop if it's running.
        sdt = getattr(self, "_share_drift_task", None)
        if sdt is not None:
            sdt.cancel()
            try:
                await sdt
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        # v19.34 — cancel the mid-bar tick lifecycle loop + all per-trade
        # subscriber tasks so they don't leak across hot-reloads.
        lt = getattr(self, "_midbar_tick_lifecycle_task", None)
        if lt is not None:
            lt.cancel()
            try:
                await lt
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        midbar_subs = getattr(self, "_midbar_tick_subs", {}) or {}
        for tid, t in list(midbar_subs.items()):
            if t is not None and not t.done():
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
        if isinstance(midbar_subs, dict):
            midbar_subs.clear()
        # v19.34.10 — stop integrity watchdog cleanly.
        integ = getattr(self, "_integrity_service", None)
        if integ is not None:
            try:
                await integ.stop()
            except Exception:
                pass
        logger.info("Trading bot stopped")
        
        # Persist state
        await self._save_state()
    
    async def _scan_loop(self):
        """Main scanning loop - runs when bot is active"""
        scan_count = 0
        print(f"🤖 [TradingBot] Scan loop started - interval: {self._scan_interval}s")
        while self._running:
            try:
                # 2026-04-30 — collection_mode + focus_mode guards now gate
                # ONLY `_scan_for_opportunities` (new alert intake), NOT
                # `_update_open_positions` / `_check_eod_close`. A live
                # position with no bot polling is a real safety risk: a
                # stop hit during a data-fill would never close, an EOD
                # scalp would carry into next session. Position management
                # must run during ALL of:
                #   - collection mode (data-fill jobs)
                #   - focus mode (training / backtesting)
                # Account refresh + daily loss check + trading hours
                # also stay up since the bot needs to know its own state
                # before it tries to close anything.
                pause_intake = False
                pause_reason = ""
                try:
                    from services.collection_mode import is_active as _collection_active
                    if _collection_active():
                        pause_intake = True
                        pause_reason = "collection mode active"
                except Exception:
                    pass
                if not pause_intake:
                    try:
                        from services.focus_mode_manager import focus_mode_manager
                        if not focus_mode_manager.should_run_task('trading_bot_scan'):
                            pause_intake = True
                            pause_reason = "focus mode (training/backtesting)"
                    except Exception:
                        pass
                if pause_intake and scan_count % 120 == 0:
                    print(f"📦 [TradingBot] Alert intake paused ({pause_reason}); position management continues")

                await self._update_account_from_ib()

                # Check daily loss limit (1% of account)
                if self.risk_params.max_daily_loss > 0 and self._daily_stats.net_pnl <= -self.risk_params.max_daily_loss:
                    if not self._daily_stats.daily_limit_hit:
                        self._daily_stats.daily_limit_hit = True
                        print(f"🛑 [TradingBot] Daily loss limit hit: ${self._daily_stats.net_pnl:.2f}")
                    await asyncio.sleep(60)
                    continue

                # Check trading hours (7:30 AM - 5:00 PM ET)
                if not self.is_within_trading_hours():
                    if scan_count % 60 == 0:  # Log every ~30 min
                        print("⏰ [TradingBot] Outside trading hours (7:30 AM - 5:00 PM ET)")
                    await asyncio.sleep(self._scan_interval)
                    scan_count += 1
                    continue

                # Skip if paused
                if self._mode == BotMode.PAUSED:
                    await asyncio.sleep(self._scan_interval)
                    continue

                # Log scan activity periodically
                scan_count += 1
                if scan_count % 10 == 1:  # Log every 10th scan (~5 min)
                    mode_str = "🟢 AUTO" if self._mode == BotMode.AUTONOMOUS else "🟡 CONFIRM"
                    open_count = len(self._open_trades)
                    pending_count = len(self._pending_trades)
                    pnl_str = f"${self._daily_stats.net_pnl:+,.2f}" if self._daily_stats.net_pnl != 0 else "$0"
                    intake_tag = " | 📦 INTAKE-PAUSED" if pause_intake else ""
                    print(f"[TradingBot] Scan #{scan_count} | {mode_str} | Open: {open_count} | Pending: {pending_count} | P&L: {pnl_str}{intake_tag}")

                # Alert intake — gated by collection/focus mode. Keeps the
                # bot from creating NEW trades during data-fills, but
                # everything below still runs so OPEN trades stay managed.
                #
                # v19.30 (2026-05-01) — wrap each phase in asyncio.wait_for
                # to bound worst-case scan-cycle duration. Previously a
                # slow ML eval / hung Mongo aggregation could block the
                # event loop for 44-61s (see EVENT LOOP BLOCKED warnings
                # in /tmp/backend.log on 2026-05-01 morning). Now each
                # phase has a hard wall: opportunity scan = 20s, position
                # update = 8s, EOD check = 5s. If we exceed any wall,
                # log + skip THIS iteration and continue on the next
                # tick. Total worst-case per scan: ~33s vs unbounded.
                _SCAN_WALL_S = 20.0
                _POS_WALL_S = 8.0
                _EOD_WALL_S = 5.0
                if not pause_intake:
                    try:
                        await asyncio.wait_for(self._scan_for_opportunities(), timeout=_SCAN_WALL_S)
                    except asyncio.TimeoutError:
                        print(f"⚠️ [TradingBot] _scan_for_opportunities exceeded {_SCAN_WALL_S}s budget — skipping this cycle")

                # Update open positions — runs unconditionally so stops,
                # targets, and trailing logic always trigger even during
                # data-fills. THIS IS THE SAFETY-CRITICAL CHANGE.
                try:
                    await asyncio.wait_for(self._update_open_positions(), timeout=_POS_WALL_S)
                except asyncio.TimeoutError:
                    print(f"⚠️ [TradingBot] _update_open_positions exceeded {_POS_WALL_S}s budget — skipping this cycle")

                # Check for EOD close on scalp/intraday trades — also
                # safety-critical during data-fills (an EOD scalp must
                # close even if the data-fill is still running).
                try:
                    await asyncio.wait_for(self._check_eod_close(), timeout=_EOD_WALL_S)
                except asyncio.TimeoutError:
                    print(f"⚠️ [TradingBot] _check_eod_close exceeded {_EOD_WALL_S}s budget — skipping this cycle")

            except Exception as e:
                print(f"❌ [TradingBot] Scan loop error: {e}")

            await asyncio.sleep(self._scan_interval)
    def _compute_live_unrealized_pnl(self) -> tuple:
        """Sum unrealized P&L across all open trades, gated on quote freshness.

        Returns (total_unrealized_usd, awaiting_quotes). When any open trade
        hasn't received its first IB quote yet (`current_price` is 0 or
        `fill_price` is 0/None), `awaiting_quotes=True` and the returned PnL
        is 0 — the caller MUST NOT feed garbage unrealized numbers into the
        safety guardrails or the kill-switch will latch on startup. See
        `_execute_trade` for the consumer.
        """
        total = 0.0
        awaiting = False
        for t in self._open_trades.values():
            try:
                fill = float(getattr(t, "fill_price", 0) or 0)
                cur = float(getattr(t, "current_price", 0) or 0)
                if fill <= 0 or cur <= 0:
                    awaiting = True
                    continue
                total += float(getattr(t, "unrealized_pnl", 0) or 0)
            except Exception:
                awaiting = True
                continue
        return (0.0 if awaiting else total), awaiting


    
    async def _update_account_from_ib(self):
        """Update account value from IB pushed data"""
        try:
            import routers.ib as ib_module
            ib_data = ib_module.get_pushed_data()
            if ib_data.get("connected"):
                account = ib_data.get("account", {})
                # Try to get NetLiquidation from account data (handles nested dict format)
                net_liq_data = account.get("NetLiquidation-S") or account.get("NetLiquidation")
                if net_liq_data:
                    try:
                        # Handle nested dict format: {"value": "997162.22", "currency": "USD", ...}
                        if isinstance(net_liq_data, dict):
                            value = float(net_liq_data.get("value", 0))
                        else:
                            value = float(net_liq_data)
                        
                        if value > 0 and abs(value - self.risk_params.starting_capital) > 100:  # Only update if changed by more than $100
                            self.update_account_value_from_ib(value)
                    except (ValueError, TypeError) as e:
                        logger.debug(f"Could not parse NetLiquidation: {e}")
        except Exception as e:
            logger.debug(f"Could not update account from IB: {e}")
    
    # ==================== OPPORTUNITY SCANNING ====================
    
    async def _scan_for_opportunities(self):
        """Scan for trade opportunities using alert system"""
        if not self._alert_system:
            print("⚠️ [TradingBot] No alert system configured - skipping scan")
            return
        
        # Check max open positions
        if len(self._open_trades) >= self.risk_params.max_open_positions:
            # 2026-04-28: was a silent return — now logs into Bot's Brain
            # so operator sees the cap is what's gating new entries.
            self.record_rejection(
                symbol="—",
                setup_type="any",
                direction="",
                reason_code="max_open_positions",
                context={"cap": self.risk_params.max_open_positions},
            )
            return
        
        try:
            # Get alerts from existing system
            alerts = await self._get_trade_alerts()
            
            if alerts:
                print(f"📡 [TradingBot] Found {len(alerts)} eligible alerts to evaluate")
            
            # Alert de-duplication (2026-04-21): hard veto BEFORE confidence gate.
            # Blocks repeat fires on open positions AND 5-min cooldown per
            # (symbol, setup, direction) to stop scanner spam from stacking losers.
            from services.alert_deduplicator import get_deduplicator
            _dedup = get_deduplicator()

            for alert in alerts:
                symbol = alert.get('symbol', 'UNKNOWN')
                setup = alert.get('setup_type', 'unknown')
                direction = alert.get('direction', 'long')

                dedup_result = _dedup.should_skip(
                    symbol=symbol,
                    setup_type=setup,
                    direction=direction,
                    open_trades=list(self._open_trades.values()) + list(self._pending_trades.values()),
                )
                if dedup_result.skip:
                    print(f"🛑 [TradingBot] Dedup skip {symbol} {setup} {direction}: {dedup_result.reason}")
                    # 2026-04-28: surface a wordy "why I passed" narrative
                    # in Bot's Brain so operator sees the full reasoning,
                    # not just the silent skip.
                    reason_lower = (dedup_result.reason or "").lower()
                    if "cooldown" in reason_lower:
                        rcode = "dedup_cooldown"
                    elif "open" in reason_lower or "position" in reason_lower:
                        rcode = "dedup_open_position"
                    else:
                        rcode = "dedup_open_position"
                    self.record_rejection(
                        symbol=symbol, setup_type=setup, direction=direction,
                        reason_code=rcode,
                        context={
                            "why": dedup_result.reason,
                            "cooldown_seconds_left": getattr(dedup_result, "cooldown_seconds_left", None),
                        },
                    )
                    continue

                # Skip if already have position in this symbol (safety net)
                if any(t.symbol == alert.get('symbol') for t in self._open_trades.values()):
                    self.record_rejection(
                        symbol=symbol, setup_type=setup, direction=direction,
                        reason_code="position_exists", context={},
                    )
                    continue

                # Skip if pending trade exists
                if any(t.symbol == alert.get('symbol') for t in self._pending_trades.values()):
                    self.record_rejection(
                        symbol=symbol, setup_type=setup, direction=direction,
                        reason_code="pending_trade_exists", context={},
                    )
                    continue

                # Mark alert as fired (starts cooldown) BEFORE heavy evaluation
                _dedup.mark_fired(symbol, setup, direction)

                # Reset the evaluator's specific-rejection flag. The evaluator
                # sets this flag to True whenever it records a specific
                # reason_code (no_price / smart_filter_skip / gate_skip /
                # position_size_zero / rr_below_min / ai_consultation_block /
                # evaluator_exception). The catch-all below only fires when
                # this flag is still False, preventing double-recording.
                # 2026-04-29 (afternoon-14).
                self._last_evaluator_rejection_recorded = False

                # Evaluate and create trade opportunity
                print(f"🔍 [TradingBot] Evaluating {symbol} {setup}...")
                trade = await self._evaluate_opportunity(alert)
                
                # Yield to event loop to prevent blocking (keeps WebSocket alive)
                await asyncio.sleep(0)
                
                if trade:
                    print(f"✅ [TradingBot] Trade created for {symbol}: {trade.direction.value} {trade.shares} shares @ ${trade.entry_price:.2f}")
                    if self._mode == BotMode.AUTONOMOUS:
                        # Execute immediately
                        print(f"🚀 [TradingBot] AUTONOMOUS MODE: Executing {symbol} trade...")
                        await self._execute_trade(trade)
                    else:
                        # Add to pending for confirmation
                        self._pending_trades[trade.id] = trade
                        await self._notify_trade_update(trade, "pending")
                        print(f"⏸️ [TradingBot] Added {symbol} to pending trades")
                else:
                    print(f"❌ [TradingBot] {symbol} {setup} did not meet criteria")
                    # 2026-04-28: capture the post-evaluation rejection
                    # so operator sees a narrative, not just the bare
                    # "did not meet criteria" log line.
                    # 2026-04-29 (afternoon-14): only fires the generic
                    # `evaluator_veto_unknown` if the evaluator did NOT
                    # already record a specific reason_code. Otherwise
                    # we'd double-count rejections in the analytics.
                    if not getattr(self, "_last_evaluator_rejection_recorded", False):
                        self.record_rejection(
                            symbol=symbol, setup_type=setup, direction=direction,
                            reason_code="evaluator_veto_unknown",
                            context={
                                "why": "evaluator returned no trade without recording a specific reason — likely a new return-None path",
                            },
                        )
                    
        except Exception as e:
            print(f"❌ [TradingBot] Scan error: {e}")
            import traceback
            traceback.print_exc()
    
    async def _get_trade_alerts(self) -> List[Dict]:
        """Get trade alerts from enhanced scanner"""
        alerts = []
        
        try:
            # Use enhanced scanner (primary) - same instance as live scanner API
            from services.enhanced_scanner import get_enhanced_scanner
            scanner = get_enhanced_scanner()
            
            # Get current live alerts
            scanner_alerts = scanner.get_live_alerts()
            print(f"📊 [TradingBot] Scanner ID: {id(scanner)}, has {len(scanner_alerts)} raw alerts, running: {scanner._running}")
            
            # Debug: show live alerts dict size
            print(f"   Live alerts dict size: {len(scanner._live_alerts)}")
            
            for alert in scanner_alerts:
                # Convert LiveAlert to dict format for trading bot
                alert_dict = {
                    'symbol': alert.symbol,
                    'setup_type': alert.setup_type,
                    'direction': alert.direction,
                    'current_price': alert.current_price,
                    'trigger_price': alert.trigger_price,
                    'stop_price': alert.stop_loss,
                    'targets': [alert.target] if alert.target else [],
                    'score': int((alert.trigger_probability or 0.5) * 100),
                    'trigger_probability': alert.trigger_probability or 0.5,
                    'headline': alert.headline,
                    'technical_reasons': alert.reasoning or [],
                    'warnings': [],
                    'priority': alert.priority.value if alert.priority else 'medium',
                    'tape_confirmation': alert.tape_confirmation,
                    'strategy_win_rate': alert.strategy_win_rate,
                    'auto_execute_eligible': alert.auto_execute_eligible
                }
                
                # 2026-05-01 v19.20 — skip watchlist-only setups silently.
                # These are EOD carry-forward tags and pre-trigger proximity
                # warnings that fire for tomorrow's plan / early warnings,
                # not for live evaluation. Surfacing them as "setup_disabled"
                # rejections every cycle was flooding the Deep Feed with
                # noise while the alerts themselves are still consumed by
                # gameplan_service for next-day watchlists.
                if alert.setup_type in self._watchlist_only_setups:
                    continue

                # Check if setup is enabled.
                # 2026-05-01 v19.20 — also strip `_confirmed` suffix so
                # confirmation variants (e.g. `range_break_confirmed`,
                # `breakout_confirmed`, `breakdown_confirmed`) resolve to
                # their already-enabled base setup. Previously the splitter
                # only stripped `_long`/`_short`, leaving confirmation
                # variants perpetually rejected as "setup_disabled".
                base_setup = (
                    alert.setup_type
                    .rsplit("_long", 1)[0]
                    .rsplit("_short", 1)[0]
                    .rsplit("_confirmed", 1)[0]
                )
                if base_setup in self._enabled_setups or alert.setup_type in self._enabled_setups:
                    alerts.append(alert_dict)
                    print(f"   ✅ {alert.symbol} {alert.setup_type} passed filter")
                else:
                    print(f"   ⏭️ {alert.symbol} {alert.setup_type} not in enabled setups")
                    # 2026-04-28: surface the silent setup-disabled skip
                    # in Bot's Brain. Operator's biggest "what is the bot
                    # thinking?" gap was right here — alerts arriving but
                    # never even reaching evaluation, with no UI breadcrumb.
                    self.record_rejection(
                        symbol=alert.symbol,
                        setup_type=alert.setup_type,
                        direction=alert.direction or "long",
                        reason_code="setup_disabled",
                        context={"base_setup": base_setup},
                    )
            
        except Exception as e:
            print(f"❌ [TradingBot] Error getting alerts: {e}")
            import traceback
            traceback.print_exc()
        
        if alerts:
            print(f"✅ [TradingBot] {len(alerts)} alerts ready for evaluation")
        
        return alerts[:20]  # Top 20 alerts
    
    async def _evaluate_opportunity(self, alert: Dict) -> Optional[BotTrade]:
        """Evaluate an alert — delegated to OpportunityEvaluator module."""
        return await self._opportunity_evaluator.evaluate_opportunity(alert, self)

    def _calculate_position_size(self, entry_price: float, stop_price: float, direction: TradeDirection, atr: float = None, atr_percent: float = None) -> Tuple[int, float]:
        """Position sizing — delegated to OpportunityEvaluator module."""
        return self._opportunity_evaluator.calculate_position_size(entry_price, stop_price, direction, self, atr, atr_percent)

    def calculate_atr_based_stop(self, entry_price: float, direction: TradeDirection, atr: float, setup_type: str = None) -> float:
        """ATR-based stop — delegated to OpportunityEvaluator module."""
        return self._opportunity_evaluator.calculate_atr_based_stop(entry_price, direction, atr, setup_type, self)

    def _score_to_grade(self, score: int) -> str:
        """Score to grade — delegated to OpportunityEvaluator module."""
        return self._opportunity_evaluator.score_to_grade(score)

    def _estimate_duration(self, setup_type: str) -> str:
        """Duration estimate — delegated to OpportunityEvaluator module."""
        return self._opportunity_evaluator.estimate_duration(setup_type)
    
    # ==================== ENHANCED INTELLIGENCE GATHERING ====================
    
    async def _gather_trade_intelligence(self, symbol: str, alert: Dict) -> Dict[str, Any]:
        """Delegates to TradeIntelligence module."""
        self._trade_intel.set_services(
            web_research=self.web_research,
            technical_service=self.technical_service,
            quality_service=getattr(self, '_quality_service', None),
        )
        return await self._trade_intel.gather(symbol, alert)

    def _analyze_news_sentiment(self, news_result) -> str:
        """Delegates to TradeIntelligence module."""
        return self._trade_intel._analyze_news_sentiment(news_result)

    def _extract_news_topics(self, news_result) -> List[str]:
        """Delegates to TradeIntelligence module."""
        return self._trade_intel._extract_news_topics(news_result)

    def _analyze_intelligence(self, intelligence: Dict, alert: Dict):
        """Delegates to TradeIntelligence module."""
        self._trade_intel.analyze(intelligence, alert)

    def _calculate_intelligence_adjustment(self, intelligence: Dict) -> int:
        """Delegates to TradeIntelligence module."""
        return self._trade_intel.calculate_adjustment(intelligence)

    def _build_entry_context(
        self, alert: Dict, intelligence: Dict, regime: str,
        regime_score: float, filter_action: str, filter_win_rate: float,
        atr: float, atr_percent: float, confidence_gate_result: Dict = None
    ) -> Dict[str, Any]:
        """Entry context — delegated to OpportunityEvaluator module."""
        return self._opportunity_evaluator.build_entry_context(
            alert, intelligence, regime, regime_score,
            filter_action, filter_win_rate, atr, atr_percent,
            confidence_gate_result=confidence_gate_result
        )

    @staticmethod
    def _classify_time_window(now_et) -> str:
        """Time window classification — delegated to OpportunityEvaluator module."""
        from services.opportunity_evaluator import OpportunityEvaluator
        return OpportunityEvaluator.classify_time_window(now_et)

    def _generate_explanation(self, alert: Dict, shares: int, entry: float, stop: float, targets: List[float], intelligence: Dict = None) -> TradeExplanation:
        """Explanation generation — delegated to OpportunityEvaluator module."""
        return self._opportunity_evaluator.generate_explanation(alert, shares, entry, stop, targets, intelligence, self)
    
    # ==================== TRADE EXECUTION ====================
    
    async def _execute_trade(self, trade: BotTrade):
        """Execute a trade — delegated to TradeExecution module, gated by the
        central safety guardrails (daily-loss / stale-quote / exposure caps).

        Safety check runs LAST before execution so it sees the final notional
        size chosen by the opportunity evaluator. Any failure → trade is
        skipped (not cancelled) and the reason is stream-logged so the UI's
        Unified Stream shows why the bot refused to take it.
        """
        try:
            from services.safety_guardrails import get_safety_guardrails
            guard = get_safety_guardrails()

            # ACCOUNT GUARD — block (and auto-trip) if the pusher's current
            # account doesn't match the authorized one (paper vs live). This
            # preserves the workflow of keeping a LIVE account configured
            # alongside PAPER while only authorizing one at a time via the
            # IB_ACCOUNT_ACTIVE env var.
            try:
                from services.account_guard import check_account_match
                # Prefer the pusher-reported account id (this is the same
                # source /api/ib/account/summary uses). Fall back to the
                # direct-connected IBService status only if pusher is offline.
                _current_acct = None
                try:
                    from routers.ib import get_pushed_account_id
                    _current_acct = get_pushed_account_id()
                except Exception:
                    _current_acct = None
                if not _current_acct:
                    try:
                        from services.ib_service import get_ib_service
                        _ib = get_ib_service()
                        _status = _ib.get_status() if _ib else {}
                        _current_acct = (_status or {}).get("account_id")
                    except Exception:
                        _current_acct = None
                _ok, _reason = check_account_match(_current_acct)
                if not _ok:
                    logger.critical(f"[ACCOUNT GUARD] {_reason} — tripping kill-switch")
                    try:
                        guard.trip_kill_switch(reason=f"Account guard: {_reason}")
                    except Exception:
                        pass
                    # Forensic breadcrumb so the operator's
                    # /api/diagnostic/trade-drops endpoint can pinpoint
                    # *this* gate as the silent killer (the April 16
                    # regression hid behind exactly this branch). Never
                    # raises — see trade_drop_recorder.record_trade_drop.
                    try:
                        from services.trade_drop_recorder import record_trade_drop
                        record_trade_drop(
                            getattr(self, "_db", None),
                            gate="account_guard",
                            symbol=getattr(trade, "symbol", None),
                            setup_type=getattr(trade, "setup_type", None),
                            direction=(
                                trade.direction.value
                                if hasattr(trade.direction, "value")
                                else str(getattr(trade, "direction", ""))
                            ),
                            reason=_reason,
                            context={
                                "current_account_id": _current_acct,
                                "ib_account_active_env": __import__("os").environ.get("IB_ACCOUNT_ACTIVE"),
                            },
                        )
                    except Exception:
                        pass
                    return {"success": False, "action": "SKIP",
                            "reason": f"Account guard blocked: {_reason}"}
            except Exception as _ag_err:
                logger.debug(f"[AccountGuard] check skipped: {_ag_err}")

            # Build the snapshot the guardrail needs.
            open_positions_snapshot: List[Dict[str, Any]] = []
            for t in self._open_trades.values():
                try:
                    open_positions_snapshot.append({
                        "symbol": getattr(t, "symbol", None),
                        "side": str(getattr(t, "direction", "")).lower(),
                        "notional_usd": float(getattr(t, "entry_price", 0) or 0) * float(getattr(t, "shares", 0) or 0),
                    })
                except Exception:
                    continue

            notional = float(trade.entry_price or 0) * float(trade.shares or 0)
            equity = float(self.risk_params.starting_capital or 100_000)
            last_quote_age = None
            try:
                from services.ib_push_data_store import get_last_quote_age_seconds
                last_quote_age = get_last_quote_age_seconds(trade.symbol)
            except Exception:
                pass  # quote-age helper is optional / absent in some deploys

            # Awaiting-quotes gate (P1 2026-04-22): if any open trade hasn't
            # received its first IB quote yet, `current_price` is 0 and the
            # unrealized PnL math produces garbage (e.g., -$1.2M phantom loss
            # on a just-loaded broker position). Treating that as real daily
            # P&L would instantly trip the kill-switch on startup. Skip the
            # live-unrealized input entirely until all positions have quotes.
            live_unrealized, awaiting_quotes = self._compute_live_unrealized_pnl()
            if awaiting_quotes:
                logger.info(
                    "[SAFETY] Awaiting-quotes gate active — excluding live "
                    "unrealized PnL from kill-switch math (positions without "
                    "first quote present)."
                )

            result = guard.check_can_enter(
                symbol=trade.symbol,
                side=str(trade.direction).lower(),
                notional_usd=notional,
                account_equity=equity,
                daily_realized_pnl=float(getattr(self._daily_stats, "net_pnl", 0) or 0),
                daily_unrealized_pnl=0.0 if awaiting_quotes else live_unrealized,
                open_positions=open_positions_snapshot,
                last_quote_age_seconds=last_quote_age,
            )
            if not result.allowed:
                logger.warning(
                    "[SAFETY] Trade blocked for %s (%s): %s",
                    trade.symbol, result.check, result.reason,
                )
                # Forensic breadcrumb — surface this drop in
                # /api/diagnostic/trade-drops alongside account_guard /
                # broker rejects so we can rank silent killers by gate.
                try:
                    from services.trade_drop_recorder import record_trade_drop
                    record_trade_drop(
                        getattr(self, "_db", None),
                        gate="safety_guardrail",
                        symbol=getattr(trade, "symbol", None),
                        setup_type=getattr(trade, "setup_type", None),
                        direction=str(trade.direction).lower(),
                        reason=f"{result.check}: {result.reason}",
                        context={
                            "check": result.check,
                            "notional_usd": float(notional),
                            "equity": float(equity),
                            "open_positions": len(open_positions_snapshot),
                            "last_quote_age_s": last_quote_age,
                            "awaiting_quotes": bool(awaiting_quotes),
                        },
                    )
                except Exception:
                    pass
                # Surface to the SentCom stream so operators see it in V5 UI
                try:
                    from services.sentcom_service import emit_stream_event
                    await emit_stream_event({
                        "kind": "skip",
                        "event": "safety_block",
                        "symbol": trade.symbol,
                        "text": f"Safety block ({result.check}): {result.reason}",
                    })
                except Exception:
                    pass
                return  # skip this trade — no cancel needed, it was never placed
        except Exception as e:
            # Fail-OPEN on guardrail import / plumbing error would be unsafe;
            # fail-CLOSED (skip the trade) so a buggy safety layer can't
            # accidentally allow uncontrolled exposure.
            #
            # 2026-04-30 v14: `logger.exception` so the traceback appears
            # in the log line itself. Lesson from the v13 `BotTrade.quantity`
            # regression — that bug was a one-line `AttributeError` here
            # that took 13 days to find because the prior `logger.error
            # ("[SAFETY] Guardrail check crashed; blocking trade: %s", e)`
            # hid the type + line number.
            logger.exception(
                "[SAFETY] Guardrail check crashed (%s): %s; blocking trade",
                type(e).__name__, e,
            )
            try:
                from services.trade_drop_recorder import record_trade_drop
                record_trade_drop(
                    getattr(self, "_db", None),
                    gate="safety_guardrail_crash",
                    symbol=getattr(trade, "symbol", None),
                    setup_type=getattr(trade, "setup_type", None),
                    direction=(
                        trade.direction.value if hasattr(trade.direction, "value")
                        else str(getattr(trade, "direction", ""))
                    ),
                    reason=f"guardrail check exception: {e}",
                    context={"exc_type": type(e).__name__},
                )
            except Exception:
                pass
            return

        await self._trade_execution.execute_trade(trade, self)
    
    async def confirm_trade(self, trade_id: str) -> bool:
        """Confirm a pending trade — delegated to TradeExecution module."""
        return await self._trade_execution.confirm_trade(trade_id, self)
    
    async def reject_trade(self, trade_id: str) -> bool:
        """Reject a pending trade — delegated to TradeExecution module."""
        return await self._trade_execution.reject_trade(trade_id, self)
    
    # ==================== POSITION MANAGEMENT ====================
    
    async def _update_open_positions(self):
        """Update open positions — delegated to PositionManager module."""
        await self._position_manager.update_open_positions(self)

    async def _check_eod_close(self):
        """EOD auto-close — delegated to PositionManager module."""
        await self._position_manager.check_eod_close(self)

    async def _update_trailing_stop(self, trade: BotTrade):
        """Delegates to StopManager module."""
        await self._stop_manager.update_trailing_stop(trade)

    def _move_stop_to_breakeven(self, trade: BotTrade):
        """Delegates to StopManager module."""
        self._stop_manager._move_stop_to_breakeven(trade)

    def _activate_trailing_stop(self, trade: BotTrade):
        """Delegates to StopManager module."""
        self._stop_manager._activate_trailing_stop(trade)

    def _update_trail_position(self, trade: BotTrade):
        """Delegates to StopManager module."""
        self._stop_manager._update_trail_position(trade)

    def _record_stop_adjustment(self, trade: BotTrade, old_stop: float, new_stop: float, reason: str):
        """Delegates to StopManager module."""
        self._stop_manager._record_stop_adjustment(trade, old_stop, new_stop, reason)


    async def _check_and_execute_scale_out(self, trade: BotTrade):
        """Scale-out check — delegated to PositionManager module."""
        await self._position_manager.check_and_execute_scale_out(trade, self)
    
    async def _execute_partial_exit(self, trade: BotTrade, shares: int, target_price: float, target_idx: int) -> Dict:
        """Partial exit — delegated to PositionManager module."""
        return await self._position_manager.execute_partial_exit(trade, shares, target_price, target_idx, self)

    
    async def close_trade(self, trade_id: str, reason: str = "manual") -> bool:
        """Close an open trade — delegated to PositionManager module."""
        return await self._position_manager.close_trade(trade_id, self, reason=reason)
    
    # ==================== DATA ACCESS ====================
    
    def get_status(self) -> Dict:
        """Get bot status summary"""
        return {
            "running": self._running,
            "mode": self._mode.value,
            "risk_params": {
                "max_risk_per_trade": self.risk_params.max_risk_per_trade,
                "max_daily_loss": self.risk_params.max_daily_loss,
                "starting_capital": self.risk_params.starting_capital,
                "max_position_pct": self.risk_params.max_position_pct,
                "max_open_positions": self.risk_params.max_open_positions,
                "min_risk_reward": self.risk_params.min_risk_reward,
                "max_notional_per_trade": self.risk_params.max_notional_per_trade,
                "setup_min_rr": dict(self.risk_params.setup_min_rr or {}),
                "reconciled_default_stop_pct": self.risk_params.reconciled_default_stop_pct,
                "reconciled_default_rr": self.risk_params.reconciled_default_rr,
            },
            "enabled_setups": self._enabled_setups,
            "strategy_configs": self.get_strategy_configs(),
            "pending_trades": len(self._pending_trades),
            "open_trades": len(self._open_trades),
            "daily_stats": asdict(self._daily_stats)
        }
    
    def get_pending_trades(self) -> List[Dict]:
        """Get all pending trades awaiting confirmation"""
        return [t.to_dict() for t in self._pending_trades.values()]
    
    def get_open_trades(self) -> List[Dict]:
        """Get all open positions"""
        return [t.to_dict() for t in self._open_trades.values()]
    
    def get_closed_trades(self, limit: int = 50) -> List[Dict]:
        """Get closed trades history"""
        return [t.to_dict() for t in self._closed_trades[-limit:]]
    
    def get_trade(self, trade_id: str) -> Optional[Dict]:
        """Get a specific trade by ID"""
        if trade_id in self._pending_trades:
            return self._pending_trades[trade_id].to_dict()
        if trade_id in self._open_trades:
            return self._open_trades[trade_id].to_dict()
        for trade in self._closed_trades:
            if trade.id == trade_id:
                return trade.to_dict()
        return None
    
    def get_daily_stats(self) -> Dict:
        """Get daily trading statistics"""
        return asdict(self._daily_stats)
    
    async def reconcile_positions_with_ib(self) -> Dict:
        """Reconcile bot positions with IB — delegated to PositionReconciler module."""
        return await self._position_reconciler.reconcile_positions_with_ib(self)
    
    async def sync_position_from_ib(self, symbol: str, auto_create_trade: bool = False) -> Dict:
        """Sync a single IB position — delegated to PositionReconciler module."""
        return await self._position_reconciler.sync_position_from_ib(symbol, self, auto_create_trade)
    
    async def close_phantom_position(self, trade_id: str, reason: str = "not_in_ib") -> Dict:
        """Close a phantom position — delegated to PositionReconciler module."""
        return await self._position_reconciler.close_phantom_position(trade_id, self, reason)
    
    async def full_position_sync(self) -> Dict:
        """Full IB position sync — delegated to PositionReconciler module."""
        return await self._position_reconciler.full_position_sync(self)
    
    async def reconcile_orphan_positions(
        self,
        symbols: Optional[List[str]] = None,
        all_orphans: bool = False,
        stop_pct: Optional[float] = None,
        rr: Optional[float] = None,
    ) -> Dict:
        """Proper reconcile for IB-only orphan positions — delegated to
        PositionReconciler. Materializes bot_trades + _open_trades so the
        manage loop can actively trail stops / scale out / EOD-close
        positions the bot didn't originate. See PositionReconciler.
        reconcile_orphan_positions for the full contract + safety guards.
        """
        return await self._position_reconciler.reconcile_orphan_positions(
            self,
            symbols=symbols,
            all_orphans=all_orphans,
            stop_pct=stop_pct,
            rr=rr,
        )
    
    # ==================== REGIME PERFORMANCE LOGGING ====================
    
    async def _log_trade_to_regime_performance(self, trade: BotTrade):
        """
        Log a closed trade to the regime performance tracking service.
        This allows analysis of strategy performance across different market regimes.
        """
        if self._regime_performance_service is None:
            logger.debug("Regime performance service not available - skipping trade logging")
            return
        
        try:
            # Build trade data for logging
            trade_data = {
                "trade_id": trade.id,
                "setup_type": trade.setup_type,
                "market_regime": trade.market_regime,
                "direction": trade.direction.value if hasattr(trade.direction, 'value') else trade.direction,
                "realized_pnl": trade.realized_pnl,
                "shares": trade.shares,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "regime_score": trade.regime_score,
                "regime_position_multiplier": trade.regime_position_multiplier,
                "risk_amount": trade.risk_amount,
                "closed_at": trade.closed_at
            }
            
            # Log to the regime performance service
            await self._regime_performance_service.log_trade(trade_data)
            
            logger.info(f"📊 Trade logged to regime performance: {trade.symbol} {trade.setup_type} "
                       f"in {trade.market_regime} regime, P&L: ${trade.realized_pnl:.2f}")
            
        except Exception as e:
            logger.error(f"Error logging trade to regime performance: {e}")
    
    # ==================== PERSISTENCE ====================
    
    async def _save_trade(self, trade: BotTrade):
        """Save trade to database — delegated to BotPersistence module."""
        await self._persistence.save_trade(trade, self)

    async def load_trades_from_db(self):
        """Load trades from database — delegated to BotPersistence module."""
        await self._persistence.load_trades_from_db(self)

    def _dict_to_trade(self, d: Dict) -> Optional[BotTrade]:
        """Convert dict to BotTrade — delegated to BotPersistence module."""
        return self._persistence.dict_to_trade(d)
    
    # ==================== SCANNER AUTO-EXECUTION ====================
    
    async def submit_trade_from_scanner(self, trade_request: Dict):
        """Scanner auto-submit — delegated to ScannerIntegration module."""
        return await self._scanner_integration.submit_trade_from_scanner(trade_request, self)

    async def _log_trade_to_journal(self, trade: BotTrade, action: str = "entry"):
        """Journal auto-logging — delegated to ScannerIntegration module."""
        await self._scanner_integration.log_trade_to_journal(trade, self, action)



# Singleton instance
_trading_bot_service: Optional[TradingBotService] = None


def get_trading_bot_service() -> TradingBotService:
    """Get or create the trading bot service singleton"""
    global _trading_bot_service
    if _trading_bot_service is None:
        _trading_bot_service = TradingBotService()
    return _trading_bot_service
