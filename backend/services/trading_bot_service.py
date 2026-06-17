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
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger(__name__)


# ── v19.34.285 — naked-sweep flip guard (direction-aware) ────────────────────
# The v235 protective-qty clamp (clamp_protective_qty + live_position_abs) only
# compares MAGNITUDES — it discards the SIGN of the live IB position. So when a
# tracked position desyncs overnight and IB ends up FLAT or on the OPPOSITE side
# (CRM overnight-naked-flip incident), the naked-sweep reissues a full-size EXIT
# (SELL for a long / BUY for a short) that, on trigger, oversells/overbuys past
# zero and creates a NAKED flipped position. This decides, per naked trade,
# whether reissuing the protective bracket is safe given the SIGNED live IB
# position. (A same-side partial — 0 < held < rs — still 'proceed's; the v235
# magnitude clamp inside attach_oca_stop_target shrinks the order correctly.)
def _naked_sweep_flip_decision(direction_value, bot_remaining_shares,
                               ib_signed_qty, positions_available):
    """Return 'skip_unverifiable' | 'halt_flat_or_opposite' | 'proceed'.

    - direction_value: 'long' | 'short' (the bot trade's side)
    - bot_remaining_shares: shares the bot thinks it holds (> 0)
    - ib_signed_qty: live IB net position for the symbol (signed; + long / -
      short), or None when the symbol is absent from an otherwise-present snapshot
    - positions_available: False when IB position data couldn't be read this cycle
    """
    if not positions_available:
        return "skip_unverifiable"
    is_long = str(direction_value or "long").lower() != "short"
    signed = 0.0 if ib_signed_qty is None else float(ib_signed_qty)
    same_side_qty = signed if is_long else -signed
    if same_side_qty <= 0:
        # IB is flat OR on the opposite side — any exit reissue would flip naked.
        return "halt_flat_or_opposite"
    return "proceed"


# ── M0c (2026-06-12) — ladder-aware naked detection helper ───────────────────
# An M0-laddered trade has N independent OCA pairs at IB; the trade's primary
# `stop_order_id` is only leg 1's stop. After leg 1's target fills, OCA cancels
# leg 1's stop — the legacy naked check (`stop_order_id not in live_order_ids`)
# then reads the trade as NAKED even though legs 2..n still protect every
# remaining share. This helper returns the stop ids of all still-working ladder
# legs so the sweep can check ANY of them against the live order snapshot.
def _m0_working_leg_stop_ids(trade) -> list:
    """Stop order ids (as str) of all still-working M0 ladder legs."""
    try:
        cfg = getattr(trade, "scale_out_config", None) or {}
        return [
            str(l["stop_order_id"]) for l in (cfg.get("m0_legs") or [])
            if l.get("status") == "working" and l.get("stop_order_id") is not None
        ]
    except Exception:
        return []


# ── M0d (2026-06-12) — ladder coverage audit helpers ─────────────────────────
# A partially-destroyed ladder (legs 2..n cancelled, leg 1 alive — the
# CZR/IGV/KRE 2026-06-11 incident) reads as fully protected under the binary
# naked check. These helpers measure ACTUAL covered quantity so the sweep can
# top-up the shortfall.
def _m0_coverage_scan(trade, live_order_ids) -> tuple:
    """Returns (covered_qty, live_stop_px, lost_count).

    covered_qty   — sum of qty across working legs whose stop is LIVE at IB
    live_stop_px  — stop price of a surviving leg (BE-moves included), or None
    lost_count    — legs that claimed 'working' but whose stop is gone; these
                    are MUTATED to status='lost' so no manager acts on dead ids
    """
    try:
        cfg = getattr(trade, "scale_out_config", None) or {}
        legs = cfg.get("m0_legs") or []
        covered = 0
        live_stop_px = None
        lost = 0
        for leg in legs:
            if not isinstance(leg, dict) or leg.get("status") != "working":
                continue
            sid = leg.get("stop_order_id")
            if sid is not None and str(sid) in live_order_ids:
                covered += int(leg.get("qty") or 0)
                if leg.get("stop_px") is not None:
                    live_stop_px = float(leg["stop_px"])
            else:
                leg["status"] = "lost"
                lost += 1
        return covered, live_stop_px, lost
    except Exception:
        return 0, None, 0


def _m0_furthest_lost_target(trade):
    """Furthest lost-leg target px in the trade direction (preserves the
    runner's upside on the top-up leg), or None → stop-only top-up."""
    try:
        cfg = getattr(trade, "scale_out_config", None) or {}
        tps = [float(l["target_px"]) for l in (cfg.get("m0_legs") or [])
               if isinstance(l, dict) and l.get("status") == "lost"
               and l.get("target_px")]
        if not tps:
            return None
        d = (getattr(trade.direction, "value", None) or str(trade.direction)).lower()
        return max(tps) if d == "long" else min(tps)
    except Exception:
        return None


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
    "fading_bounce": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "tidal_wave": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.4, 0.3, 0.3],
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
    # ──────────────────────────────────────────────────────────────────
    # v19.34.165 (2026-05-27) — Momentum-playbook setups newly surfaced
    # by v19.34.164 trade_drops persistence. Scanner had been emitting
    # 446 alerts/hour against these names but the bot was silently
    # dropping them at the setup_disabled gate. Parameters tuned per the
    # canonical playbook for each setup (O'Neil / Kacher / Weinstein /
    # Minervini); see CHANGELOG.md v165 entry for source citations.
    # ──────────────────────────────────────────────────────────────────
    "rs_leader_break": {
        # IBD/CAN SLIM relative-strength leader breakout. O'Neil 8-week
        # hold rule when stock gains 20%+ in first 3 weeks; trail under
        # 50-day MA otherwise. Same family as base_breakout but with
        # the RS-leader pre-filter.
        "timeframe": TradeTimeframe.POSITION,
        "trail_pct": 0.04,
        "scale_out_pcts": [0.2, 0.3, 0.5],   # partial at 8-10%, 20%, ride
        "close_at_eod": False,
    },
    "stage_2_breakout": {
        # Weinstein Stage-2 base breakout, weeks-to-months hold.
        # Trail under the rising 30-week MA; some traders use 1-1.5 ATR.
        "timeframe": TradeTimeframe.POSITION,
        "trail_pct": 0.04,
        "scale_out_pcts": [0.2, 0.3, 0.5],
        "close_at_eod": False,
    },
    "three_week_tight": {
        # Minervini TWT — break above 3-week compressed range on volume.
        # Hold while constructive; partial at 2R (~20-25% gain), ride
        # remainder with trailing stop. Slightly tighter trail than a
        # fresh base breakout because TWT is a continuation pattern
        # already partway into the move.
        "timeframe": TradeTimeframe.POSITION,
        "trail_pct": 0.035,
        "scale_out_pcts": [0.25, 0.25, 0.5],
        "close_at_eod": False,
    },
    "power_trend_stack": {
        # Minervini Power-Play / Stage-2 continuation with EMA stack
        # alignment. Faster mover than fresh-base breakouts so we run
        # the SWING tier (days to weeks). Stop below the last
        # contraction low; trail under 10-day MA.
        "timeframe": TradeTimeframe.SWING,
        "trail_pct": 0.03,
        "scale_out_pcts": [0.25, 0.25, 0.5],
        "close_at_eod": False,
    },
    "pocket_pivot": {
        # Kacher pocket pivot — early entry inside a constructive base
        # when up-volume exceeds the heaviest prior-10-day down-volume.
        # Days-to-weeks hold, exit if closes below 10-day MA. SWING tier.
        "timeframe": TradeTimeframe.SWING,
        "trail_pct": 0.025,
        "scale_out_pcts": [0.33, 0.33, 0.34],   # 1R/2R/3R style
        "close_at_eod": False,
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
    max_open_positions: int = 25             # Maximum concurrent positions (operator default; live value loaded from Mongo bot_state, capped by kill-switch SAFETY_MAX_POSITIONS)
    # ── v19.34.123 (Feb 2026) ───────────────────────────────────
    # When False (default), the opportunity_evaluator refuses any
    # new entry on a (symbol, direction) that already has an open
    # canonical — setup_type-agnostic. Kills the Feb 2026 RJF
    # runaway pattern (28 SHORT entries in 76 min via classifier
    # cycling 6+ setup_types to bypass per-setup cooldowns).
    # Operator can flip to True to re-enable additive scaling.
    allow_multiple_entries_per_symbol_dir: bool = False
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
        "fading_bounce":       1.5,
        "tidal_wave":          2.0,
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


def _compute_hold_seconds(entry_ts, close_ts) -> Optional[float]:
    """v19.34.274 — realized hold-duration label (seconds).

    Returns `closed_at − entry_ts` in seconds, where `entry_ts` is the
    fill time (executed_at) falling back to created_at. Returns None when
    either timestamp is missing/unparseable so OPEN trades stay None and
    bad rows never poison the meta-model feature. Robust to naive ISO
    strings (assumed UTC), trailing 'Z', and datetime objects.
    """
    def _parse(ts):
        if ts is None:
            return None
        if isinstance(ts, datetime):
            dt = ts
        else:
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    a = _parse(entry_ts)
    b = _parse(close_ts)
    if a is None or b is None:
        return None
    secs = (b - a).total_seconds()
    # Guard against clock-skew / bad data producing negatives.
    if secs < 0:
        return None
    return round(secs, 1)


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

    # ── v19.34.175 — TQS/SMB unification ─────────────────────────────
    # `unified_grade` is the single source of truth for this trade's
    # grade — it equals the Trade Quality Score grade (`tqs_grade`). The
    # `smb_grade` field above is retained for AUDIT ONLY and no longer
    # drives position sizing (it is already 15% of the TQS Setup pillar;
    # reusing it for sizing double-counted it). `tqs_score`/`tqs_grade`
    # mirror the TQS pipeline output captured at fill time.
    tqs_score: float = 0.0            # 0-100 overall Trade Quality Score
    tqs_grade: str = ""               # A / B+ / B / C+ / C / D / F
    unified_grade: str = ""           # canonical grade (= tqs_grade)
    
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
    # v322s — was `""`: any construction path that didn't set created_at
    # explicitly persisted an EMPTY STRING, hiding the row from every
    # date-windowed query and sorting it out of forensics (the ACMR
    # 65h-carry row was invisible to two autopsy probes because of this).
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())
    executed_at: Optional[str] = None
    closed_at: Optional[str] = None
    # v19.34.274 — realized hold-duration label (seconds), stamped at close
    # via to_dict for the future realized-outcome meta-model.
    hold_seconds: Optional[float] = None
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

    # v19.34.36 (2026-05-07) — Alert→Trade join key. Stamped from
    # `LiveAlert.id` at evaluator time so the learning loop's pending-
    # context store and `decision_trail.py`'s alert_id Mongo join can
    # both resolve. Pre-v19.34.36 this field didn't exist on BotTrade,
    # so:
    #   1) `learning_loop.record_trade_outcome` fell through to a fresh
    #      context capture at CLOSE time (wrong market regime).
    #   2) `decision_trail` queries by `alert_id` returned empty for
    #      every trade (no rows ever had the field).
    # Now threaded all the way through scanner → bot → evaluator → trade.
    alert_id: Optional[str] = None

    # ── v19.34.163 — Bracket churn telemetry + cooldown fields ───────────
    # Cumulative, monotonic; cleanup paths MUST NOT reset these. Drive
    # the v90 P0 bracket-churn audit and `bracket_completion_telemetry`
    # alert job (P3 backlog).
    #   target_ever_attached     True after the FIRST successful TP attach.
    #                            Lets `pnl-by-style` distinguish "TP never
    #                            placed" (the actual bug) from "TP placed
    #                            but didn't hit". Never resets.
    #   bracket_attach_count     Increments on every successful naked-
    #                            sweep reissue (and any other successful
    #                            attach path that calls _stamp_bracket_attach).
    #                            Used by ops dashboards + churn audit.
    #   last_bracket_attach_at   ISO-UTC timestamp of the most recent
    #                            successful attach. Read by Guard 2 in
    #                            `_naked_position_sweep` to suppress
    #                            re-detection within NAKED_REISSUE_COOLDOWN_S
    #                            (default 90s) — covers IB async-callback
    #                            latency before the new STP shows up in
    #                            pusher/ib_direct snapshots.
    target_ever_attached: bool = False
    bracket_attach_count: int = 0
    last_bracket_attach_at: Optional[str] = None

    def __post_init__(self):
        """v19.34.57 — Audit-gap closer: stamp `trade_type` at construction.

        Pre-v19.34.57, `trade_type` was only stamped inside the fill block
        of `services/trade_execution.py` (~lines 790-835). That meant any
        trade that never reached fill — REJECTED by the bot's pre-trade
        gates, VETOED by risk guards, or aborted before broker submission —
        was persisted with `trade_type='unknown'`. Audit revealed 227 such
        rows, polluting paper/live attribution and live-readiness gating.
        The fill-time block stays canonical (it reads the *actual* IB
        account_id from the pusher snapshot — the truth for filled rows).
        This `__post_init__` only fixes the construction-time default so
        rejected/vetoed trades inherit the operator\'s configured intent
        from `IB_ACCOUNT_ACTIVE`. On any import or env-load failure it
        leaves the field as the dataclass default ("unknown") — never
        worse than the legacy behavior.
        """
        if self.trade_type == "unknown":
            try:
                from services.account_guard import load_account_expectation
                self.trade_type = load_account_expectation().active_mode
            except Exception:
                # Stay on the dataclass default — preserves legacy behavior.
                self.trade_type = "unknown"

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
        # v19.34.87 — Runtime-attached bracket fields. `target_order_id`
        # (singular) and `oca_group` are NOT dataclass fields — they
        # get attached at runtime by attach_oca_stop_target and
        # bracket_reissue_service. asdict() doesn't see them, so
        # pre-v87 every persist wiped both fields, meaning every
        # restart left `target_order_id=None` on trades that had a
        # live target at IB. That made the v83 stop_present_no_target
        # skip fire on legitimately-bracketed trades, which on
        # 2026-05-12 caused 8 new OCA pairs to get stacked on top
        # of existing live brackets at IB. Explicitly serialize them
        # now so the restore path can hydrate them back.
        if hasattr(self, "target_order_id"):
            d['target_order_id'] = getattr(self, "target_order_id", None)
        if hasattr(self, "oca_group"):
            d['oca_group'] = getattr(self, "oca_group", None)
        # Also surface adoption / external-close timestamps used by
        # the reconciler's filtering logic (set by reconciler /
        # consolidator paths at runtime).
        for _runtime_field in (
            "adopted_from_orphan_at", "external_close_first_seen_at",
            "external_close_confirmed_at", "remaining_shares_after_external_close",
        ):
            if hasattr(self, _runtime_field):
                d[_runtime_field] = getattr(self, _runtime_field, None)
        # v19.34.274 — hold_seconds: realized trade duration (seconds).
        # Computed centrally here so EVERY close path (operator-flatten,
        # EOD-close, stop, scale-out final, reconciler) persists it for
        # free via save_trade → to_dict. None while the trade is open.
        d['hold_seconds'] = _compute_hold_seconds(
            self.executed_at or self.created_at,
            self.closed_at,
        )
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


def _reaper_should_skip_filled(symbol: str, ib_pos_syms: set, bot_open_syms: set) -> bool:
    """v19.34.234 — Reaper safety guard.

    Return True when a stale `pending` row must NOT be reaped because its
    symbol still shows a LIVE IB position that the bot is not tracking as an
    open trade. That combination almost always means the pre-submitted order
    DID fill at IB but the fill was never attributed back to the bot (the
    `entry_order_id=None` race seen 2026-06-03 on SOXX/LRCX/ALAB/ASTS): the
    blind reaper would falsely record the real fill as `rejected` and let the
    live shares become an orphan that the consolidator then over-sizes.

    Blast radius is intentionally tiny: at worst this leaves a benign
    `pending` DB row in place (it places no orders). It can never close a
    position or submit an order.
    """
    s = (symbol or "").upper()
    return bool(s) and s in ib_pos_syms and s not in bot_open_syms


def _reaper_order_still_working(
    entry_order_id, symbol: str, live_orders_by_id: dict, live_order_syms: set
) -> bool:
    """v19.34.300 — True when a stale pending still has a WORKING order at IB
    that must be cancelled before the record can be safely reaped.

    Matches by IB orderId first (authoritative); falls back to a symbol match
    so an `entry_order_id=None` race still trips the guard rather than letting
    a working order be abandoned. Pure / no I/O so it's unit-testable.
    """
    try:
        oid = int(entry_order_id) if entry_order_id not in (None, "", 0, "0") else 0
    except (TypeError, ValueError):
        oid = 0
    s = (symbol or "").upper()
    return bool(oid and oid in (live_orders_by_id or {})) or bool(s and s in (live_order_syms or set()))



class TradingBotService:
    """
    Main trading bot service that orchestrates scanning, evaluation,
    execution, and position management.
    """
    
    def __init__(self):
        self._mode = BotMode.AUTONOMOUS  # Start in autonomous mode for auto-trading
        self._running = False
        self._scan_task: Optional[asyncio.Task] = None

        # v19.34.25 — Patches G/H/I (post-2026-02-bot-stampede-disaster).
        # These three timestamps + flag coordinate the startup-gate trio:
        #   • _started_at — moment start() fires; STARTUP_GRACE_SECONDS
        #     (default 60s) of cool-down blocks new entries even though
        #     the scan loop is alive. Lets pre-market staged signals
        #     stale-expire instead of cascading into a stampede at the
        #     instant the operator flips the kill switch.
        #   • _patch_f_audit_complete — set True once the v19.34.24
        #     orphan-GTC tripwire has actually run. Pre-G the audit had
        #     a 25s asyncio.sleep before its first audit while the
        #     scan loop began firing at t+1s, so the bot raced past
        #     its own protection.
        #   • _patch_f_audit_started_at — used to detect tripwire
        #     wedge and force-clear after N seconds of stuck "running".
        self._started_at: Optional[datetime] = None
        self._patch_f_audit_complete: bool = False
        self._patch_f_audit_started_at: Optional[datetime] = None

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
            "rubber_band", "rubber_band_scalp", "vwap_bounce", "vwap_fade", "fading_bounce", "tidal_wave",
            # Consolidation
            "big_dog", "puppy_dog", "nine_ema_scalp", "abc_scalp", "9_ema_scalp",
            # Afternoon
            "hod_breakout", "time_of_day_fade",
            # Special
            "breaking_news", "volume_capitulation", "range_break", "breakout",
            # New strategies
            "squeeze", "relative_strength", "relative_strength_leader", "relative_strength_laggard",
            "gap_fade", "chart_pattern",  # mean_reversion suppressed v19.34.327 (97% vwap_fade duplicate, v345)
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
            # ─────────────────────────────────────────────────────────
            # v19.34.165 (2026-05-27) — 5 momentum-playbook setups the
            # scanner had been emitting (446 alerts/hr observed via v164
            # trade_drops persistence) but the bot was silently rejecting
            # at the setup_disabled gate. Entries also added to
            # STRATEGY_CONFIG above so they don't fall to DEFAULT.
            # ─────────────────────────────────────────────────────────
            "rs_leader_break",       # IBD/CAN SLIM RS leader breakout
            "power_trend_stack",     # Minervini Power-Play continuation
            "pocket_pivot",          # Kacher pocket pivot
            "stage_2_breakout",      # Weinstein Stage-2 base breakout
            "three_week_tight",      # Minervini 3-week-tight continuation
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
        # v19.34.154 — EOD close window shifted 3:55 ET → 3:45 ET to beat
        # IBKR's Reg-T SMA calculation at 3:50 ET. Per operator's IBKR
        # research (2026-02-XX session): IBKR switches from intraday-
        # margin to overnight-Reg-T at 3:50 ET and starts force-
        # liquidating any account in deficit between 3:50-4:00 ET. The
        # bot's 3:55 close was fighting that auto-liquidator, generating
        # the 180×/min Error-201 cancel storms operator observed. Closing
        # intraday/scalp positions at 3:45 ET (the Soft Edge Margin
        # cutoff) gives IB headroom for its own 3:50 calc and eliminates
        # the storm. Swing/position trades (`close_at_eod=False`) are
        # untouched — they're explicitly held overnight.
        self._eod_close_hour = 15  # 3 PM ET
        self._eod_close_minute = 45  # 3:45 PM ET (was 55 — pre-v19.34.154)
        self._eod_close_executed_today = False
        # ── v19.34.113 — EOD setup grading ──────────────────────────
        # Fires 15 min after the EOD close (16:10 ET) so every scalp/
        # intraday close has had time to flush through bot_trades. The
        # grading service is read-mostly; this tick just upserts the
        # per-(setup_type, trading_date) snapshot rows. Idempotent — a
        # crash-and-recover during the grading window re-runs cleanly.
        self._eod_grading_hour = 16
        self._eod_grading_minute = 10
        self._eod_grading_executed_today_key: Optional[str] = None  # YYYY-MM-DD of last successful run
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

    async def _broadcast_event(self, payload: dict) -> None:
        """v19.34.191 — legacy shim restoring EOD/orphan HUD events.

        The original `_broadcast_event` was dropped during the
        unified-stream migration, leaving ~9 EOD/orphan-sweep call
        sites raising AttributeError (swallowed → HUD banners dead).
        Maps the legacy ``{"type": ..., "timestamp": ..., **extra}``
        payloads onto `emit_stream_event` so Mission Control HUD
        notifications fire again. Never raises into the caller.
        """
        try:
            from services.sentcom_service import emit_stream_event
            if not isinstance(payload, dict):
                return
            etype = str(payload.get("type") or payload.get("event") or "event")
            sev = str(payload.get("severity") or "").upper()
            kind = "alert" if (
                sev in ("CRITICAL", "ALARM", "WARN", "WARNING")
                or "alarm" in etype or "blocked" in etype
            ) else "system"
            text = payload.get("text") or payload.get("content")
            if not text:
                label = etype.replace("_", " ").title()
                bits = []
                for _k in (
                    "open_positions", "positions_to_close", "closed",
                    "failed", "escalated", "queued", "errors",
                    "ghosts_found", "total_pnl",
                ):
                    _v = payload.get(_k)
                    if _v not in (None, "", [], {}):
                        bits.append(f"{_k.replace('_', ' ')}={_v}")
                text = f"⏱ {label}" + (f" · {', '.join(bits)}" if bits else "")
            meta = {
                _mk: _mv for _mk, _mv in payload.items()
                if _mk not in ("type", "event", "text", "content", "kind")
            }
            await emit_stream_event({
                "kind": kind,
                "event": etype,
                "text": text,
                "metadata": meta,
            })
        except Exception as _e:
            logger.debug(f"_broadcast_event shim failed: {_e}")
    
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

        # ── v19.34.164 — Persist to MongoDB `trade_drops` collection ──
        # Operator-discovered May 2026: ~90% of trade rejections were
        # invisible to the Diagnostics tab because `record_rejection`
        # only wrote to an in-memory UI stream. `9_ema_scalp` alerts
        # (251 in 30d) emitted by the scanner were vanishing entirely.
        #
        # `record_trade_drop` is fire-and-forget (best-effort Mongo
        # write + in-memory ring buffer fallback). The 120s dedup
        # window above means duplicate (symbol, setup_type, reason_code)
        # rejections within ~2min are suppressed before we even reach
        # this point, so the DB write inherits the same dedup for free.
        try:
            from services.trade_drop_recorder import record_trade_drop
            _ctx_for_drop: Dict[str, Any] = {"narrative": narrative[:300]}
            if isinstance(ctx, dict):
                for _k, _v in ctx.items():
                    try:
                        # Truncate over-long string values to keep
                        # the doc small (Mongo 16MB cap is generous
                        # but per-doc bloat slows the audit endpoint).
                        if isinstance(_v, str) and len(_v) > 500:
                            _ctx_for_drop[_k] = _v[:500]
                        else:
                            _ctx_for_drop[_k] = _v
                    except Exception:
                        pass
            record_trade_drop(
                getattr(self, "_db", None),
                gate=reason_code,
                symbol=symbol,
                setup_type=setup_type,
                direction=direction,
                reason=narrative[:500],
                context=_ctx_for_drop,
            )
        except Exception as exc:
            logger.debug(f"record_rejection: trade_drops persist failed: {exc}")

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
        if reason_code == "symbol_exposure_saturated":
            # v19.34.70 — Operator-visible cooldown breadcrumb so the
            # Bot's Brain panel shows WHY the bot stopped re-evaluating
            # the symbol (instead of looking silent and broken).
            existing = ctx.get("existing_sym_exposure_usd", 0) or 0
            cap = ctx.get("safety_cap_usd", 0) or 0
            return (
                f"🧊 Cooling off on {symbol} {setup_display} — per-symbol "
                f"exposure ${existing:,.0f} hit the ${cap:,.0f} cap. "
                f"Skipping further entries on this setup until exposure "
                f"clears or the 5-min cooldown expires (prevents "
                f"death-by-a-thousand-cuts fragmentation)."
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
        if reason_code == "stale_alert_ttl":
            age_secs = ctx.get("alert_age_seconds")
            ttl_secs = ctx.get("ttl_seconds")
            age_phrase = f" ({age_secs:.0f}s old, TTL {int(ttl_secs)}s)" if (
                age_secs is not None and ttl_secs is not None
            ) else ""
            return (
                f"🕒 Passing on {symbol} {setup_display} — this alert sat "
                f"in the pipeline too long{age_phrase}. By now the trigger "
                f"price has moved and the setup is no longer the one the "
                f"scanner detected. Killing it here saves a round-trip to "
                f"IB and a near-certain bad fill."
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

        # v19.34.180 — persist MONGO_WINS fields SYNCHRONOUSLY.
        # The async create_task(_save_state()) below races the
        # state_integrity watchdog, which treats these fields as
        # MONGO_WINS and reverts the in-memory value back to the stale
        # Mongo snapshot BEFORE the deferred save lands — so the
        # operator's PUT /risk-params silently doesn't stick (observed
        # 2026-05-29: max_open_positions=25 reverted to 10). Writing the
        # changed MONGO_WINS fields straight to bot_state here makes the
        # endpoint authoritative for them. Sync pymongo is fine: this
        # method is called from a sync FastAPI route (threadpool), not
        # the event loop.
        try:
            from services.state_integrity_service import MONGO_WINS_FIELDS
            mongo_now = {
                f"risk_params.{k}": getattr(self.risk_params, k)
                for k in kwargs
                if k in MONGO_WINS_FIELDS and hasattr(self.risk_params, k)
            }
            if mongo_now and getattr(self, "_db", None) is not None:
                self._db.bot_state.update_one(
                    {"_id": "bot_state"}, {"$set": mongo_now}, upsert=True
                )
                logger.info(
                    f"v19.34.180 synced MONGO_WINS risk fields to Mongo: "
                    f"{list(mongo_now.keys())}"
                )
        except Exception as _mw_err:
            logger.warning(
                f"v19.34.180 sync persist of MONGO_WINS risk fields failed: {_mw_err}"
            )

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
    
    def _disabled_setups(self) -> set:
        """v19.34.244 — setup_types the bot must NOT trade even if their base is
        enabled. Confirmed money-losing variants live here. Operator-overridable
        via the DISABLED_SETUPS env (comma-separated setup_types). Default blocks
        `vwap_fade_short` (8% win, -4.26R, -$22k/120d). The scanner still emits
        these for monitoring; only TRADING is suppressed."""
        import os
        from services.entry_gate import parse_disabled_setups
        return parse_disabled_setups(os.environ.get("DISABLED_SETUPS"))

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
        # v19.34.25 Patch H — stamp startup time so _execute_trade can
        # enforce STARTUP_GRACE_SECONDS before firing any new entries.
        # Also reset Patch F audit flag so a fresh start() correctly
        # gates the first audit cycle.
        self._started_at = datetime.now(timezone.utc)
        self._patch_f_audit_complete = False
        self._patch_f_audit_started_at = None
        self._mode = BotMode.AUTONOMOUS if self._mode == BotMode.PAUSED else self._mode
        self._scan_task = asyncio.create_task(self._scan_loop())
        # v19.34.123 — Continuous real-time kill-switch monitor.
        # Reads realized PnL directly from `bot_trades` (post-v123 with
        # full PnL coverage on every close path) PLUS live unrealized
        # PnL from `_open_trades`. Runs every 15s independent of the
        # scan loop so the daily-loss cap fires REGARDLESS of whether
        # the bot is actively trying to enter trades.
        #
        # Pre-v123 the only daily-loss check ran inside `_scan_loop`
        # against `_daily_stats.net_pnl` — when the scanner paused (or
        # was rate-limited), the cap was effectively defeated. Feb 2026
        # operator lost $25k while the $5k cap "passed" because the
        # check never ran on the actual broker PnL.
        self._kill_switch_task = asyncio.create_task(
            self._kill_switch_monitor_loop()
        )
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

            # ── v19.34.73 (2026-05-21) — Boot phantom-sibling purge ──
            # The 2026-05-21 ADI incident: trade `b415ed5f` (44sh,
            # orphan-adopted from a prior session) co-existed in
            # `_open_trades` with the real bot_fired `82f0686f` (134sh).
            # Both matched (ADI, long) so the sym-dir-cap guard latched
            # onto the older `b415ed5f` as canonical and refused all
            # new ADI entries; meanwhile the naked-sweep reissued
            # brackets for BOTH every 60s, with `b415ed5f`'s submissions
            # bouncing off IB with Error 200 (stale contract / no
            # secdef) 35+ times.
            #
            # This pass purges the LOSER sibling for any (symbol,
            # direction) bucket that has >1 trade in `_open_trades`.
            # "Loser" = lower score per the same `_score_sibling`
            # function used by `_naked_position_sweep` (bot_fired beats
            # orphan-adopted; ties broken by remaining_shares).
            # The purged trade is moved to `_closed_trades` with
            # `close_reason="phantom_sibling_purge_v19_34_73"` and a
            # synthetic 0-share close (no PnL impact).
            async def _startup_phantom_sibling_purge():
                try:
                    await asyncio.sleep(20)  # let restore_state + orphan-guard settle
                    from services.trading_bot_service import TradeStatus
                    _sib_map: Dict[tuple, list] = {}
                    for _tid, _t in self._open_trades.items():
                        _ss = (getattr(_t, "symbol", "") or "").upper()
                        _sd = getattr(_t, "direction", None)
                        _sdv = getattr(_sd, "value", str(_sd) if _sd else "long").lower()
                        _sib_map.setdefault((_ss, _sdv), []).append(_tid)

                    def _score(_t) -> int:
                        _eb = (getattr(_t, "entered_by", "") or "").lower()
                        _bonus = 10000 if "bot_fired" in _eb else 0
                        _rs = int(abs(getattr(_t, "remaining_shares", 0) or 0))
                        return _bonus + _rs

                    purged = []
                    for (_sym, _dir), _tids in _sib_map.items():
                        if len(_tids) <= 1:
                            continue
                        _scored = sorted(
                            (
                                (_score(self._open_trades[_tid]), _tid)
                                for _tid in _tids
                                if _tid in self._open_trades
                            ),
                            reverse=True,
                        )
                        _winner = _scored[0][1] if _scored else None
                        for _, _loser_tid in _scored[1:]:
                            _loser = self._open_trades.get(_loser_tid)
                            if _loser is None:
                                continue
                            try:
                                _loser.status = TradeStatus.CLOSED
                                _loser.close_reason = "phantom_sibling_purge_v19_34_73"
                                _loser.closed_at = datetime.now(timezone.utc).isoformat()
                                _loser.remaining_shares = 0
                                del self._open_trades[_loser_tid]
                                self._closed_trades.append(_loser)
                                try:
                                    await self._save_trade(_loser)
                                except Exception as _se:
                                    logger.debug(
                                        f"[v19.34.73 phantom-purge] save failed for "
                                        f"{_loser_tid} (non-fatal): {_se}"
                                    )
                                purged.append({
                                    "purged_trade_id": _loser_tid,
                                    "symbol": _sym,
                                    "direction": _dir,
                                    "kept_canonical": _winner,
                                })
                                logger.warning(
                                    f"🧹 [v19.34.73 phantom-purge] Removed {_sym} "
                                    f"{_dir} phantom {_loser_tid} from _open_trades "
                                    f"— canonical {_winner} owns the position."
                                )
                            except Exception as _pe:
                                logger.warning(
                                    f"[v19.34.73 phantom-purge] could not purge "
                                    f"{_loser_tid} (non-fatal): {_pe}"
                                )
                    if purged:
                        logger.warning(
                            f"🧹 [v19.34.73 phantom-purge] Boot purge complete: "
                            f"removed {len(purged)} phantom sibling(s). Details: {purged}"
                        )
                    else:
                        logger.info(
                            "[v19.34.73 phantom-purge] No sibling-phantoms found at boot."
                        )
                except Exception as e:
                    logger.warning(
                        f"[v19.34.73 phantom-purge] boot pass failed (non-fatal): {e}"
                    )
            asyncio.create_task(_startup_phantom_sibling_purge())

            # ── v19.34.66 (2026-02-09) — Boot-time orphan-GTC tripwire ──
            # Long-missing audit pass. Every prior reconciler starts from
            # the bot's view of the world; none ever asked "what does IB
            # still have that the bot has forgotten about?". The 5/4 GTC
            # bracket-leg orphan event (10 protective sells aging at IB
            # for 5 days) was the canary.
            #
            # Fires ONCE at boot (after pusher has had ~25s to publish a
            # fresh position snapshot) AND every 30s thereafter via the
            # periodic loop below.
            #
            # ── v19.34.24 / "Patch F" (Feb-2026) — Boot-time IB zombie flush ──
            # The 2026-02 market-open zombie disaster: backend was
            # restarted overnight with fresh patches A/B/C/E applied,
            # but old DAY orders from the buggy session before the
            # restart were still alive at IB. At 9:30:00 ET those
            # zombie orders triggered, creating a -$482K SHLD short
            # and other massive unauthorised positions before the
            # operator could intervene.
            #
            # Pre-F: this boot tripwire (a) only audited GTC orders
            # (`only_gtc=True` by default — DAY zombies invisible),
            # and (b) only LOGGED. Even after v19.34.89 enabled
            # auto-sweep, the cancel didn't fire until the periodic
            # loop's 60s warm-up + 30s tick = up to 90s after boot.
            # At market-open that window is the entire disaster.
            #
            # Patch F changes:
            #   1. Audit ALL TIFs (`only_gtc=False`) so DAY zombies
            #      are caught.
            #   2. Immediately auto-cancel SAFE verdicts
            #      (NAKED_NO_POSITION, ORPHAN_NO_TRADE) right here at
            #      boot, before the bot enters its scan loop and
            #      before the periodic loop kicks in.
            #   3. Gated by `PATCH_F_AUTO_FLUSH_ON_BOOT` env var
            #      (default ENABLED). Set to "false" only when
            #      investigating a specific zombie set you want to
            #      inspect manually first.
            async def _startup_orphan_gtc_audit():
                # v19.34.25 Patch G — flag the audit as STARTED before
                # anything else. _execute_trade can use this to
                # distinguish "audit will eventually run" (allow normal
                # waiting behaviour) from "audit never even started"
                # (something is wrong, hard-block the bot).
                self._patch_f_audit_started_at = datetime.now(timezone.utc)
                try:
                    # v19.34.25 — shrunk from 25s → configurable (default
                    # 10s, env: PATCH_F_AUDIT_SLEEP_SECONDS). The
                    # _execute_trade gate now blocks entries until the
                    # audit completes, so the sleep no longer needs to
                    # be the operator's primary safety margin.
                    import os as _os_sleep
                    _audit_sleep = float(
                        _os_sleep.environ.get(
                            "PATCH_F_AUDIT_SLEEP_SECONDS", "10",
                        )
                    )
                    await asyncio.sleep(_audit_sleep)
                    from services.orphan_gtc_reconciler import (
                        VERDICT_NAKED_NO_POSITION,
                        VERDICT_ORPHAN_NO_TRADE,
                        VERDICT_MISMATCHED_SIZE,
                        SAFE_TO_AUTO_CANCEL,
                        OrderVerdict,
                        audit_orphan_gtc_orders,
                        cancel_orphan_gtc_orders,
                    )
                    # Patch F: include DAY orders. DAY zombies left over
                    # from a pre-restart session are the exact failure
                    # mode this guards against.
                    audit = await audit_orphan_gtc_orders(
                        bot=self, only_gtc=False,
                    )
                    if not audit.get("success"):
                        logger.warning(
                            "[v19.34.66 ORPHAN-GTC BOOT] audit could not run "
                            "at boot (reason=%s) — will retry in periodic loop",
                            audit.get("reason"),
                        )
                        return
                    summary = audit.get("summary", {})
                    n_naked = summary.get(VERDICT_NAKED_NO_POSITION, 0)
                    n_orphan = summary.get(VERDICT_ORPHAN_NO_TRADE, 0)
                    n_mismatch = summary.get(VERDICT_MISMATCHED_SIZE, 0)
                    if n_naked or n_orphan or n_mismatch:
                        logger.error(
                            "[v19.34.66 ORPHAN-GTC BOOT] FOUND naked=%d "
                            "orphan=%d mismatch=%d at IB. Use GET "
                            "/api/safety/orphan-gtc-orders for the full "
                            "verdict table; the V5 HUD pill should be RED.",
                            n_naked, n_orphan, n_mismatch,
                        )
                        for v in audit.get("verdicts", []):
                            if v.get("verdict") == "tracked":
                                continue
                            logger.error(
                                "[v19.34.66 ORPHAN-GTC BOOT] %s ib_order_id=%s "
                                "%s %s qty=%s tif=%s status=%s verdict=%s "
                                "ib_pos=%s reasons=%s",
                                v.get("symbol"), v.get("ib_order_id"),
                                v.get("action"), v.get("order_type"),
                                v.get("quantity"), v.get("time_in_force"),
                                v.get("status"), v.get("verdict"),
                                v.get("ib_position_size"),
                                v.get("reasons"),
                            )

                        # Patch F: immediate auto-flush of SAFE
                        # verdicts. Gated by env var so the operator
                        # can disable for investigation runs.
                        import os as _os
                        flush_enabled = _os.environ.get(
                            "PATCH_F_AUTO_FLUSH_ON_BOOT", "true",
                        ).strip().lower() in ("1", "true", "yes", "on")
                        if not flush_enabled:
                            logger.warning(
                                "[v19.34.24 PATCH-F BOOT] auto-flush "
                                "DISABLED via PATCH_F_AUTO_FLUSH_ON_BOOT — "
                                "leaving %d safe zombies in place for "
                                "manual review", n_naked + n_orphan,
                            )
                            return

                        # Rehydrate raw verdict dicts → OrderVerdict
                        # objects, filtering to safe set only.
                        safe_to_cancel = []
                        for raw in audit.get("verdicts") or []:
                            if not isinstance(raw, dict):
                                continue
                            if raw.get("verdict") not in SAFE_TO_AUTO_CANCEL:
                                continue
                            try:
                                safe_to_cancel.append(OrderVerdict(
                                    ib_order_id=int(raw.get("ib_order_id") or 0),
                                    perm_id=raw.get("perm_id"),
                                    symbol=raw.get("symbol") or "",
                                    action=raw.get("action") or "",
                                    quantity=int(raw.get("quantity") or 0),
                                    order_type=raw.get("order_type") or "",
                                    limit_price=raw.get("limit_price"),
                                    stop_price=raw.get("stop_price"),
                                    time_in_force=raw.get("time_in_force") or "",
                                    status=raw.get("status") or "",
                                    verdict=raw.get("verdict") or "",
                                    reasons=list(raw.get("reasons") or []),
                                    bot_trade_id=raw.get("bot_trade_id"),
                                    ib_position_size=raw.get("ib_position_size"),
                                    submitted_at=raw.get("submitted_at"),
                                ))
                            except (TypeError, ValueError) as _rehyd_exc:
                                logger.warning(
                                    "[v19.34.24 PATCH-F BOOT] could not "
                                    "rehydrate verdict %s: %s",
                                    raw, _rehyd_exc,
                                )
                        if not safe_to_cancel:
                            logger.warning(
                                "[v19.34.24 PATCH-F BOOT] %d dangerous "
                                "verdicts but none in SAFE_TO_AUTO_CANCEL "
                                "set — leaving for operator review",
                                n_naked + n_orphan + n_mismatch,
                            )
                            return
                        logger.warning(
                            "[v19.34.24 PATCH-F BOOT] auto-flushing %d "
                            "zombie order(s) at IB before bot enters "
                            "scan loop", len(safe_to_cancel),
                        )
                        cancel_report = await cancel_orphan_gtc_orders(
                            verdicts_to_cancel=safe_to_cancel,
                        )
                        n_cancelled = len(cancel_report.get("cancelled") or [])
                        n_errors = len(cancel_report.get("errors") or [])
                        logger.warning(
                            "[v19.34.24 PATCH-F BOOT] flush complete — "
                            "cancelled=%d errors=%d (full report in "
                            "share_drift_events)",
                            n_cancelled, n_errors,
                        )
                        # Audit-trail write so the operator can grep
                        # the boot flush after the fact.
                        try:
                            db = getattr(self, "_db", None)
                            if db is None:
                                from database import get_database
                                db = get_database()
                            if db is not None:
                                db["share_drift_events"].insert_one({
                                    "event_type": "patch_f_boot_zombie_flush_v19_34_24",
                                    "started_at": cancel_report.get("started_at"),
                                    "completed_at": cancel_report.get("completed_at"),
                                    "requested": cancel_report.get("requested"),
                                    "cancelled": cancel_report.get("cancelled"),
                                    "errors": cancel_report.get("errors"),
                                    "audit_summary": summary,
                                })
                        except Exception as _audit_exc:
                            logger.debug(
                                "[v19.34.24 PATCH-F BOOT] audit write "
                                "skipped: %s", _audit_exc,
                            )
                    else:
                        logger.info(
                            "[v19.34.66 ORPHAN-GTC BOOT] clean — "
                            "tracked=%d, no orphans/naked/mismatched",
                            summary.get("tracked", 0),
                        )
                except Exception as e:
                    logger.warning(
                        "[v19.34.66 ORPHAN-GTC BOOT] tripwire crashed "
                        "(non-fatal): %s", e,
                    )
                finally:
                    # v19.34.25 Patch G — ALWAYS mark complete, even on
                    # crash/timeout/early-return. The _execute_trade
                    # gate is "audit has run at least once"; we don't
                    # want a tripwire bug to brick all entries forever.
                    # If the audit failed, the periodic reconciler will
                    # retry every 30s — that's the real safety net.
                    self._patch_f_audit_complete = True
                    logger.info(
                        "[v19.34.25 PATCH-G GATE] Patch F audit done "
                        "— _execute_trade gate is now open"
                    )
            asyncio.create_task(_startup_orphan_gtc_audit())

            # ── v19.34.66 — Periodic background reconciler ──
            # v19.34.89 (2026-05-11) — now actually AUTO-CANCELS the
            # safe verdicts (NAKED_NO_POSITION, ORPHAN_NO_TRADE) instead
            # of merely logging. Gate via `AUTO_SWEEP_ORPHAN_GTC` env
            # var (default: enabled). Cancels are routed through the
            # v19.34.88 cancel queue → Windows pusher → IB.
            #
            # Interval dropped from 120s → 30s so the gap between
            # "target fills, stop becomes naked" and "stop cancelled at
            # IB" shrinks to ≤30s. Cheap: 1 IB orders read + 1 position
            # snapshot read + 1 Mongo find.
            async def _periodic_orphan_gtc_audit():
                # Initial offset so this doesn't dogpile with the boot
                # tripwire above.
                await asyncio.sleep(60)
                # Read once at startup; treat live changes to env as
                # operator-driven restart events.
                import os as _os
                auto_sweep = _os.environ.get(
                    "AUTO_SWEEP_ORPHAN_GTC", "true",
                ).strip().lower() in ("1", "true", "yes", "on")
                if auto_sweep:
                    logger.warning(
                        "[v19.34.89 AUTO-SWEEP] periodic orphan-GTC "
                        "auto-cancel ENABLED (interval=30s)"
                    )
                else:
                    logger.info(
                        "[v19.34.89 AUTO-SWEEP] periodic orphan-GTC "
                        "auto-cancel DISABLED via env "
                        "(AUTO_SWEEP_ORPHAN_GTC). Falling back to "
                        "surfacing-only behaviour."
                    )
                while self._running:
                    try:
                        from services.orphan_gtc_reconciler import (
                            VERDICT_NAKED_NO_POSITION,
                            VERDICT_ORPHAN_NO_TRADE,
                            SAFE_TO_AUTO_CANCEL,
                            audit_orphan_gtc_orders,
                            cancel_orphan_gtc_orders,
                        )
                        audit = await audit_orphan_gtc_orders(bot=self, only_gtc=False)
                        if audit.get("success"):
                            s = audit.get("summary", {})
                            danger = (
                                s.get(VERDICT_NAKED_NO_POSITION, 0)
                                + s.get(VERDICT_ORPHAN_NO_TRADE, 0)
                            )
                            if danger:
                                logger.error(
                                    "[v19.34.66 ORPHAN-GTC PERIODIC] %d "
                                    "dangerous orphan(s) at IB right now. "
                                    "Surface = GET /api/safety/orphan-gtc-orders",
                                    danger,
                                )
                                if auto_sweep:
                                    # Collect verdict objects for the safe set only.
                                    raw_verdicts = audit.get("verdicts") or []
                                    safe_to_cancel = []
                                    for raw in raw_verdicts:
                                        if isinstance(raw, dict):
                                            if raw.get("verdict") not in SAFE_TO_AUTO_CANCEL:
                                                continue
                                            # Rehydrate into OrderVerdict-like obj.
                                            from services.orphan_gtc_reconciler import OrderVerdict
                                            try:
                                                safe_to_cancel.append(OrderVerdict(
                                                    ib_order_id=int(raw.get("ib_order_id") or 0),
                                                    perm_id=raw.get("perm_id"),
                                                    symbol=raw.get("symbol") or "",
                                                    action=raw.get("action") or "",
                                                    quantity=int(raw.get("quantity") or 0),
                                                    order_type=raw.get("order_type") or "",
                                                    limit_price=raw.get("limit_price"),
                                                    stop_price=raw.get("stop_price"),
                                                    time_in_force=raw.get("time_in_force") or "",
                                                    status=raw.get("status") or "",
                                                    verdict=raw.get("verdict") or "",
                                                    reasons=list(raw.get("reasons") or []),
                                                    bot_trade_id=raw.get("bot_trade_id"),
                                                    ib_position_size=raw.get("ib_position_size"),
                                                    submitted_at=raw.get("submitted_at"),
                                                ))
                                            except Exception as _re:
                                                logger.debug(
                                                    "[v19.34.89] verdict rehydrate skipped: %s", _re,
                                                )
                                        else:
                                            if getattr(raw, "verdict", None) in SAFE_TO_AUTO_CANCEL:
                                                safe_to_cancel.append(raw)
                                    if safe_to_cancel:
                                        logger.warning(
                                            "[v19.34.89 AUTO-SWEEP] firing cancels for %d "
                                            "safe orphan(s): %s",
                                            len(safe_to_cancel),
                                            [(v.symbol, v.ib_order_id, v.verdict)
                                             for v in safe_to_cancel[:10]],
                                        )
                                        sweep = await cancel_orphan_gtc_orders(
                                            verdicts_to_cancel=safe_to_cancel,
                                        )
                                        n_ok = len(sweep.get("cancelled") or [])
                                        n_err = len(sweep.get("errors") or [])
                                        logger.warning(
                                            "[v19.34.89 AUTO-SWEEP] sweep complete: "
                                            "queued=%d errors=%d",
                                            n_ok, n_err,
                                        )
                                        if n_err:
                                            for err in (sweep.get("errors") or [])[:5]:
                                                logger.error(
                                                    "[v19.34.89 AUTO-SWEEP] err: %s", err,
                                                )
                                        try:
                                            await self._broadcast_event({
                                                "type": "orphan_auto_sweep",
                                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                                "queued": n_ok,
                                                "errors": n_err,
                                                "details": sweep.get("cancelled") or [],
                                            })
                                        except Exception:
                                            pass
                    except Exception as e:
                        logger.debug(
                            "[v19.34.66 ORPHAN-GTC PERIODIC] tick error "
                            "(non-fatal): %s", e,
                        )
                    await asyncio.sleep(30)
            asyncio.create_task(_periodic_orphan_gtc_audit())

            # ── v19.34.70 PATCH D — Periodic bracket-state reconciler ──
            #
            # Why this loop exists:
            #   Even with Patches A (cancel-path filter) and B (attach-path
            #   classifier), the bot's `_open_trades` rows accumulate stale
            #   `stop_order_id` / `target_order_id(s)` references over time.
            #   Patches A + B make the system RESILIENT to staleness; Patch
            #   C (the explicit endpoint) lets the operator clean up on
            #   demand. Patch D AUTOMATES that cleanup so stale refs never
            #   pile up silently in the first place.
            #
            # Loop cadence: 120s by default (env override via
            # `AUTO_RECONCILE_BRACKET_STATE_S`). 120s is conservative;
            # the periodic orphan-GTC audit runs at 30s but does more
            # work, so 120s here keeps total background load modest while
            # catching staleness within ~2 min of it appearing.
            #
            # Safety: this loop ONLY clears confirmed-stale refs (IB
            # cache snapshot is authoritative). When IB cache cannot be
            # queried (ib_direct disconnected, etc.), the underlying
            # endpoint refuses to clear anything → loop logs and skips.
            # Setting `AUTO_RECONCILE_BRACKET_STATE=false` in the env
            # disables the loop entirely.
            async def _periodic_bracket_state_reconcile():
                from os import environ
                enabled = environ.get("AUTO_RECONCILE_BRACKET_STATE",
                                      "true").lower() == "true"
                if not enabled:
                    logger.info(
                        "[v19.34.70 PATCH D] periodic bracket-state "
                        "reconcile DISABLED via env "
                        "(AUTO_RECONCILE_BRACKET_STATE=false)"
                    )
                    return
                interval_s = float(environ.get(
                    "AUTO_RECONCILE_BRACKET_STATE_S", "120"
                ))
                logger.info(
                    "[v19.34.70 PATCH D] periodic bracket-state "
                    "reconcile ENABLED (interval=%.0fs). Stale tracked "
                    "orderIds will be auto-cleared after IB cache "
                    "cross-check.", interval_s,
                )
                # Wait one full interval before the first sweep — gives
                # the bot's startup-time orphan reconciler a chance to
                # finish before we look at the cleaned-up state.
                await asyncio.sleep(interval_s)
                while self._running:
                    try:
                        from routers.trading_bot import (
                            reconcile_bracket_state,
                            ReconcileBracketStateRequest,
                        )
                        report = await reconcile_bracket_state(
                            ReconcileBracketStateRequest(dry_run=False)
                        )
                        modified = report.get("trades_modified", 0)
                        if modified > 0:
                            naked = [
                                r["symbol"] for r in report.get("trades", [])
                                if r.get("fully_unprotected")
                            ]
                            logger.warning(
                                "[v19.34.70 PATCH D] cleared stale "
                                "bracket refs from %d trade(s); %d now "
                                "fully unprotected at IB: %s. The "
                                "bracket-attach guard (manage loop) "
                                "should re-attach within its next cycle.",
                                modified, len(naked), naked,
                            )
                        elif not report.get("ib_cache_available", True):
                            logger.debug(
                                "[v19.34.70 PATCH D] skipped — IB cache "
                                "unavailable. Will retry in %.0fs.",
                                interval_s,
                            )
                    except Exception as e:
                        logger.debug(
                            "[v19.34.70 PATCH D] tick error "
                            "(non-fatal): %s", e,
                        )
                    # ── v19.34.79 — Bracket-stacking auto-cancel ──
                    # Right after the state-reconcile sweep, run the
                    # bracket-stacking auto-cancel so any GM/LIN-style
                    # excess target/stop legs that the audit identifies
                    # get cancelled in the same 120s tick. Gated by env
                    # so the operator can disable independently of the
                    # state-reconcile loop.
                    try:
                        from os import environ as _env79
                        if _env79.get("AUTO_CANCEL_BRACKET_STACKING",
                                      "true").lower() == "true":
                            from routers.trading_bot import (
                                bracket_stacking_cancel,
                                BracketStackingCancelRequest,
                            )
                            result = await bracket_stacking_cancel(
                                BracketStackingCancelRequest(dry_run=False)
                            )
                            cancelled = (result.get("totals") or {}).get("cancelled", 0)
                            refused = (result.get("totals") or {}).get("refused_symbols", 0)
                            if cancelled > 0 or refused > 0:
                                logger.warning(
                                    "[v19.34.79 bracket-cancel auto] "
                                    "cancelled=%d refused_symbols=%d "
                                    "(symbols_in_audit=%d)",
                                    cancelled, refused,
                                    (result.get("totals") or {}).get("symbols_in_audit", 0),
                                )
                    except Exception as e:
                        logger.debug(
                            "[v19.34.79 bracket-cancel auto] tick error "
                            "(non-fatal): %s", e,
                        )
                    await asyncio.sleep(interval_s)
            asyncio.create_task(_periodic_bracket_state_reconcile())

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

        # v19.34.30 Bug A-2 stale PENDING row auto-reaper
        async def _stale_pending_reaper_loop():
            import os as _os3
            interval_s = int(_os3.environ.get("PENDING_REAPER_INTERVAL_S", "60") or 60)
            max_age_s = int(_os3.environ.get("PENDING_REAPER_MAX_AGE_S", "300") or 300)
            # v19.34.300 — cancel-before-reap. Before marking a stale pending
            # `rejected`, cancel its still-WORKING entry order at IB so it cannot
            # fill AFTER the reap into a naked, unmanaged orphan (the MA
            # 2026-06-08 incident; the v234 position guard only catches orders
            # ALREADY filled at reap time, never a fill that lands later). If the
            # working order can't be provably killed, we KEEP tracking instead of
            # abandoning it. Reversible via env (default ON).
            cancel_first = (
                _os3.environ.get("PENDING_REAPER_CANCEL_FIRST", "true").strip().lower()
                in ("1", "true", "yes", "on")
            )
            disabled = (
                _os3.environ.get("PENDING_REAPER_ENABLED", "true").strip().lower()
                in ("0", "false", "no", "off")
            )
            if disabled:
                logger.info("[v19.34.30 PENDING-REAPER] disabled by env")
                return
            await asyncio.sleep(45)
            while self._running:
                try:
                    db = getattr(self, "_db", None)
                    # v19.34.236 (Part A) — attribute unattributed IB fills to
                    # their original PENDING rows BEFORE the reap decision, so
                    # a filled entry is promoted to OPEN (preserving its real
                    # setup/intent) instead of being reaped + re-adopted as a
                    # synthetic slice. Flag-gated; no-op when disabled.
                    try:
                        await self._attribute_pending_fills()
                    except Exception as _afe:
                        logger.debug("[v19.34.236] attribute_pending_fills tick failed: %s", _afe)
                    if db is not None:
                        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max_age_s)).isoformat()
                        query = {
                            "status": "pending",
                            "pre_submit_at": {"$lt": cutoff},
                            "$or": [
                                {"executed_at": None},
                                {"executed_at": {"$exists": False}},
                            ],
                        }
                        stale = list(
                            db["bot_trades"].find(
                                query, {"_id": 0, "id": 1, "symbol": 1, "pre_submit_at": 1,
                                        "entry_order_id": 1}
                            ).limit(50)
                        )
                        if stale:
                            stamp = datetime.now(timezone.utc).isoformat()
                            updated_ids: List[str] = []
                            # v19.34.234 — fill-race guard: gather live IB
                            # positions + the bot's open-trade symbols ONCE so
                            # we never reap a pending whose order actually
                            # filled at IB but wasn't attributed back.
                            ib_pos_syms: set = set()
                            try:
                                from services.ib_direct_service import get_ib_direct_service
                                _ibd = get_ib_direct_service()
                                if _ibd is not None and await _ibd.ensure_connected():
                                    for _p in (await _ibd.get_positions()) or []:
                                        if abs(float(_p.get("position") or 0)) >= 1:
                                            ib_pos_syms.add((_p.get("symbol") or "").upper())
                            except Exception as _e:
                                logger.debug(
                                    "[v19.34.234 reaper-guard] IB positions check failed: %s", _e
                                )
                            bot_open_syms: set = {
                                (getattr(t, "symbol", "") or "").upper()
                                for t in (self._open_trades or {}).values()
                            }
                            # v19.34.300 — gather live WORKING orders once so we
                            # can cancel an order before reaping its record.
                            live_orders_by_id: dict = {}
                            live_order_syms: set = set()
                            if cancel_first:
                                try:
                                    for _o in (await _ibd.get_open_orders()) or []:
                                        _oid = int(_o.get("order_id") or 0)
                                        if _oid:
                                            live_orders_by_id[_oid] = _o
                                        _osym = (_o.get("symbol") or "").upper()
                                        if _osym:
                                            live_order_syms.add(_osym)
                                except Exception as _oe:
                                    logger.debug(
                                        "[v19.34.300 cancel-first] get_open_orders failed: %s", _oe
                                    )
                            skipped_filled: List[str] = []
                            kept_working: List[str] = []
                            for row in stale:
                                tid = row.get("id")
                                if not tid:
                                    continue
                                _sym = (row.get("symbol") or "").upper()
                                if _reaper_should_skip_filled(_sym, ib_pos_syms, bot_open_syms):
                                    skipped_filled.append(f"{_sym}:{tid}")
                                    try:
                                        db["state_integrity_events"].insert_one({
                                            "event": "reaper_skip_likely_filled",
                                            "severity": "high",
                                            "symbol": _sym,
                                            "trade_id": tid,
                                            "detail": (
                                                "stale pending NOT reaped — IB holds a live "
                                                "position for this symbol the bot isn't tracking "
                                                "as open (likely unattributed fill)."
                                            ),
                                            "ts": stamp,
                                        })
                                    except Exception:
                                        pass
                                    continue
                                # v19.34.300 — CANCEL-BEFORE-REAP. If a working
                                # entry order still exists at IB, kill it before
                                # rejecting the record; if we can't provably kill
                                # it, KEEP tracking (never abandon a live order
                                # that could fill into a naked orphan).
                                if cancel_first:
                                    _eoid = row.get("entry_order_id")
                                    try:
                                        _eoid_int = int(_eoid) if _eoid not in (None, "", 0, "0") else 0
                                    except Exception:
                                        _eoid_int = 0
                                    _order_is_live = _reaper_order_still_working(
                                        row.get("entry_order_id"), _sym,
                                        live_orders_by_id, live_order_syms,
                                    )
                                    if _order_is_live:
                                        _cancelled = False
                                        if _eoid_int:
                                            try:
                                                _cres = await _ibd.cancel_order(_eoid_int)
                                                _cancelled = bool(_cres.get("success"))
                                            except Exception as _ce:
                                                logger.debug(
                                                    "[v19.34.300] cancel_order(%s) raised: %s",
                                                    _eoid_int, _ce,
                                                )
                                        if not _cancelled:
                                            # Could not provably kill the working
                                            # order → do NOT reap; keep tracking so
                                            # the reconciler/attribution promotes a
                                            # real fill instead of orphaning it.
                                            kept_working.append(f"{_sym}:{tid}")
                                            try:
                                                db["state_integrity_events"].insert_one({
                                                    "event": "reaper_skip_working_order",
                                                    "severity": "high",
                                                    "symbol": _sym,
                                                    "trade_id": tid,
                                                    "entry_order_id": _eoid_int or None,
                                                    "detail": (
                                                        "stale pending NOT reaped — a working "
                                                        "order still exists at IB and could not "
                                                        "be cancelled; kept tracking to avoid a "
                                                        "naked post-reap fill (MA-class incident)."
                                                    ),
                                                    "ts": stamp,
                                                })
                                            except Exception:
                                                pass
                                            continue
                                        # order cancelled — safe to mark rejected.
                                res = db["bot_trades"].update_one(
                                    {"id": tid, "status": "pending"},
                                    {"$set": {
                                        "status": "rejected",
                                        "close_reason": "stale_pending_auto_reaper",
                                        "closed_at": stamp,
                                        "reaped_at": stamp,
                                        "reaper_version": "v19.34.30",
                                    }},
                                )
                                if res.modified_count:
                                    updated_ids.append(tid)
                            if updated_ids:
                                logger.warning(
                                    "[v19.34.30 PENDING-REAPER] reaped %d stale PENDING row(s) (>%ds old)",
                                    len(updated_ids), max_age_s,
                                )
                                for tid in updated_ids:
                                    self._pending_trades.pop(tid, None)
                            if skipped_filled:
                                logger.warning(
                                    "[v19.34.234 reaper-guard] SKIPPED %d stale pending(s) — IB "
                                    "holds live position(s) the bot isn't tracking (likely "
                                    "unattributed fill): %s",
                                    len(skipped_filled), ", ".join(skipped_filled),
                                )
                            if kept_working:
                                logger.warning(
                                    "[v19.34.300 cancel-first] KEPT %d stale pending(s) — a "
                                    "working order still exists at IB and could not be cancelled; "
                                    "not abandoning it (would risk a naked post-reap fill): %s",
                                    len(kept_working), ", ".join(kept_working),
                                )
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.debug(f"[v19.34.30 PENDING-REAPER] loop tick failed: {e}")
                try:
                    await asyncio.sleep(interval_s)
                except asyncio.CancelledError:
                    raise

        try:
            self._pending_reaper_task = asyncio.create_task(_stale_pending_reaper_loop())
        except Exception as e:
            logger.warning(
                f"[v19.34.30 PENDING-REAPER] failed to schedule (non-fatal): {e}"
            )

        # ─── v322s — missed-EOD boot catch-up sweep ───────────────────
        # ACMR 2026-05-29: the backend was DOWN during the 15:45-16:00 ET
        # EOD window, so a close_at_eod position carried the WEEKEND and
        # gapped through its stop at Monday's open auction (-$285). The
        # in-session guards (v301/302) can't help when the process isn't
        # running — this boot task closes that hole: any tracked OPEN
        # close_at_eod trade whose fill date is a PREVIOUS session gets
        # flattened at boot (market open) or at the next open (boots
        # premarket / weekend; the task re-checks every 2 min until the
        # bell). Kill switch: MISSED_EOD_BOOT_SWEEP_ENABLED=0.
        async def _missed_eod_boot_sweep_task():
            try:
                await asyncio.sleep(75)  # let boot reconcile + rehydrate settle
                while True:
                    res = await self._position_manager.missed_eod_boot_sweep(self)
                    if not res.get("waiting_for_open"):
                        break
                    await asyncio.sleep(120)  # re-check until the open
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[v322s MISSED-EOD] boot sweep task failed: {e}")

        try:
            self._missed_eod_boot_task = asyncio.create_task(
                _missed_eod_boot_sweep_task())
        except Exception as e:
            logger.warning(
                f"[v322s MISSED-EOD] failed to schedule boot sweep (non-fatal): {e}"
            )

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
                                # v19.34.19 — operator-gated: zombie-trade
                                # drift detection ON in the loop, but
                                # auto-heal only when SHARE_DRIFT_ZOMBIE_AUTO_HEAL=true.
                                # Default False so first-ever zombie population
                                # gets reviewed before any slice spawn.
                                zombie_detect_only=os.environ.get(
                                    "SHARE_DRIFT_ZOMBIE_AUTO_HEAL", "false"
                                ).lower() not in ("true", "1", "yes", "on"),
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
                            # ── v19.34.42 — auto-consolidate after drift pass.
                            # Detects fragmented (symbol, direction) groups
                            # (N>1 open bot_trades for one IB position) and
                            # collapses them into a single canonical trade.
                            # Safety rail: only runs when kill-switch is ON
                            # OR fragments are small (≤2 per group). Disable
                            # via SHARE_DRIFT_AUTO_CONSOLIDATE=false.
                            if os.environ.get(
                                "SHARE_DRIFT_AUTO_CONSOLIDATE", "true"
                            ).lower() in ("true", "1", "yes", "on"):
                                try:
                                    from services.position_consolidator import (
                                        PositionConsolidator,
                                    )
                                    consolidator = PositionConsolidator(self._db)
                                    cresult = await consolidator.auto_consolidate_if_safe(self)
                                    if cresult.get("ran"):
                                        logger.warning(
                                            "[v19.34.42 AUTO-CONSOLIDATE] %s",
                                            cresult,
                                        )
                                        self._share_drift_diag[
                                            "last_consolidation"
                                        ] = cresult
                                except Exception as ce:
                                    logger.warning(
                                        f"[v19.34.42 AUTO-CONSOLIDATE] tick failed: {ce}"
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

        # ─── v19.34.80 (2026-05-22) — Quote-Resubscribe Watchdog ──────
        # Verifies every pusher re-subscribe RPC actually landed in the
        # live IB subscription set. Pre-v19.34.80 the position_manager
        # fired `subscribe_symbols()` and trusted the pusher's 200 OK,
        # which silently masked failures (4.9hr stale-quote operator
        # incident). The watchdog cross-checks subscriptions() and
        # force-cycles unsub+resub when a symbol the manage loop said
        # was stale never actually registers at IB. Escalates to
        # `quote_resub_watchdog_events` after 3 failed cycles.
        try:
            from services.quote_resub_watchdog import quote_resub_watchdog_loop
            self._quote_resub_watchdog_task = asyncio.create_task(
                quote_resub_watchdog_loop(self)
            )
        except Exception as e:
            logger.warning(
                f"[v19.34.80 quote-resub-watchdog] failed to schedule "
                f"(non-fatal): {e}"
            )

        # ─── v19.34.49 (2026-05-20) — Continuous Orphan-Reconcile Loop ─
        # Pure IB-only orphans (positions IB has but bot doesn't track)
        # are NOT handled by the share-drift loop (which acts only on
        # already-tracked symbols; orphans are deferred at
        # position_reconciler.py:1775 back to reconcile_orphan_positions).
        # Without this loop, mid-session orphans (manual TWS fills,
        # bracket-fill races, overnight carryovers) stay naked until
        # the operator manually clicks "Reconcile N". Production root
        # cause for the 2026-05-20 overnight 8-orphan incident.
        if os.environ.get("AUTO_ORPHAN_RECONCILE_ENABLED", "true").lower() in (
            "true", "1", "yes", "on"
        ):
            orphan_interval_s = int(
                os.environ.get("AUTO_ORPHAN_RECONCILE_INTERVAL_S", "180") or 180
            )
            if orphan_interval_s < 30:
                orphan_interval_s = 30  # safety floor

            async def _orphan_reconcile_loop():
                await asyncio.sleep(60)  # grace: pusher snapshot + boot pass settle
                logger.info(
                    "[v19.34.49 ORPHAN-LOOP] started, interval=%ss",
                    orphan_interval_s,
                )
                self._orphan_reconcile_diag = {
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "interval_s": orphan_interval_s,
                    "tick_count": 0,
                    "last_tick_at": None,
                    "last_tick_status": "pending",
                    "last_tick_error": None,
                    "last_reconciled": [],
                    "last_skipped": [],
                    "consecutive_failures": 0,
                }
                while self._running:
                    tick_started = datetime.now(timezone.utc)
                    try:
                        from routers.ib import is_pusher_connected
                        if not is_pusher_connected():
                            self._orphan_reconcile_diag["last_tick_status"] = "skipped_no_pusher"
                            self._orphan_reconcile_diag["last_tick_at"] = tick_started.isoformat()
                            self._orphan_reconcile_diag["tick_count"] += 1
                        else:
                            result = await self._position_reconciler.reconcile_orphan_positions(
                                self, all_orphans=True,
                            )
                            self._orphan_reconcile_diag["tick_count"] += 1
                            self._orphan_reconcile_diag["last_tick_at"] = tick_started.isoformat()
                            n_recon = len(result.get("reconciled") or [])
                            n_skip = len(result.get("skipped") or [])
                            self._orphan_reconcile_diag["last_tick_status"] = (
                                "ok" if result.get("success") else "error"
                            )
                            self._orphan_reconcile_diag["last_tick_error"] = result.get("error")
                            claimed = [
                                r.get("symbol") for r in (result.get("reconciled") or [])
                                if r.get("symbol")
                            ][:16]
                            self._orphan_reconcile_diag["last_reconciled"] = claimed
                            self._orphan_reconcile_diag["last_skipped"] = [
                                {"symbol": s.get("symbol"), "reason": s.get("reason")}
                                for s in (result.get("skipped") or [])
                                if s.get("symbol")
                            ][:16]
                            self._orphan_reconcile_diag["consecutive_failures"] = 0
                            if n_recon:
                                logger.warning(
                                    "[v19.34.49 ORPHAN-LOOP] auto-claimed %d orphan(s): %s "
                                    "(skipped=%d)", n_recon, claimed, n_skip,
                                )
                                try:
                                    from services.sentcom_service import emit_stream_event
                                    await emit_stream_event({
                                        "kind": "info",
                                        "event": "auto_orphan_reconcile",
                                        "text": (
                                            f"\U0001F501 Auto-orphan-reconcile claimed "
                                            f"{n_recon} naked IB orphan(s): "
                                            f"{', '.join(claimed[:8])}"
                                            + (f" (+{len(claimed)-8} more)"
                                               if len(claimed) > 8 else "")
                                        ),
                                        "metadata": {
                                            "reconciled_count": n_recon,
                                            "skipped_count": n_skip,
                                            "symbols": claimed,
                                        },
                                    })
                                except Exception:
                                    pass
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        diag = getattr(self, "_orphan_reconcile_diag", {})
                        diag["last_tick_status"] = "exception"
                        diag["last_tick_error"] = f"{type(e).__name__}: {e}"
                        diag["last_tick_at"] = tick_started.isoformat()
                        diag["consecutive_failures"] = (
                            diag.get("consecutive_failures", 0) + 1
                        )
                        logger.warning(f"[v19.34.49 ORPHAN-LOOP] tick failed: {e}")
                    try:
                        await asyncio.sleep(orphan_interval_s)
                    except asyncio.CancelledError:
                        raise

            try:
                self._orphan_reconcile_task = asyncio.create_task(_orphan_reconcile_loop())
            except Exception as e:
                logger.warning(
                    f"[v19.34.49 ORPHAN-LOOP] failed to schedule (non-fatal): {e}"
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
        # v19.34.49 — cancel the orphan-reconcile loop if it's running.
        ort = getattr(self, "_orphan_reconcile_task", None)
        if ort is not None:
            ort.cancel()
            try:
                await ort
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

                # v19.34.171 — Scalp time decay (auto-close stale scalps).
                # Budget under the EOD wall — sweep is read-mostly,
                # only acts on positions past the decay timer.
                try:
                    await asyncio.wait_for(self._check_scalp_decay(), timeout=_EOD_WALL_S)
                except asyncio.TimeoutError:
                    print(f"⚠️ [TradingBot] _check_scalp_decay exceeded {_EOD_WALL_S}s budget — skipping this cycle")
                except Exception as _sd_err:
                    print(f"⚠️ [TradingBot] _check_scalp_decay error: {_sd_err}")

                # v332 — Regime demotion policy. Confirmed adverse regime
                # flips demote conflicting intraday/swing positions
                # (stop→BE / software-stop tighten — NO IB order surgery,
                # so no orphan risk). Also keeps `_current_regime` live for
                # the sizing multiplier (it was frozen at RISK_ON since
                # boot: `_update_market_regime` was never wired into any
                # loop). Self-throttled to 30s inside the service.
                try:
                    from services.regime_demotion_service import get_regime_demotion_service
                    await asyncio.wait_for(
                        get_regime_demotion_service().tick(self), timeout=_EOD_WALL_S)
                except asyncio.TimeoutError:
                    print(f"⚠️ [TradingBot] regime demotion tick exceeded {_EOD_WALL_S}s budget — skipping this cycle")
                except Exception as _rd_err:
                    print(f"⚠️ [TradingBot] regime demotion tick error: {_rd_err}")

                # v19.34.113 — EOD setup grading. Fires once per trading
                # day at 16:10 ET. Read-mostly; the only Mongo writes
                # are upserts into `setup_grade_records`. Budgeted at
                # the same wall as EOD close — generous since a single
                # day's grading walks a few hundred bot_trades max.
                try:
                    await asyncio.wait_for(self._check_eod_grading(), timeout=_EOD_WALL_S)
                except asyncio.TimeoutError:
                    print(f"⚠️ [TradingBot] _check_eod_grading exceeded {_EOD_WALL_S}s budget — skipping this cycle")

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

        # v19.34.26 — Scanner power toggle (soft brake). When operator
        # has paused the scanner, refuse to pull new alerts into the
        # eval pipeline. In-flight evals + open-position management
        # (stop trail, scale-out, close) continue normally elsewhere
        # in this service. This is the "water pump off" semantic.
        try:
            from services.safety_guardrails import get_safety_guardrails
            guard = get_safety_guardrails()
            if guard.is_scanner_paused():
                # Single log line per cycle — don't spam. The scan loop
                # runs every 30s so this is at most 2 lines/min.
                print(
                    f"🚫 [TradingBot] scanner paused by operator "
                    f"({guard.state.scanner_paused_reason}) — skipping intake"
                )
                return
        except Exception as _e:
            # Defensive: never let a guardrail check failure block the
            # scanner loop from running. In-memory state is the worst
            # case fallback (scanner_paused=False), which preserves
            # existing behaviour.
            pass

        # Check max open positions.
        # v19.34.179 — honor the EFFECTIVE cap = min(bot config,
        # kill-switch SAFETY_MAX_POSITIONS). Previously this gate used the
        # bot value alone, so a bot cap of 25 with a kill switch of 5
        # wasted evaluation on trades the kill switch would later block at
        # execution (and made the intake number disagree with the binding
        # cap the operator sees on /effective-limits). This can only TIGHTEN
        # the gate, never loosen it — strictly safe.
        _eff_max_pos = self.risk_params.max_open_positions
        try:
            from services.safety_guardrails import SafetyConfig
            _safety_max = SafetyConfig.from_env().max_positions
            if _safety_max and _safety_max > 0:
                _eff_max_pos = min(_eff_max_pos, _safety_max)
        except Exception:
            pass
        if len(self._open_trades) >= _eff_max_pos:
            # 2026-04-28: was a silent return — now logs into Bot's Brain
            # so operator sees the cap is what's gating new entries.
            self.record_rejection(
                symbol="—",
                setup_type="any",
                direction="",
                reason_code="max_open_positions",
                context={"cap": _eff_max_pos,
                         "bot_cap": self.risk_params.max_open_positions},
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
                # v19.34.243 — PER-ENTRY GATE. The pause + max-position checks
                # at the top of this method run ONCE per cycle. Without
                # re-checking here, a multi-alert batch (a) keeps firing after
                # an operator pauses mid-cycle (the 2026-06-03 CEG case), and
                # (b) overshoots the position cap (open=24, cap=25 → a 3-alert
                # batch opened 27 on 2026-06-02). Re-check both per entry and
                # STOP the batch the moment either binds. Counts pending so
                # in-flight entries count against the cap.
                try:
                    from services.safety_guardrails import get_safety_guardrails
                    _paused_now = get_safety_guardrails().is_scanner_paused()
                except Exception:
                    _paused_now = False
                from services.entry_gate import per_entry_gate_should_stop
                if per_entry_gate_should_stop(
                    len(self._open_trades), len(self._pending_trades),
                    _eff_max_pos, _paused_now,
                ):
                    _live_count = len(self._open_trades) + len(self._pending_trades)
                    self.record_rejection(
                        symbol=alert.get("symbol", "—"),
                        setup_type=alert.get("setup_type", "any"),
                        direction=alert.get("direction", ""),
                        reason_code=("scanner_paused_mid_cycle" if _paused_now
                                     else "max_open_positions"),
                        context={"cap": _eff_max_pos, "live_count": _live_count,
                                 "per_entry_gate_v19_34_243": True,
                                 "paused": _paused_now},
                    )
                    print(f"🚫 [v19.34.243 per-entry gate] halting batch "
                          f"(paused={_paused_now}, open+pending={_live_count}, "
                          f"cap={_eff_max_pos})")
                    break

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
                    # v19.34.36 — thread alert.id through so the evaluator
                    # can stamp it on BotTrade.alert_id, restoring the
                    # alert→trade join key for learning_loop pending-context
                    # lookups and decision_trail Mongo queries.
                    'alert_id': alert.id,
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
                    'auto_execute_eligible': alert.auto_execute_eligible,
                    # ── v19.34.175 — TQS/SMB unification ───────────────
                    # Pre-fix, this manually-rebuilt dict DROPPED every
                    # grade + quality field, so (a) the grade scaler in
                    # `calculate_position_size` resolved to D (0.1x) on
                    # EVERY trade and (b) the post-gate TQS recalc ran on
                    # hardcoded defaults (smb_grade="B", tape=0, rr=2.0).
                    # Thread the real scanner values so TQS is the single
                    # source of truth for grade + sizing. SMB grade is
                    # carried for AUDIT ONLY (no longer drives sizing).
                    'tqs_score': getattr(alert, 'tqs_score', 0.0),
                    'tqs_grade': getattr(alert, 'tqs_grade', '') or '',
                    'tqs_action': getattr(alert, 'tqs_action', '') or '',
                    'tqs_pillar_scores': getattr(alert, 'tqs_pillar_scores', {}) or {},
                    'tqs_pillar_grades': getattr(alert, 'tqs_pillar_grades', {}) or {},
                    'tqs_breakdown': getattr(alert, 'tqs_breakdown', {}) or {},
                    'tqs_weights': getattr(alert, 'tqs_weights', {}) or {},
                    'trade_style': getattr(alert, 'trade_style', '') or '',
                    'tape_score': getattr(alert, 'tape_score', 0) or 0,
                    'smb_score_total': getattr(alert, 'smb_score_total', 0) or 0,
                    'risk_reward': getattr(alert, 'risk_reward', 0) or 0,
                    'smb_grade': getattr(alert, 'trade_grade', '') or '',
                    'trade_grade': getattr(alert, 'trade_grade', '') or '',
                }
                
                # 2026-05-01 v19.20 — skip watchlist-only setups silently.
                # These are EOD carry-forward tags and pre-trigger proximity
                # warnings that fire for tomorrow's plan / early warnings,
                # not for live evaluation. Surfacing them as "setup_disabled"
                # rejections every cycle was flooding the Deep Feed with
                # noise while the alerts themselves are still consumed by
                # gameplan_service for next-day watchlists.
                #
                # v19.34.164: write directly to `trade_drops` (bypassing
                # record_rejection which would re-flood Bot's Brain). The
                # Diagnostics tab now sees these drops while the live UI
                # stream stays quiet.
                if alert.setup_type in self._watchlist_only_setups:
                    try:
                        from services.trade_drop_recorder import record_trade_drop
                        record_trade_drop(
                            getattr(self, "_db", None),
                            gate="watchlist_only_skip",
                            symbol=alert.symbol,
                            setup_type=alert.setup_type,
                            direction=alert.direction or "long",
                            reason="watchlist-only setup (EOD carry/proximity warn) — not live-tradable",
                            context={"alert_priority": alert.priority.value if alert.priority else None},
                        )
                    except Exception:
                        pass
                    continue

                # v19.34.244 — DISABLED_SETUPS blocklist. Some setup VARIANTS
                # are confirmed money-losers (e.g. vwap_fade_short: 8% win,
                # -4.26R, -$22k over 120d — while vwap_fade_long is +0.51R and
                # stays enabled). Block the exact setup_type from TRADING here
                # while leaving the scanner free to still surface it for
                # monitoring/shadow. Operator-overridable via the DISABLED_SETUPS
                # env (comma-sep setup_types); default blocks vwap_fade_short.
                if alert.setup_type.lower() in self._disabled_setups():
                    print(f"   🚫 {alert.symbol} {alert.setup_type} in DISABLED_SETUPS — not trading")
                    self.record_rejection(
                        symbol=alert.symbol,
                        setup_type=alert.setup_type,
                        direction=alert.direction or "long",
                        reason_code="setup_in_disabled_blocklist_v19_34_244",
                        context={"disabled_setups": sorted(self._disabled_setups())},
                    )
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

        # ── v19.34.179 — quality-ranked slot allocation ───────────────
        # The scarce position slots (max_open_positions) are filled by
        # iterating this list in order until the cap is hit. Rank by
        # priority bucket → TQS score → trigger probability → raw score so
        # the BEST ideas get the slots, not whatever arrived first. (The
        # scanner already orders by priority, but the dict round-trip +
        # the [:20] truncation below need this to be explicit and stable.)
        #
        # ── v19.34.185 (F-F) — gameplan-aware soft conviction boost ─────
        # Names on today's PREMARKET gameplan (pm_/daily-sourced conviction)
        # and alerts whose direction aligns with the day's market bias get a
        # mild, env-tunable bump applied to the TQS dimension of the rank key.
        # Ranking-only: it never changes the stored TQS grade or any gate
        # decision, and the priority bucket still dominates (so a low-priority
        # gameplan name can't jump a high-priority non-gameplan one).
        _gp_watchlist, _gp_bias = self._get_gameplan_conviction()
        import os as _os_ff
        _w_watch = float(_os_ff.environ.get("GAMEPLAN_WATCHLIST_BOOST", "8"))
        _w_bias = float(_os_ff.environ.get("GAMEPLAN_BIAS_BOOST", "4"))

        def _alert_rank(a: Dict):
            prio = {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(
                str(a.get("priority") or "medium").lower(), 4
            )
            boost = self._compute_gameplan_boost(a, _gp_watchlist, _gp_bias, _w_watch, _w_bias)
            return (
                prio,
                -(float(a.get("tqs_score") or 0) + boost),
                -float(a.get("trigger_probability") or 0),
                -float(a.get("score") or 0),
            )

        alerts.sort(key=_alert_rank)

        return alerts[:20]  # Top 20 alerts (best-ranked first)

    @staticmethod
    def _compute_gameplan_boost(alert: Dict, watchlist: set, bias, w_watch: float, w_bias: float) -> float:
        """v19.34.185 (F-F) — ranking-only conviction boost for an alert.

        +w_watch if the symbol is on today's premarket/daily gameplan watchlist.
        +w_bias  if the alert's direction aligns with the day's market bias
                 (long when Bullish, short when Bearish; nothing when Neutral).
        Never negative; never touches the stored TQS or any gate.
        """
        boost = 0.0
        sym = str(alert.get("symbol") or "").upper()
        if sym and watchlist and sym in watchlist:
            boost += w_watch
        b = (bias or "").lower()
        if b in ("bullish", "bearish"):
            direction = str(alert.get("direction") or "").lower()
            if (b == "bullish" and direction in ("long", "buy")) or \
               (b == "bearish" and direction in ("short", "sell")):
                boost += w_bias
        return boost

    def _get_gameplan_conviction(self):
        """v19.34.185 (F-F) — today's gameplan conviction set, cached ~5 min.

        Returns (watchlist:set[str], bias:str|None) where watchlist holds only
        symbols sourced from the PREMARKET/DAILY scan (genuine pre-open
        conviction) — NOT intraday live alerts (which would make the boost
        circular). The 5-min TTL lets the 09:00 ET premarket regeneration be
        picked up the same session.
        """
        import time as _time
        try:
            import pytz as _pytz
            today = datetime.now(_pytz.timezone('America/New_York')).strftime("%Y-%m-%d")
        except Exception:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        cache = getattr(self, "_gameplan_conviction_cache", None)
        now = _time.time()
        if cache and cache.get("date") == today and (now - cache.get("ts", 0)) < 300:
            return cache["watchlist"], cache["bias"]

        watchlist, bias = set(), None
        try:
            db = self._db
            if db is None:
                from database import get_database
                db = get_database()
            plan = db["game_plans"].find_one(
                {"date": today}, {"_id": 0, "stocks_in_play": 1, "bias": 1}
            )
            if plan:
                for s in (plan.get("stocks_in_play") or []):
                    if s.get("source") in ("premarket_scanner", "daily_scanner"):
                        sym = s.get("symbol")
                        if sym:
                            watchlist.add(str(sym).upper())
                bias = (str(plan.get("bias") or "").lower() or None)
        except Exception as e:
            print(f"[F-F] gameplan conviction load skipped: {e}")

        self._gameplan_conviction_cache = {"date": today, "ts": now, "watchlist": watchlist, "bias": bias}
        return watchlist, bias
    
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
    
    async def _attribute_pending_fills(self):
        """v19.34.236 (Part A) — promote PENDING rows whose entry actually
        FILLED at IB (but the fill was never attributed back) into OPEN
        trades, matched to the live IB orphan — instead of letting the reaper
        falsely reject them and the reconciler re-adopt the shares as a
        synthetic slice (the entry_order_id=None race, 2026-06-03).

        Flag-gated (`PENDING_FILL_ATTRIBUTION_ENABLED`, default OFF) so the
        deployed code is inert until the operator enables + watches it.

        Submits NO orders: the promoted OPEN trade is left for the existing
        (v235-clamped) naked-position sweep to protect on its next cycle.
        """
        import os as _os
        # v19.34.236 — ON by default (operator-enabled 2026-06-03). Instant
        # disable via PENDING_FILL_ATTRIBUTION_ENABLED=0 + restart.
        if _os.environ.get("PENDING_FILL_ATTRIBUTION_ENABLED", "true").strip().lower() \
                not in ("1", "true", "yes", "on"):
            return
        if not self._pending_trades:
            return
        try:
            from services.ib_direct_service import get_ib_direct_service
            ibd = get_ib_direct_service()
            if ibd is None or not await ibd.ensure_connected():
                return
            positions = await ibd.get_positions() or []
        except Exception as e:
            logger.debug("[v19.34.236] get_positions failed: %s", e)
            return

        bot_open_syms = {
            (getattr(t, "symbol", "") or "").upper()
            for t in (self._open_trades or {}).values()
        }
        # symbol -> (signed_qty, avg_cost) for orphans the bot isn't tracking.
        orphans: Dict[str, tuple] = {}
        for p in positions:
            sym = (p.get("symbol") or "").upper()
            q = float(p.get("position") or 0.0)
            if sym and abs(q) >= 1 and sym not in bot_open_syms:
                orphans[sym] = (q, float(p.get("avg_cost") or p.get("avgCost") or 0.0))
        if not orphans:
            return

        from services.pending_fill_attribution import (
            match_pending_to_orphan, build_promotion_update,
        )
        pending_rows = []
        for t in self._pending_trades.values():
            pending_rows.append({
                "id": getattr(t, "id", None),
                "symbol": (getattr(t, "symbol", "") or "").upper(),
                "direction": (getattr(t.direction, "value", None) or str(getattr(t, "direction", ""))).lower(),
                "shares": int(getattr(t, "shares", 0) or 0),
                "pre_submit_at": getattr(t, "pre_submit_at", None),
            })

        now = datetime.now(timezone.utc)
        for sym, (signed_qty, avg_cost) in orphans.items():
            tid = match_pending_to_orphan(sym, signed_qty, pending_rows, now)
            if not tid:
                continue
            trade = self._pending_trades.get(tid)
            if trade is None:
                continue
            qty_abs = abs(int(round(signed_qty)))
            fill_price = avg_cost or float(getattr(trade, "entry_price", 0) or 0)
            upd = build_promotion_update(qty_abs, fill_price, now.isoformat())

            trade.status = TradeStatus.OPEN
            trade.fill_price = upd["fill_price"]
            trade.executed_at = upd["executed_at"]
            trade.remaining_shares = upd["remaining_shares"]
            trade.original_shares = upd["original_shares"]
            trade.shares = upd["shares"]
            trade.close_reason = None
            trade.notes = (getattr(trade, "notes", "") or "") + (
                f" [v19.34.236 PENDING-FILL-ATTRIBUTED {qty_abs}@{fill_price:.2f}]"
            )

            self._pending_trades.pop(tid, None)
            self._open_trades[tid] = trade

            try:
                save_fn = getattr(self, "_save_trade", None) or getattr(self, "_persist_trade", None)
                if save_fn:
                    r = save_fn(trade)
                    if asyncio.iscoroutine(r):
                        await r
            except Exception:
                pass
            try:
                if getattr(self, "_db", None) is not None:
                    self._db["state_integrity_events"].insert_one({
                        "event": "pending_fill_attributed",
                        "severity": "high",
                        "symbol": sym,
                        "trade_id": tid,
                        "qty": qty_abs,
                        "fill_price": fill_price,
                        "detail": (
                            "PENDING row promoted to OPEN — matched an "
                            "unattributed live IB fill; naked-sweep will protect it."
                        ),
                        "ts": now.isoformat(),
                    })
            except Exception:
                pass
            logger.warning(
                "[v19.34.236] PROMOTED pending %s %s -> OPEN (attributed IB fill %d @ %.2f) "
                "— left for naked-sweep to protect.",
                sym, tid, qty_abs, fill_price,
            )

    async def _execute_trade(self, trade: BotTrade):
        """Execute a trade — delegated to TradeExecution module, gated by the
        central safety guardrails (daily-loss / stale-quote / exposure caps).

        Safety check runs LAST before execution so it sees the final notional
        size chosen by the opportunity evaluator. Any failure → trade is
        skipped (not cancelled) and the reason is stream-logged so the UI's
        Unified Stream shows why the bot refused to take it.
        """
        try:
            # ── v19.34.25 PATCH-G + PATCH-H — Startup gates ─────────
            # Hard fences before ANY entry can fire. These exist
            # because the 2026-02 stampede disaster showed that:
            #   (1) the bot's scan loop fires within 1-2s of start(),
            #   (2) Patch F's orphan-GTC audit had a 25s sleep before
            #       it could run, so the scan loop raced past its own
            #       boot protection,
            #   (3) staged pre-market signals + a freshly-flipped
            #       kill switch produced 7 simultaneous market-orders
            #       that filled instantly, leaving the account naked
            #       when the account guard tripped seconds later.
            #
            # Gate H (startup grace) — refuse to fire entries for the
            # first STARTUP_GRACE_SECONDS (default 60s) after start().
            # This lets stale pre-market signals expire instead of
            # cascading, and gives Patch F time to complete its audit.
            # Operator can override via env to 0 if they want the old
            # zero-grace behaviour back.
            #
            # Gate G (Patch F audit) — refuse to fire entries until
            # the orphan-GTC audit has completed at least once. The
            # tripwire ALWAYS sets _patch_f_audit_complete=True in its
            # finally block, so a crashed/timed-out audit doesn't
            # brick entries indefinitely.
            import os as _os_gate
            from datetime import datetime as _dt_gate, timezone as _tz_gate
            grace_seconds = int(_os_gate.environ.get(
                "STARTUP_GRACE_SECONDS", "60",
            ))
            if self._started_at is not None and grace_seconds > 0:
                elapsed = (_dt_gate.now(_tz_gate.utc) - self._started_at).total_seconds()
                if elapsed < grace_seconds:
                    logger.warning(
                        "[v19.34.25 PATCH-H GATE] entry SKIPPED for %s "
                        "%s — bot in startup grace (%.1fs / %ds). "
                        "Set STARTUP_GRACE_SECONDS=0 to disable.",
                        getattr(trade, "symbol", "?"),
                        getattr(trade, "direction", "?"),
                        elapsed, grace_seconds,
                    )
                    return
            if not self._patch_f_audit_complete:
                logger.warning(
                    "[v19.34.25 PATCH-G GATE] entry SKIPPED for %s %s "
                    "— Patch F audit has not yet run. Bot will retry "
                    "on next scan tick.",
                    getattr(trade, "symbol", "?"),
                    getattr(trade, "direction", "?"),
                )
                return

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
                # ── v19.34.28 Patch L2b — ib_direct managedAccounts fast path ──
                # When BOT_ORDER_PATH=direct, the operator has authorized
                # ib-direct (clientId=11) as the canonical order socket.
                # Its managedAccounts list is the most direct source of
                # truth for "what account am I actually trading on" and
                # eliminates the Patch I pusher-warmup race (managedAccounts
                # is populated synchronously during IB Gateway handshake).
                if (os.environ.get("BOT_ORDER_PATH", "pusher") or "pusher").strip().lower() == "direct":
                    try:
                        from services.ib_direct_service import get_ib_direct_service
                        _ibd = get_ib_direct_service()
                        if _ibd is not None and _ibd.is_connected() and _ibd.is_authorized_to_trade():
                            _managed = _ibd._ib.managedAccounts() if _ibd._ib else []
                            if _managed:
                                _current_acct = next((a for a in _managed if a), None)
                                logger.debug(
                                    "[v19.34.28 L2b] account_guard using "
                                    "ib_direct.managedAccounts: %s", _current_acct,
                                )
                    except Exception as _ibd_exc:
                        logger.debug(
                            "[v19.34.28 L2b] ib_direct account lookup "
                            "failed (falling back to pusher): %s", _ibd_exc,
                        )
                if not _current_acct:
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
                # v19.34.25 Patch I — if the first check failed because
                # account_id is None, retry with the pusher's
                # first-POST timestamp so the warmup window applies.
                # Only kicks in for the missing-account branch; a true
                # mismatch (paper-vs-live drift) still fails fast.
                if not _ok and not _current_acct:
                    try:
                        from routers.ib import _pushed_ib_data as _pid
                        from datetime import datetime as _dt_ag, timezone as _tz_ag
                        _first_ts = _pid.get("first_pushed_at")
                        if _first_ts:
                            _first_seen_dt = _dt_ag.fromisoformat(
                                _first_ts.replace("Z", "+00:00")
                            )
                            _ok, _reason = check_account_match(
                                _current_acct,
                                pusher_first_seen_at=_first_seen_dt,
                            )
                    except Exception as _warmup_exc:
                        logger.debug(
                            "[v19.34.25 PATCH-I] warmup lookup skipped: %s",
                            _warmup_exc,
                        )
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

    async def _check_scalp_decay(self):
        """v19.34.171 — Scalp time decay — delegated to PositionManager."""
        await self._position_manager.check_scalp_decay(self)

    async def _check_eod_grading(self):
        """v19.34.113 — Once-per-day setup grading EOD tick.

        Fires at 16:10 ET (after EOD auto-close at 15:55 ET + a 15min
        flush window). Idempotent: stamps the trading_date key after
        a successful run, skips on subsequent calls inside the same
        day. A crash before stamping replays cleanly because the
        grading service itself upserts (no duplicate rows).
        """
        try:
            from zoneinfo import ZoneInfo
            et = ZoneInfo("US/Eastern")
            now_et = datetime.now(et)
            today_key = now_et.strftime("%Y-%m-%d")

            # Already graded today.
            if self._eod_grading_executed_today_key == today_key:
                return

            # Only fire at/after 16:10 ET on weekdays.
            if now_et.weekday() >= 5:  # Sat/Sun
                return
            if (now_et.hour, now_et.minute) < (self._eod_grading_hour, self._eod_grading_minute):
                return

            from services.setup_grading_service import get_setup_grading_service
            svc = get_setup_grading_service()
            result = await asyncio.to_thread(svc.compute_eod_grades, today_key)
            self._eod_grading_executed_today_key = today_key
            print(
                f"📊 [v19.34.113 EOD-GRADE] {today_key} — graded "
                f"{result.get('setups_graded', 0)} setup_type(s)"
            )
        except Exception as e:
            # Never let a grading failure crash the scan loop. Operator
            # can recompute manually via POST /api/setup-grades/compute.
            print(f"⚠️ [v19.34.113 EOD-GRADE] error: {e}")

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

    async def close_trade_custom(
        self,
        trade_id: str,
        *,
        percentage: float = 100.0,
        order_type: str = "market",
        limit_price: Optional[float] = None,
        reason: str = "manual_panel_close",
    ) -> Dict:
        """v19.34.72 — Operator-driven Close with order_type + partial qty.
        Delegated to PositionManager.close_trade_custom."""
        return await self._position_manager.close_trade_custom(
            trade_id, self,
            percentage=percentage,
            order_type=order_type,
            limit_price=limit_price,
            reason=reason,
        )

    
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

    # ── v19.34.123 (Feb 2026) — Continuous real-time kill-switch monitor ──
    #
    # Pre-v123 daily-loss enforcement was entirely synchronous with the
    # scan loop:
    #   - `_scan_loop` checked `self._daily_stats.net_pnl <= -max_daily_loss`
    #     ONCE per iteration (scan cadence ~1-3s).
    #   - `_daily_stats.net_pnl` was a stale cached value that missed
    #     every close path except `bot.close_trade()`.
    # Feb 2026 incident: bot took $25k of losses while the $5k cap "passed"
    # because (a) most closes were OCA-ext / operator-flatten / consolidator
    # paths that didn't update `_daily_stats.net_pnl` (v123 paths fix this
    # — see services/pnl_compute.py), and (b) once scanner paused, the
    # check never ran at all.
    #
    # Post-v123: an INDEPENDENT 15s task reads PnL directly from
    # `bot_trades` (today's UTC closed trades) PLUS live unrealized PnL
    # from `_open_trades`. Fires `safety_guardrails.trip_kill_switch()`
    # AND `bot.pause()` when total ≤ -max_daily_loss. Survives scanner
    # pause, runs whenever the bot service is up.
    #
    # Reads from BOTH max_daily_loss caps (risk_params + safety_config)
    # and trips on the lower (more restrictive) one.

    async def _kill_switch_monitor_loop(self):
        """Continuous daily-loss enforcement — runs every 15s."""
        import os
        # v19.34.126 — use print() not logger.info() so heartbeats appear
        # in /tmp/backend.log. server.py has no logging.basicConfig() so
        # logger.info() output from service modules is silently dropped.
        # See server.py:1511 for the historical note on this gotcha.
        print("[v123 kill-switch] task launched, importing motor...", flush=True)
        try:
            import motor.motor_asyncio
        except ImportError:
            print(
                "[v123 kill-switch] motor not available — continuous "
                "monitor DISABLED",
                flush=True,
            )
            logger.warning(
                "[v123 kill-switch] motor not available — continuous "
                "monitor disabled"
            )
            return

        mongo_url = os.environ.get("MONGO_URL")
        if not mongo_url:
            print(
                "[v123 kill-switch] MONGO_URL not set — continuous "
                "monitor DISABLED",
                flush=True,
            )
            logger.warning(
                "[v123 kill-switch] MONGO_URL not set — continuous "
                "monitor disabled"
            )
            return

        client = motor.motor_asyncio.AsyncIOMotorClient(mongo_url)
        db = client[os.environ.get("DB_NAME", "tradecommand")]

        print(
            "[v123 kill-switch] Continuous monitor started (15s cadence)",
            flush=True,
        )
        logger.info("[v123 kill-switch] Continuous monitor started (15s cadence)")
        _hb_counter = 0  # v19.34.125 — periodic INFO heartbeat

        while self._running:
            try:
                await asyncio.sleep(15.0)
                snapshot = await self._compute_realtime_daily_pnl(db)
                total_pnl = snapshot["realized"] + snapshot["unrealized"]

                # Compute the effective daily-loss limit. Pick LOWER
                # (more restrictive) of risk_params.max_daily_loss and
                # safety_config.max_daily_loss_usd.
                limits = []
                rp_lim = float(getattr(self.risk_params, "max_daily_loss", 0) or 0)
                if rp_lim > 0:
                    limits.append(rp_lim)
                try:
                    from services.safety_guardrails import get_safety_guardrails
                    sg = get_safety_guardrails()
                    sg_lim = float(getattr(sg.config, "max_daily_loss_usd", 0) or 0)
                    if sg_lim > 0:
                        limits.append(sg_lim)
                except Exception:
                    sg = None
                if not limits:
                    continue
                effective_limit = min(limits)

                if total_pnl <= -effective_limit:
                    # TRIP
                    reason = (
                        f"v123_realtime_monitor: realized=${snapshot['realized']:,.0f} "
                        f"+ unrealized=${snapshot['unrealized']:,.0f} "
                        f"= ${total_pnl:,.0f} ≤ -${effective_limit:,.0f} "
                        f"(over {snapshot['closed_count']} closed trades)"
                    )
                    # v19.34.126 — print() for log visibility (logger.error
                    # also fires but may be filtered by stderr handler config).
                    print(f"[v123 kill-switch] TRIPPED — {reason}", flush=True)
                    logger.error("[v123 kill-switch] TRIPPED — %s", reason)
                    if sg is not None:
                        try:
                            sg.trip_kill_switch(reason)
                        except Exception as e:
                            logger.error("[v123 kill-switch] trip failed: %s", e)
                    # Also flip bot to paused mode so scan loop stops
                    # firing new entries even if kill-switch reset.
                    try:
                        from services.trading_bot_service import BotMode as _BM
                        self._mode = _BM.PAUSED
                    except Exception:
                        pass
                    self._daily_stats.daily_limit_hit = True
                elif abs(total_pnl) > 0:
                    # Diagnostic heartbeat (DEBUG-level so we don't spam INFO)
                    logger.debug(
                        "[v123 kill-switch] pnl=$%.0f / limit=$%.0f (%d closed)",
                        total_pnl, effective_limit, snapshot["closed_count"],
                    )

                # v19.34.125/126 — periodic heartbeat (~once every 4 min)
                # so the operator can `grep "v123 kill-switch"` and confirm
                # the background task is alive, even on a quiet PnL day.
                # Uses print() because server.py has no logging.basicConfig().
                _hb_counter += 1
                if _hb_counter % 16 == 0:
                    msg = (
                        f"[v123 kill-switch] heartbeat: realized=${snapshot['realized']:.0f} "
                        f"unrealized=${snapshot['unrealized']:.0f} "
                        f"limit=${effective_limit:.0f} closed={snapshot['closed_count']} (alive)"
                    )
                    print(msg, flush=True)
                    logger.info(msg)

                # v19.34.127 — Naked-position sweep (every 4th iter = 60s).
                # The actual -$25k cause: yesterday IB mass-cancelled
                # 100+ stops independently of our code, leaving the bot
                # holding naked positions with no detection path. This
                # sweep walks `_open_trades`, asks IB for live orders,
                # and emergency-reissues any missing stop. Result lands
                # in `bracket_lifecycle_events` so future incidents are
                # traceable.
                if _hb_counter % 4 == 0:
                    try:
                        sweep_result = await self._naked_position_sweep()
                        # v19.34.128 — proof-of-life: print the FIRST sweep's
                        # outcome regardless of mode so the operator can
                        # verify the loop is wired up. In paper mode this
                        # surfaces `skipped_reason=non_live_mode:PAPER` so
                        # the user knows the sweep is alive but inactive.
                        # After the first, only print on activity (already
                        # handled inside _naked_position_sweep).
                        if _hb_counter == 4:
                            print(
                                f"[v127 naked-sweep] first sweep complete: "
                                f"{sweep_result}",
                                flush=True,
                            )
                    except Exception as _sweep_err:
                        print(
                            f"[v127 naked-sweep] iteration crashed: {_sweep_err}",
                            flush=True,
                        )
                        logger.error(
                            "[v127 naked-sweep] iteration crashed: %s", _sweep_err,
                        )
            except asyncio.CancelledError:
                logger.info("[v123 kill-switch] monitor cancelled")
                return
            except Exception as e:
                logger.error("[v123 kill-switch] monitor iteration crashed: %s", e)
                await asyncio.sleep(5.0)

    async def _compute_realtime_daily_pnl(self, db) -> Dict[str, float]:
        """Single source of truth for "today's PnL right now". Reads
        directly from `bot_trades` (realized) + `_open_trades` cache
        (unrealized). PAPER trades excluded.

        Today's window = UTC midnight to now.
        """
        from datetime import datetime as _dt, timezone as _tz
        today_iso = _dt.now(_tz.utc).strftime("%Y-%m-%dT00:00:00")

        # Realized — sum net_pnl on today's LIVE closed trades
        realized = 0.0
        closed_count = 0
        try:
            cursor = db["bot_trades"].find({
                "status": {"$in": ["closed", "CLOSED"]},
                "$or": [
                    {"closed_at":   {"$gte": today_iso}},
                    {"exit_time":   {"$gte": today_iso}},
                ],
            }, {"_id": 0, "net_pnl": 1, "realized_pnl": 1, "executor_mode": 1, "mode": 1})
            async for t in cursor:
                m = (t.get("executor_mode") or t.get("mode") or "LIVE").upper()
                if m == "PAPER":
                    continue
                v = t.get("net_pnl")
                if v is None:
                    v = t.get("realized_pnl") or 0.0
                try:
                    realized += float(v)
                except (TypeError, ValueError):
                    pass
                closed_count += 1
        except Exception as e:
            logger.debug("[v123 kill-switch] realized-pnl query failed: %s", e)

        # Unrealized — sum from in-memory open trades (best-effort).
        # v19.34.226 — SKIP any trade with no valid mark (current_price <= 0).
        # A single stale-priced position (CRM 95sh, current_price=0) produced a
        # FAKE -$18,897 unrealized that repeatedly tripped the daily-loss
        # kill-switch even though genuine intraday P&L was +$7. A missing mark
        # must NEVER trip the kill-switch.
        unrealized = 0.0
        skipped_no_mark = 0
        try:
            for t in self._open_trades.values():
                try:
                    cur = float(getattr(t, "current_price", 0) or 0)
                    if cur <= 0:
                        skipped_no_mark += 1
                        continue
                    unrealized += float(getattr(t, "unrealized_pnl", 0) or 0)
                except (TypeError, ValueError):
                    continue
        except Exception:
            pass
        if skipped_no_mark:
            logger.warning(
                "[v123 kill-switch] skipped %d open trade(s) with no valid mark "
                "(current_price<=0) from the unrealized sum", skipped_no_mark,
            )

        return {
            "realized":     round(realized, 2),
            "unrealized":   round(unrealized, 2),
            "closed_count": closed_count,
        }


    # ─── v19.34.127 — Naked-position sweep ─────────────────────────────
    #
    # Yesterday's incident (-$25k): IB mass-cancelled 100+ of our stops
    # at 11:21 and 15:29. Our consolidator / reissue paths only fire when
    # we initiate the change; if IB independently nukes a stop (admin
    # cancel, OCA conflict, max-orders trim, etc.) we had ZERO detection.
    # `bracket_lifecycle_events` for RJF/MTB/ARGX/UPS confirmed: 0
    # reissue events on the bleeding day.
    #
    # This sweep, fired every 60s inside `_kill_switch_monitor_loop`,
    # asks IB for the live order book and cross-references against
    # every `trade.stop_order_id` in `_open_trades`. Any mismatch →
    # emergency `attach_oca_stop_target` + persist a `phase:
    # "naked_sweep_reissue"` row to `bracket_lifecycle_events` so the
    # operator can audit what happened.
    #
    # Skipped silently when:
    #   • Bot is in PAPER mode (no IB connection)
    #   • Trade executor not attached
    #   • IB get_open_orders raises (broker offline) — next sweep retries

    async def _naked_position_sweep(self) -> Dict[str, Any]:
        """Walk `_open_trades` and reissue any missing stop at IB.

        Returns a result dict for diagnostics / tests:
            {"checked": int, "naked_found": int, "reissued": int,
             "reissue_failed": int, "skipped_reason": Optional[str]}
        """
        result: Dict[str, Any] = {
            "checked": 0, "naked_found": 0, "reissued": 0,
            "reissue_failed": 0, "skipped_reason": None,
        }

        executor = getattr(self, "_trade_executor", None)
        if executor is None:
            result["skipped_reason"] = "no_trade_executor"
            return result

        # Resolve open-orders source. v19.34.129: delegate to the
        # existing 3-tier resolver (ib_direct → pusher-relay →
        # `_pushed_ib_data["orders"]` snapshot from the Windows pusher).
        # The DGX deployment shape is pusher-only — `_ib_client` on the
        # executor stays None and the bot never has a direct IB
        # connection. The pusher publishes its `openTrades()` snapshot
        # to `_pushed_ib_data["orders"]` every 10s, which is the
        # authoritative source for naked-detection in this setup.
        try:
            from services.orphan_gtc_reconciler import _fetch_ib_open_orders
            ib_orders, source_info = await _fetch_ib_open_orders()
        except Exception as e:
            result["skipped_reason"] = f"open_orders_fetch_failed:{e}"
            return result
        if ib_orders is None:
            result["skipped_reason"] = (
                f"open_orders_unavailable:{source_info.get('error') or 'no_source'}"
            )
            return result
        result["source_tier"] = source_info.get("tier")

        # ─────────── v19.34.31 PATCH E ─────────── # v19_34_31_PATCH_E_pusher_stale_guard
        # If the pusher snapshot used to build live_order_ids is older
        # than PUSHER_STALE_THRESHOLD_SEC, the snapshot is missing
        # recently-issued OCA stop/target IDs — the naked sweep will
        # then wrongly flag every active bracket as NAKED and trigger
        # an emergency reissue cascade (bracket stacking).
        PUSHER_STALE_THRESHOLD_SEC = 45.0
        try:
            if (source_info or {}).get("tier") == "pusher_orders_snapshot":
                from routers.ib import _pushed_ib_data
                # v19.34.320L — use module-global datetime/timezone (line 19).
                # The prior local "from datetime import datetime, timezone" here
                # bound them function-wide, causing UnboundLocalError at the
                # naked-sweep telemetry write (~L6530) when this branch wasn't taken.
                _lu = (_pushed_ib_data or {}).get("last_update")
                if _lu:
                    _last_dt = datetime.fromisoformat(str(_lu).replace("Z", "+00:00"))
                    _age = (datetime.now(timezone.utc) - _last_dt).total_seconds()
                    result["pusher_age_sec"] = _age
                    if _age > PUSHER_STALE_THRESHOLD_SEC:
                        result["skipped_reason"] = f"pusher_snapshot_stale:{_age:.1f}s"
                        print(
                            f"[v127 naked-sweep] SKIP — pusher snapshot is "
                            f"{_age:.1f}s old (>{PUSHER_STALE_THRESHOLD_SEC}s). "
                            f"Refusing to reissue brackets on a stale order book.",
                            flush=True,
                        )
                        return result
        except Exception as _stale_err:
            print(
                f"[v127 naked-sweep] pusher-stale check failed (continuing): "
                f"{_stale_err}", flush=True,
            )
        # ─────────── /PATCH E ───────────

        # ─────────── v19.34.163 PATCH F — Tier-mismatch blind-guard ───────────
        # When BOT_ORDER_PATH=direct, orders are placed via `ib_direct`
        # (clientId=11 on DGX). The Windows pusher's `openTrades()`
        # snapshot uses its OWN clientId and — without
        # `reqAutoOpenOrders(True)` on the pusher side — IB Gateway
        # only returns orders belonging to the requesting client.
        # Result: the pusher snapshot is structurally BLIND to every
        # bracket we place via ib_direct. The 7-day audit (2026-05-26)
        # showed 928 naked_sweep_reissue events, 97% triggered by
        # self_cascade — i.e. the sweep saw its own just-placed stop
        # missing from a blind snapshot and reissued forever.
        # Worst offenders: COR (144 reissues / 3h), UAL (101 / 4.5h).
        #
        # Fix: if Tier 1 (ib_direct) fell through and we landed on
        # Tier 3 (pusher_orders_snapshot) while running direct mode,
        # SKIP the entire sweep. We lose naked detection for one
        # cycle (~60s) but we don't generate ghost OCA pairs at IB.
        # The proper fix is v19.34.164 (persistent ib_direct or
        # pusher reqAutoOpenOrders); this guard stops the bleed
        # until then.
        try:
            _order_path = (os.environ.get("BOT_ORDER_PATH", "pusher")
                           or "pusher").strip().lower()
            if (_order_path == "direct"
                    and (source_info or {}).get("tier") == "pusher_orders_snapshot"):
                result["skipped_reason"] = "tier3_blind_to_ib_direct_orders"
                result["source_tier"] = "pusher_orders_snapshot"
                result["order_path"] = _order_path
                print(
                    "[v19.34.163 naked-sweep] SKIP — BOT_ORDER_PATH=direct "
                    "but resolver fell through to pusher_orders_snapshot "
                    "(ib_direct disconnected). Pusher snapshot cannot see "
                    "ib_direct's orders → would trigger false-naked cascade. "
                    "Re-arm ib_direct connection to restore detection.",
                    flush=True,
                )
                return result
        except Exception as _tier_err:
            print(
                f"[v19.34.163 naked-sweep] tier-mismatch guard check failed "
                f"(continuing): {_tier_err}", flush=True,
            )
        # ─────────── /PATCH F ───────────

        # Skip if executor is in non-LIVE mode (simulator/paper has no
        # actual IB orders, though pusher-mode is also "LIVE").
        mode_str = (
            getattr(executor, "mode", None)
            or getattr(executor, "_mode", None)
            or "LIVE"
        )
        try:
            mode_str = getattr(mode_str, "value", str(mode_str)).upper()
        except Exception:
            mode_str = str(mode_str).upper()
        if mode_str != "LIVE":
            result["skipped_reason"] = f"non_live_mode:{mode_str}"
            return result

        # 1) Build set of live order_ids from the resolved snapshot.
        #    `_fetch_ib_open_orders` normalizes to `ib_order_id` /
        #    `perm_id`; pusher payload also exposes `order_id`. Index
        #    on every available identifier so any of them matches.
        live_order_ids = set()
        for o in (ib_orders or []):
            for k in ("ib_order_id", "order_id", "orderId", "perm_id", "id"):
                v = o.get(k) if isinstance(o, dict) else None
                if v is not None:
                    live_order_ids.add(str(v))

        # ── M0c (2026-06-12) — empty order-snapshot guard ───────────────────
        # An EMPTY open-orders read while the bot tracks real IB stop ids is
        # far more likely a degraded/unprimed snapshot (backend just
        # restarted; ib_direct freshly reconnected; pusher feed wiped) than
        # every bracket genuinely vanishing at once. Mass-reissuing on a
        # blank snapshot is the bracket-stacking / ladder-clobbering failure
        # mode — skip the cycle instead (detection resumes next tick).
        if not live_order_ids:
            _tracked_stop_count = 0
            for _gt in self._open_trades.values():
                _gsid = getattr(_gt, "stop_order_id", None)
                _gsid_str = str(_gsid) if _gsid is not None else None
                if _gsid_str and not (
                    _gsid_str.startswith("SIM-")
                    or _gsid_str.startswith("ADOPT-STOP-")
                ):
                    _tracked_stop_count += 1
            if _tracked_stop_count > 0:
                result["skipped_reason"] = "empty_order_snapshot_suspect"
                print(
                    f"[M0c naked-sweep] SKIP — order snapshot is EMPTY "
                    f"(tier={source_info.get('tier')}) but bot tracks "
                    f"{_tracked_stop_count} live stop id(s). Refusing "
                    f"mass-reissue on a blank snapshot.",
                    flush=True,
                )
                return result

        # ── v19.34.285 — flip-guard: signed live IB positions ──────────────
        # Build a SIGNED per-symbol IB net-position map so a naked reissue can
        # be refused when IB is flat/opposite for the symbol (would flip the
        # position naked). An empty/unreadable snapshot => unverifiable, and the
        # per-trade guard then SKIPS reissue for that cycle (never reissues an
        # exit it can't confirm). Same source the reconciler uses.
        ib_signed_by_sym: Dict[str, float] = {}
        ib_positions_available = False
        try:
            from services.orphan_gtc_reconciler import _fetch_ib_positions_async
            _ibpos, _ibpos_src = await _fetch_ib_positions_async()
            if (_ibpos_src or {}).get("ok") and _ibpos:
                ib_positions_available = True
                for _p in _ibpos:
                    _psym = (_p.get("symbol") or "").upper()
                    if not _psym:
                        continue
                    try:
                        ib_signed_by_sym[_psym] = (
                            ib_signed_by_sym.get(_psym, 0.0)
                            + float(_p.get("position") or 0)
                        )
                    except (TypeError, ValueError):
                        pass
            result["flip_guard_positions_available"] = ib_positions_available
            result["flip_guard_positions_source"] = (_ibpos_src or {}).get("tier")
        except Exception as _fgerr:
            result["flip_guard_positions_available"] = False
            print(
                f"[v19.34.285 flip-guard] IB position fetch failed (continuing "
                f"as unverifiable): {_fgerr}", flush=True,
            )

        # 2) Walk every open trade with shares > 0.
        from services.bracket_reissue_service import _persist_lifecycle_event
        # 2026-02-13 (v19.34.143) — emergency hard %-stop fallback for
        # reconciled orphans whose `stop_price` / `target_prices` got
        # nuked or were never set. Without this, `attach_oca_stop_target`
        # bails with "missing stop_price or target_price" and the
        # position stays NAKED forever (TE/EGO/KTOS scenario).
        # The 2% / 3% defaults mirror `reconcile_orphan_positions`.
        EMERGENCY_STOP_PCT = 2.0
        EMERGENCY_RR = 1.5

        # v19.34.73 — Sibling-canonical guard. Pre-fix: when two trades
        # for the same (symbol, direction) co-existed in `_open_trades`
        # (e.g., real bot_fired `82f0686f` 134sh + stale orphan-adopted
        # `b415ed5f` 44sh from a prior session), the naked-sweep
        # reissued brackets for BOTH every 60s. IB rejected the smaller
        # phantom's bracket with Error 200 (stale contract / no
        # secdef), and the next sweep saw it naked again → infinite
        # error-200 loop (observed 35+ cycles for ADI on 2026-05-21).
        # Fix: build a sibling map, score each canonical (bot_fired +
        # remaining_shares), and skip naked-reissue for any trade
        # that's NOT the highest-scored sibling. The losing sibling
        # gets marked for purge by the boot-time phantom cleaner.
        _sibling_map: Dict[tuple, list] = {}
        for _stid, _strade in self._open_trades.items():
            _ssym = (getattr(_strade, "symbol", "") or "").upper()
            _sdir = getattr(_strade, "direction", None)
            _sdv = getattr(_sdir, "value", str(_sdir) if _sdir else "long").lower()
            _sibling_map.setdefault((_ssym, _sdv), []).append(_stid)

        def _score_sibling(_t) -> int:
            """Higher score = healthier canonical. bot_fired wins."""
            _eb = (getattr(_t, "entered_by", "") or "").lower()
            _bonus = 10000 if "bot_fired" in _eb else 0
            _rs = int(abs(getattr(_t, "remaining_shares", 0) or 0))
            return _bonus + _rs

        for tid, trade in list(self._open_trades.items()):
            try:
                rs = int(abs(getattr(trade, "remaining_shares", 0) or 0))
                if rs <= 0:
                    continue
                result["checked"] += 1

                # ── v19.34.163 PATCH G — Recent-reissue cooldown ─────
                # Even when Tier 1 (ib_direct) is healthy, IB's
                # EWrapper.openOrder callback fires AFTER the
                # placeOrder return. There's a ~1-5s window where
                # `_ib.trades()` may not yet reflect the just-placed
                # STP. If the next 60s sweep tick lands in that
                # window the trade reads naked again. Suppress
                # re-detection for NAKED_REISSUE_COOLDOWN_S (default
                # 90s) after the last successful attach so we never
                # double-fire on async-callback latency.
                try:
                    _last_attach = getattr(trade, "last_bracket_attach_at", None)
                    if _last_attach:
                        _last_dt = datetime.fromisoformat(
                            str(_last_attach).replace("Z", "+00:00")
                        )
                        _age_s = (datetime.now(timezone.utc) - _last_dt).total_seconds()
                        _cooldown_s = float(
                            os.environ.get("NAKED_REISSUE_COOLDOWN_S", 90.0)
                        )
                        if 0 <= _age_s < _cooldown_s:
                            result.setdefault("cooldown_skips", 0)
                            result["cooldown_skips"] += 1
                            continue
                except Exception as _cooldown_err:
                    # Cooldown failure must NEVER suppress naked
                    # detection — fall through to the original path.
                    print(
                        f"[v19.34.163 naked-sweep] cooldown check failed "
                        f"for {tid} (continuing to naked detection): "
                        f"{_cooldown_err}", flush=True,
                    )
                # ─────────── /PATCH G ───────────

                # v19.34.73 — Skip if a healthier sibling owns
                # (symbol, direction). This trade is a phantom.
                _g_sym = (getattr(trade, "symbol", "") or "").upper()
                _g_dir = getattr(trade, "direction", None)
                _g_dv = getattr(_g_dir, "value", str(_g_dir) if _g_dir else "long").lower()
                _sibs = _sibling_map.get((_g_sym, _g_dv), [])
                if len(_sibs) > 1:
                    _scored = []
                    for _sib_tid in _sibs:
                        _sib_t = self._open_trades.get(_sib_tid)
                        if _sib_t is None:
                            continue
                        _scored.append((_score_sibling(_sib_t), _sib_tid))
                    _scored.sort(reverse=True)
                    _winner = _scored[0][1] if _scored else None
                    if _winner is not None and _winner != tid:
                        print(
                            f"[v19.34.73 naked-sweep] {_g_sym} {tid}: "
                            f"SKIP reissue — healthier sibling {_winner} "
                            f"owns ({_g_sym}, {_g_dv}). This trade is a "
                            f"phantom and will be cleaned up by the boot "
                            f"phantom-purge pass.",
                            flush=True,
                        )
                        result.setdefault("skipped_phantom_siblings", []).append(tid)
                        continue

                # ── M0d (2026-06-12) — ladder coverage audit + top-up ────
                # Runs for every M0-laddered trade BEFORE the binary naked
                # check: leg 1's live stop used to mask destroyed legs 2..n
                # (CZR 175sh with only 70 protected). Audit actual covered
                # qty; if part of the position is uncovered, append ONE
                # top-up OCA leg at the surviving legs' stop price. Flip-
                # guard verified: top-up only when IB confirms same-side
                # shares, clamped so total protection never exceeds the
                # live position.
                if ((getattr(trade, "scale_out_config", None) or {}).get("m0_legs")):
                    _cov, _live_stop_px, _lost_n = _m0_coverage_scan(
                        trade, live_order_ids)
                    if _cov > 0:
                        _shortfall = rs - _cov
                        _sgn_m0 = ib_signed_by_sym.get(_g_sym)
                        _same_side_m0 = 0
                        if _sgn_m0 is not None:
                            if _g_dv == "long" and _sgn_m0 > 0:
                                _same_side_m0 = int(_sgn_m0)
                            elif _g_dv == "short" and _sgn_m0 < 0:
                                _same_side_m0 = int(abs(_sgn_m0))
                        if _shortfall >= 1:
                            result.setdefault("m0_shortfall_found", 0)
                            result["m0_shortfall_found"] += 1
                            if not ib_positions_available or _same_side_m0 <= _cov:
                                print(
                                    f"[M0d naked-sweep] {_g_sym} {tid} ladder "
                                    f"shortfall {_shortfall}sh (covered {_cov}/"
                                    f"{rs}) but IB side unverified/flat "
                                    f"(avail={ib_positions_available} "
                                    f"same_side={_same_side_m0}) — SKIP top-up "
                                    f"this cycle.", flush=True,
                                )
                            else:
                                _topup_qty = min(_shortfall, _same_side_m0 - _cov)
                                _spx_m0 = _live_stop_px or float(
                                    getattr(trade, "stop_price", 0) or 0)
                                _tpx_m0 = _m0_furthest_lost_target(trade)
                                if _topup_qty >= 1 and _spx_m0 > 0:
                                    try:
                                        from services.ib_direct_service import (
                                            get_ib_direct_service,
                                        )
                                        _topup_res = await (
                                            get_ib_direct_service().m0_topup_leg(
                                                trade, qty=_topup_qty,
                                                stop_px=_spx_m0,
                                                target_px=_tpx_m0, tif="DAY",
                                            )
                                        )
                                    except Exception as _tue:
                                        _topup_res = {
                                            "success": False,
                                            "error": f"{type(_tue).__name__}:{_tue}",
                                        }
                                    if _topup_res.get("success"):
                                        result.setdefault("m0_topup_placed", 0)
                                        result["m0_topup_placed"] += 1
                                        try:
                                            trade.last_bracket_attach_at = (
                                                datetime.now(timezone.utc).isoformat()
                                            )
                                        except Exception:
                                            pass
                                        print(
                                            f"[M0d naked-sweep] {_g_sym} {tid} "
                                            f"TOP-UP placed: {_topup_qty}sh "
                                            f"stop@{_spx_m0} "
                                            f"(was covered {_cov}/{rs}, "
                                            f"{_lost_n} leg(s) lost).",
                                            flush=True,
                                        )
                                    else:
                                        result.setdefault("m0_topup_failed", 0)
                                        result["m0_topup_failed"] += 1
                                        print(
                                            f"[M0d naked-sweep] {_g_sym} {tid} "
                                            f"top-up FAILED: "
                                            f"{_topup_res.get('error')} — will "
                                            f"retry next cycle.", flush=True,
                                        )
                        # ≥1 live ladder leg → never fall through to the
                        # binary naked check (leg-1 stop may legitimately
                        # be gone after its TP filled).
                        continue
                    # covered == 0 → whole ladder dead (legs already marked
                    # lost by the scan) — fall through to the standard
                    # naked-reissue path below.

                stop_id = getattr(trade, "stop_order_id", None)
                stop_id_str = str(stop_id) if stop_id is not None else None
                # v19.34.143 — Treat simulated stop IDs (SIM-STP-*,
                # ADOPT-STOP-* without a real IB ack) as NAKED. These
                # appear when `attach_oca_stop_target` ran while the
                # pusher was offline; the trade looks bracketed in the
                # bot but isn't protected at IB.
                is_simulated = bool(
                    stop_id_str and (
                        stop_id_str.startswith("SIM-")
                        or stop_id_str.startswith("ADOPT-STOP-")
                    )
                )
                is_naked = (
                    stop_id_str is None
                    or is_simulated
                    or (stop_id_str not in live_order_ids)
                )
                if not is_naked:
                    continue

                # ── M0c (2026-06-12) — ladder-aware naked check ──────────
                # For M0 trades the primary stop_order_id is only leg 1's
                # stop; after a leg fill OCA legitimately cancels it. The
                # trade is protected as long as ANY working leg stop is
                # still live at IB.
                _m0_stop_ids = _m0_working_leg_stop_ids(trade)
                if _m0_stop_ids and any(_s in live_order_ids for _s in _m0_stop_ids):
                    continue
                if _m0_stop_ids:
                    # Ladder tracked but NO leg stop live → legs were lost
                    # (cancelled externally). Mark them so the M0 manager
                    # stops acting on dead ids; the reissue below
                    # re-protects the position (possibly with a new ladder).
                    try:
                        for _leg in (trade.scale_out_config or {}).get("m0_legs", []):
                            if _leg.get("status") == "working":
                                _leg["status"] = "lost"
                    except Exception:
                        pass

                result["naked_found"] += 1
                sym = getattr(trade, "symbol", "?")
                print(
                    f"[v127 naked-sweep] {sym} {tid} NAKED — "
                    f"stop_id={stop_id_str!r} simulated={is_simulated} "
                    f"not in {len(live_order_ids)} live orders. "
                    f"Emergency re-issue.",
                    flush=True,
                )

                # ── v19.34.285 — flip-guard (direction-aware) ──────────────
                # Before reissuing the protective EXIT bracket, verify IB's
                # SIGNED position. If IB is flat/opposite (or unverifiable),
                # reissuing would oversell/overbuy and flip the position naked.
                _dir_obj285 = getattr(trade, "direction", None)
                _dir_v285 = getattr(
                    _dir_obj285, "value",
                    str(_dir_obj285) if _dir_obj285 else "long",
                ).lower()
                _ib_signed285 = (
                    ib_signed_by_sym.get(sym.upper())
                    if ib_positions_available else None
                )
                _decision285 = _naked_sweep_flip_decision(
                    _dir_v285, rs, _ib_signed285, ib_positions_available,
                )
                if _decision285 != "proceed":
                    if _decision285 == "skip_unverifiable":
                        result.setdefault("flip_guard_skipped_unverifiable", 0)
                        result["flip_guard_skipped_unverifiable"] += 1
                        _phase285 = "naked_sweep_flip_guard_skip"
                        _reason285 = "ib_position_unverifiable"
                        print(
                            f"[v19.34.285 flip-guard] {sym} {tid} SKIP reissue — "
                            f"IB position data unavailable this cycle; refusing "
                            f"unverifiable exit reissue.", flush=True,
                        )
                    else:  # halt_flat_or_opposite
                        result.setdefault("flip_guard_halts", 0)
                        result["flip_guard_halts"] += 1
                        _phase285 = "naked_sweep_halt_no_ib_position"
                        _reason285 = "ib_flat_or_opposite"
                        try:
                            trade.desync_flagged = True
                            trade.desync_reason = "ib_flat_or_opposite_v285"
                            trade.desync_detected_at = (
                                datetime.now(timezone.utc).isoformat()
                            )
                        except Exception:
                            pass
                        print(
                            f"[v19.34.285 flip-guard] {sym} {tid} HARD-HALT "
                            f"reissue — bot thinks {_dir_v285} {rs}sh but IB net="
                            f"{(_ib_signed285 if _ib_signed285 is not None else 0):+.0f}. "
                            f"Reissue would flip naked. Flagged desync for "
                            f"reconciler.", flush=True,
                        )
                    try:
                        await _persist_lifecycle_event(
                            bot=self,
                            event={
                                "phase": _phase285,
                                "success": False,
                                "trade_id": tid,
                                "symbol": sym,
                                "reason": _reason285,
                                "bot_remaining_shares": rs,
                                "ib_position_qty": _ib_signed285,
                                "direction": _dir_v285,
                            },
                        )
                    except Exception as _ple285:
                        print(
                            f"[v19.34.285 flip-guard] lifecycle persist failed: "
                            f"{_ple285}", flush=True,
                        )
                    continue
                # ───────────────────────────────────────────────────────────

                # v19.34.143 — emergency hard %-stop fallback. Before
                # delegating to attach_oca_stop_target, make sure
                # stop_price + target_prices are sane. If either is
                # missing or zero, synthesize a 2% hard stop / 3% target
                # off the entry price so the attach call can succeed
                # instead of bouncing on "missing stop_price".
                emergency_synth = None
                try:
                    entry = float(
                        getattr(trade, "fill_price", None)
                        or getattr(trade, "entry_price", None)
                        or 0
                    )
                    cur_stop = float(getattr(trade, "stop_price", 0) or 0)
                    tgt_list = getattr(trade, "target_prices", None) or []
                    cur_tgt = (
                        float(tgt_list[0])
                        if tgt_list and tgt_list[0] is not None
                        else 0
                    )
                    direction_val = getattr(trade, "direction", None)
                    direction_str = (
                        getattr(direction_val, "value", str(direction_val))
                        if direction_val is not None
                        else "long"
                    ).lower()
                    if entry > 0 and (cur_stop <= 0 or cur_tgt <= 0):
                        stop_dist = entry * (EMERGENCY_STOP_PCT / 100.0)
                        target_dist = stop_dist * EMERGENCY_RR
                        if direction_str == "long":
                            new_stop = entry - stop_dist
                            new_tgt = entry + target_dist
                        else:
                            new_stop = entry + stop_dist
                            new_tgt = entry - target_dist
                        trade.stop_price = round(new_stop, 4)
                        trade.target_prices = [round(new_tgt, 4)]
                        emergency_synth = {
                            "entry": entry,
                            "stop_price": trade.stop_price,
                            "target_price": trade.target_prices[0],
                            "stop_pct": EMERGENCY_STOP_PCT,
                            "rr": EMERGENCY_RR,
                            "reason": "missing_stop_or_target",
                        }
                        print(
                            f"[v127 naked-sweep] {sym} {tid} synthesized "
                            f"emergency {EMERGENCY_STOP_PCT}% stop "
                            f"@ ${trade.stop_price:.2f} / target "
                            f"@ ${trade.target_prices[0]:.2f} "
                            f"(entry=${entry:.2f}) before re-issue. "
                            f"detail={emergency_synth}",
                            flush=True,
                        )
                except Exception as _synth_err:
                    print(
                        f"[v127 naked-sweep] {sym} {tid} emergency stop "
                        f"synthesis failed: {_synth_err}",
                        flush=True,
                    )

                # 3) Emergency re-issue via attach_oca_stop_target.
                oca_result = None
                try:
                    if hasattr(executor, "attach_oca_stop_target"):
                        oca_result = await executor.attach_oca_stop_target(trade)
                except Exception as e:
                    oca_result = {"success": False, "error": f"{type(e).__name__}:{e}"}

                ok = bool(oca_result and oca_result.get("success"))
                if ok:
                    trade.stop_order_id = oca_result.get("stop_order_id")
                    tgt_id = oca_result.get("target_order_id")
                    if tgt_id is not None:
                        trade.target_order_id = tgt_id
                        # v19.34.30 Patch A: REPLACE not append.
                        # M0c — unless the reissue placed a NEW M0 ladder:
                        # _m0_place_oca_ladder already stamped the FULL leg
                        # id list on trade.target_order_ids; clobbering it
                        # to [tgt_id] would blind every cancel path (and
                        # the orphan classifier) to legs 2..n.
                        try:
                            if not (oca_result or {}).get("m0_ladder"):
                                trade.target_order_ids = [tgt_id]
                        except Exception:
                            pass
                    trade.oca_group = oca_result.get("oca_group")
                    # ── v19.34.163 PATCH H — Cumulative telemetry ────
                    # Three monotonic fields, NEVER reset by cleanup
                    # sweeps. Drive the v90 P0 churn audit + future
                    # `bracket_completion_telemetry` alert job.
                    try:
                        trade.bracket_attach_count = int(
                            getattr(trade, "bracket_attach_count", 0) or 0
                        ) + 1
                        # Only flip target_ever_attached when we
                        # genuinely placed a target (tgt_id present).
                        # `partial=True` (stop-only, no TP) intentionally
                        # does NOT flip this — distinguishes "TP placed
                        # at least once" from "stop-only forever".
                        if tgt_id is not None and not getattr(
                            trade, "target_ever_attached", False
                        ):
                            trade.target_ever_attached = True
                        trade.last_bracket_attach_at = (
                            datetime.now(timezone.utc).isoformat()
                        )
                    except Exception as _telem_err:
                        # Telemetry MUST NOT block the trade path.
                        print(
                            f"[v19.34.163 naked-sweep] telemetry update "
                            f"failed for {tid} (continuing): {_telem_err}",
                            flush=True,
                        )
                    # ─────────── /PATCH H ───────────
                    # Persist new order IDs.
                    try:
                        save_fn = getattr(self, "_save_trade", None) or getattr(self, "_persist_trade", None)
                        if save_fn:
                            r = save_fn(trade)
                            if asyncio.iscoroutine(r):
                                await r
                    except Exception:
                        pass
                    result["reissued"] += 1
                else:
                    result["reissue_failed"] += 1
                    print(
                        f"[v127 naked-sweep] {sym} {tid} REISSUE FAILED — "
                        f"{(oca_result or {}).get('error', 'unknown')}. "
                        f"Position remains NAKED.",
                        flush=True,
                    )

                # 4) Persist lifecycle event so /diagnostic/bracket-lifecycle
                #    surfaces this — schema-compatible with consolidator events.
                try:
                    await _persist_lifecycle_event(
                        bot=self,
                        event={
                            "phase": "naked_sweep_reissue",
                            "success": ok,
                            "trade_id": tid,
                            "symbol": sym,
                            "reason": "naked_position_detected",
                            "previous_stop_order_id": stop_id_str,
                            "new_stop_order_id": (
                                str(oca_result.get("stop_order_id"))
                                if ok else None
                            ),
                            "oca_group": (oca_result or {}).get("oca_group"),
                            "remaining_shares": rs,
                            "ib_live_order_count": len(live_order_ids),
                            "error": None if ok else (oca_result or {}).get("error"),
                        },
                    )
                except Exception as _persist_err:
                    print(
                        f"[v127 naked-sweep] lifecycle persist failed: "
                        f"{_persist_err}",
                        flush=True,
                    )
            except Exception as _iter_err:
                print(
                    f"[v127 naked-sweep] per-trade iteration crashed for "
                    f"{tid}: {_iter_err}",
                    flush=True,
                )
                continue

        if result["naked_found"] > 0:
            print(
                f"[v127 naked-sweep] complete — checked={result['checked']} "
                f"naked={result['naked_found']} reissued={result['reissued']} "
                f"failed={result['reissue_failed']}",
                flush=True,
            )
        return result



    
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
