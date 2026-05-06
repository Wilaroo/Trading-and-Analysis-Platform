"""
SMB Unified Scoring Integration

Enhances the existing scoring_engine.py with:
1. SMB 5-Variable scoring (mapped from existing 11-point checklist)
2. Enhanced Tape Reading with Level 2 "Box" metrics
3. Trade Style recommendations (M2M/T2H/A+)
4. Earnings Catalyst scoring (-10 to +10)
5. Tiered Entry recommendations
6. Reasons2Sell framework
7. AI Coaching integration hooks

This module bridges the existing scoring system with SMB Capital methodology,
maintaining backwards compatibility while adding professional trading features.
"""

from dataclasses import dataclass, field
from typing import Dict, List
from enum import Enum
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Import SMB components
try:
    from services.smb_integration import (
        TradeStyle, SetupDirection, SetupCategory,
        SMBVariableScore, calculate_smb_score,
        get_setup_config, get_default_trade_style, get_style_targets,
        SETUP_REGISTRY, TRADE_STYLE_TARGETS
    )
    from services.earnings_scoring_service import (
        EarningsData, EarningsScore, GuidanceDirection,
        calculate_earnings_score, get_score_description, TradingApproach
    )
    SMB_AVAILABLE = True
except ImportError as e:
    logger.warning(f"SMB Integration modules not available: {e}")
    SMB_AVAILABLE = False


# ==================== ENHANCED TAPE READING (Level 2 Box) ====================

class TapeSignalStrength(Enum):
    """Tape reading signal strength"""
    VERY_STRONG = "very_strong"    # Score 9-10
    STRONG = "strong"              # Score 7-8
    MODERATE = "moderate"          # Score 5-6
    WEAK = "weak"                  # Score 3-4
    VERY_WEAK = "very_weak"        # Score 1-2


@dataclass
class Level2BoxMetrics:
    """
    SMB Capital Level 2 "Box" Configuration Metrics
    
    The Box provides real-time tape reading signals:
    - Price/Bid/Ask analysis
    - Velocity of prints
    - Size at levels
    - Absorption/Stuffing detection
    """
    symbol: str
    
    # Level 1 (Summary)
    last_price: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    spread: float = 0.0
    spread_pct: float = 0.0
    
    # Volume metrics
    current_volume: int = 0
    avg_volume: int = 0
    rvol: float = 1.0
    
    # Velocity (prints per time period)
    tape_velocity: float = 0.0          # Trades per minute
    velocity_trend: str = "stable"      # "accelerating", "stable", "decelerating"
    
    # Size analysis
    bid_size_total: int = 0
    ask_size_total: int = 0
    bid_ask_imbalance: float = 0.0      # Positive = more bids, negative = more asks
    large_prints_count: int = 0         # Prints > 10k shares
    
    # SMB Tape Signals
    hidden_seller_detected: bool = False
    hidden_buyer_detected: bool = False
    aggressive_buyer: bool = False      # Hitting the ask consistently
    aggressive_seller: bool = False     # Hitting the bid consistently
    absorption_at_level: bool = False   # Large orders being absorbed
    stuffed_pattern: bool = False       # Failed breakout, stuffed by seller
    re_bid_signal: bool = False         # Price broke support but immediately re-bid
    re_offer_signal: bool = False       # Price broke resistance but immediately re-offered
    
    # Momentum
    price_momentum: str = "neutral"     # "strong_up", "up", "neutral", "down", "strong_down"
    momentum_vs_volume: str = "confirming"  # "confirming", "diverging", "neutral"
    
    # Composite tape score
    tape_score: int = 5                 # 1-10 (matches SMB's scoring)
    tape_signal_strength: str = "moderate"
    tape_bias: str = "neutral"          # "bullish", "bearish", "neutral"
    
    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "level1": {
                "last_price": self.last_price,
                "bid": self.bid,
                "ask": self.ask,
                "spread": self.spread,
                "spread_pct": self.spread_pct
            },
            "volume": {
                "current": self.current_volume,
                "average": self.avg_volume,
                "rvol": self.rvol
            },
            "velocity": {
                "trades_per_min": self.tape_velocity,
                "trend": self.velocity_trend
            },
            "size": {
                "bid_total": self.bid_size_total,
                "ask_total": self.ask_size_total,
                "imbalance": self.bid_ask_imbalance,
                "large_prints": self.large_prints_count
            },
            "signals": {
                "hidden_seller": self.hidden_seller_detected,
                "hidden_buyer": self.hidden_buyer_detected,
                "aggressive_buyer": self.aggressive_buyer,
                "aggressive_seller": self.aggressive_seller,
                "absorption": self.absorption_at_level,
                "stuffed": self.stuffed_pattern,
                "re_bid": self.re_bid_signal,
                "re_offer": self.re_offer_signal
            },
            "momentum": {
                "direction": self.price_momentum,
                "vs_volume": self.momentum_vs_volume
            },
            "tape_score": self.tape_score,
            "signal_strength": self.tape_signal_strength,
            "bias": self.tape_bias
        }


def calculate_tape_score(metrics: Level2BoxMetrics) -> Level2BoxMetrics:
    """
    Calculate comprehensive tape score (1-10) from Level 2 Box metrics.
    Uses SMB Capital's tape reading methodology.
    """
    score = 5  # Start neutral
    reasons = []
    
    # 1. Spread analysis (-2 to +2)
    if metrics.spread_pct <= 0.05:  # Very tight
        score += 2
        reasons.append("Tight spread (institutional interest)")
    elif metrics.spread_pct <= 0.15:  # Normal
        score += 1
    elif metrics.spread_pct >= 0.5:  # Very wide
        score -= 2
        reasons.append("Wide spread warning")
    
    # 2. Bid/Ask imbalance (-2 to +2)
    if metrics.bid_ask_imbalance > 0.3:  # Heavy bids
        score += 2
        reasons.append("Heavy bid stacking")
    elif metrics.bid_ask_imbalance < -0.3:  # Heavy asks
        score -= 2
        reasons.append("Heavy ask stacking")
    
    # 3. Aggressive activity (-1 to +1)
    if metrics.aggressive_buyer:
        score += 1
        reasons.append("Aggressive buying at ask")
    if metrics.aggressive_seller:
        score -= 1
        reasons.append("Aggressive selling at bid")
    
    # 4. SMB Signals (-2 to +2)
    if metrics.hidden_buyer_detected:
        score += 2
        reasons.append("Hidden buyer detected")
    if metrics.hidden_seller_detected:
        score -= 2
        reasons.append("Hidden seller detected")
    
    if metrics.re_bid_signal:
        score += 2
        reasons.append("Re-bid signal (buyers defending)")
    if metrics.re_offer_signal:
        score -= 2
        reasons.append("Re-offer signal (sellers defending)")
    
    if metrics.stuffed_pattern:
        score -= 2
        reasons.append("Stuffed pattern (failed breakout)")
    
    if metrics.absorption_at_level:
        score += 1
        reasons.append("Absorption at key level")
    
    # 5. Volume/Velocity bonus
    if metrics.rvol >= 3.0:
        score += 1
        reasons.append(f"High RVOL: {metrics.rvol:.1f}x")
    
    if metrics.velocity_trend == "accelerating":
        score += 1
    elif metrics.velocity_trend == "decelerating":
        score -= 1
    
    # Clamp to 1-10
    score = max(1, min(10, score))
    metrics.tape_score = score
    
    # Determine strength
    if score >= 9:
        metrics.tape_signal_strength = "very_strong"
    elif score >= 7:
        metrics.tape_signal_strength = "strong"
    elif score >= 5:
        metrics.tape_signal_strength = "moderate"
    elif score >= 3:
        metrics.tape_signal_strength = "weak"
    else:
        metrics.tape_signal_strength = "very_weak"
    
    # Determine bias
    if score >= 7:
        metrics.tape_bias = "bullish"
    elif score <= 3:
        metrics.tape_bias = "bearish"
    else:
        metrics.tape_bias = "neutral"
    
    return metrics


def analyze_tape_from_quote_data(
    symbol: str,
    quote_data: Dict,
    historical_trades: List[Dict] = None
) -> Level2BoxMetrics:
    """
    Create Level 2 Box metrics from available quote data.
    Works with Alpaca/IB quote data.
    """
    metrics = Level2BoxMetrics(symbol=symbol)
    
    # Level 1 data
    metrics.last_price = quote_data.get("price", quote_data.get("last", 0))
    metrics.bid = quote_data.get("bid", 0)
    metrics.ask = quote_data.get("ask", 0)
    
    if metrics.bid > 0 and metrics.ask > 0:
        metrics.spread = metrics.ask - metrics.bid
        metrics.spread_pct = (metrics.spread / metrics.last_price * 100) if metrics.last_price > 0 else 0
    
    # Volume data
    metrics.current_volume = quote_data.get("volume", 0)
    metrics.avg_volume = quote_data.get("avg_volume", quote_data.get("average_volume", 0))
    
    if metrics.avg_volume > 0:
        metrics.rvol = metrics.current_volume / metrics.avg_volume
    
    # Size data
    metrics.bid_size_total = quote_data.get("bid_size", quote_data.get("bidsize", 0)) * 100
    metrics.ask_size_total = quote_data.get("ask_size", quote_data.get("asksize", 0)) * 100
    
    if metrics.bid_size_total + metrics.ask_size_total > 0:
        metrics.bid_ask_imbalance = (metrics.bid_size_total - metrics.ask_size_total) / (metrics.bid_size_total + metrics.ask_size_total)
    
    # Momentum from price change
    change_pct = quote_data.get("change_percent", quote_data.get("changePercent", 0))
    if change_pct > 2:
        metrics.price_momentum = "strong_up"
        metrics.aggressive_buyer = True
    elif change_pct > 0.5:
        metrics.price_momentum = "up"
    elif change_pct < -2:
        metrics.price_momentum = "strong_down"
        metrics.aggressive_seller = True
    elif change_pct < -0.5:
        metrics.price_momentum = "down"
    else:
        metrics.price_momentum = "neutral"
    
    # Analyze historical trades if available
    if historical_trades:
        # Count trades at ask vs bid
        at_ask = sum(1 for t in historical_trades if t.get("side") == "ask")
        at_bid = sum(1 for t in historical_trades if t.get("side") == "bid")
        
        if at_ask > at_bid * 1.5:
            metrics.aggressive_buyer = True
        elif at_bid > at_ask * 1.5:
            metrics.aggressive_seller = True
        
        # Count large prints
        metrics.large_prints_count = sum(1 for t in historical_trades if t.get("size", 0) >= 10000)
        
        # Calculate velocity (trades per minute)
        if len(historical_trades) >= 2:
            time_span = (historical_trades[-1].get("timestamp", 0) - historical_trades[0].get("timestamp", 0)) / 60
            if time_span > 0:
                metrics.tape_velocity = len(historical_trades) / time_span
    
    # Calculate composite score
    return calculate_tape_score(metrics)


# ==================== REASONS TO SELL FRAMEWORK ====================

class Reason2Sell(Enum):
    """SMB Capital Reasons to Sell / Exit framework"""
    PRICE_TARGET = "price_target"           # Hit predetermined target
    TREND_VIOLATION = "trend_violation"     # Broke 9 EMA or trendline
    THESIS_INVALID = "thesis_invalid"       # Original reason no longer valid
    MARKET_RESISTANCE = "market_resistance" # SPY/QQQ hit major level
    TAPE_EXHAUSTION = "tape_exhaustion"     # Volume/momentum dried up
    PARABOLIC_EXTENSION = "parabolic_extension"  # Too far from value
    BREAKING_NEWS = "breaking_news"         # Fresh negative headline
    END_OF_DAY = "end_of_day"              # Market close approaching
    GIVE_BACK_RULE = "give_back_rule"      # Gave back X% of peak profit
    TIME_STOP = "time_stop"                 # Trade not working in time window


@dataclass
class Reason2SellCheck:
    """Result of checking Reasons2Sell for a position"""
    triggered: bool = False
    reasons: List[str] = field(default_factory=list)
    severity: str = "none"  # "none", "warning", "exit"
    recommended_action: str = "hold"  # "hold", "reduce", "exit"
    details: Dict = field(default_factory=dict)


def check_reasons_to_sell(
    position: Dict,
    current_quote: Dict,
    market_data: Dict = None,
    trade_style: str = "trade_2_hold"
) -> Reason2SellCheck:
    """
    Check all Reasons2Sell for a position.
    
    Args:
        position: Dict with entry_price, target, stop_loss, shares, direction, entry_time
        current_quote: Current market data with price, ema_9, vwap, etc.
        market_data: Market context (SPY trend, regime, etc.)
        trade_style: "move_2_move", "trade_2_hold", or "a_plus"
    
    Returns:
        Reason2SellCheck with triggered reasons and recommendations
    """
    result = Reason2SellCheck()
    
    entry_price = position.get("entry_price", 0)
    target = position.get("target", 0)
    direction = position.get("direction", "long")
    peak_price = position.get("peak_price", entry_price)
    
    current_price = current_quote.get("price", current_quote.get("last", 0))
    ema_9 = current_quote.get("ema_9", 0)
    vwap = current_quote.get("vwap", 0)
    
    if current_price <= 0 or entry_price <= 0:
        return result
    
    is_long = direction.lower() == "long"
    
    # 1. PRICE TARGET REACHED
    if is_long and target > 0 and current_price >= target:
        result.triggered = True
        result.reasons.append(Reason2Sell.PRICE_TARGET.value)
        result.details["target_hit"] = True
    elif not is_long and target > 0 and current_price <= target:
        result.triggered = True
        result.reasons.append(Reason2Sell.PRICE_TARGET.value)
        result.details["target_hit"] = True
    
    # 2. TREND VIOLATION (9 EMA break) - Critical for T2H
    if ema_9 > 0:
        if is_long and current_price < ema_9 * 0.995:  # 0.5% buffer
            result.reasons.append(Reason2Sell.TREND_VIOLATION.value)
            result.details["ema_9_broken"] = True
            if trade_style == "trade_2_hold":
                result.triggered = True
        elif not is_long and current_price > ema_9 * 1.005:
            result.reasons.append(Reason2Sell.TREND_VIOLATION.value)
            result.details["ema_9_broken"] = True
            if trade_style == "trade_2_hold":
                result.triggered = True
    
    # 3. GIVE-BACK RULE (protect profits)
    if peak_price > 0:
        if is_long:
            peak_profit = peak_price - entry_price
            current_profit = current_price - entry_price
        else:
            peak_profit = entry_price - peak_price
            current_profit = entry_price - current_price
        
        if peak_profit > 0:
            give_back_pct = 1 - (current_profit / peak_profit) if peak_profit > 0 else 0
            result.details["give_back_pct"] = give_back_pct * 100
            
            # Different thresholds by style
            threshold = 0.5 if trade_style == "trade_2_hold" else 0.3
            if give_back_pct >= threshold:
                result.reasons.append(Reason2Sell.GIVE_BACK_RULE.value)
                result.triggered = True
    
    # 4. PARABOLIC EXTENSION (too far from value)
    if vwap > 0:
        distance_from_vwap_pct = abs(current_price - vwap) / vwap * 100
        result.details["distance_from_vwap"] = distance_from_vwap_pct
        
        if distance_from_vwap_pct > 5:  # More than 5% from VWAP
            result.reasons.append(Reason2Sell.PARABOLIC_EXTENSION.value)
            # Don't auto-trigger, just warn
    
    # 5. END OF DAY (close approaching)
    now = datetime.now()
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    minutes_to_close = (market_close - now).total_seconds() / 60
    
    if 0 < minutes_to_close <= 15:  # Last 15 minutes
        result.reasons.append(Reason2Sell.END_OF_DAY.value)
        result.details["minutes_to_close"] = minutes_to_close
        # Don't auto-trigger, let user decide
    
    # 6. MARKET RESISTANCE (if we have market data)
    if market_data:
        spy_at_resistance = market_data.get("spy_at_resistance", False)
        if spy_at_resistance and is_long:
            result.reasons.append(Reason2Sell.MARKET_RESISTANCE.value)
            result.details["spy_at_resistance"] = True
    
    # Determine severity and action
    if result.triggered:
        result.severity = "exit"
        result.recommended_action = "exit"
    elif len(result.reasons) >= 2:
        result.severity = "warning"
        result.recommended_action = "reduce"
    elif len(result.reasons) == 1:
        result.severity = "warning"
        result.recommended_action = "hold"
    
    return result


# ==================== TIERED ENTRY TRACKING ====================

@dataclass
class TieredEntry:
    """Track tiered entry positions"""
    symbol: str
    direction: str  # "long" or "short"
    trade_style: str = "trade_2_hold"
    
    # Tier 1 (Feelers - initial position)
    tier_1_shares: int = 0
    tier_1_price: float = 0.0
    tier_1_reason: str = ""
    tier_1_time: str = ""
    
    # Tier 2 (Confirmation - add after tape confirms)
    tier_2_shares: int = 0
    tier_2_price: float = 0.0
    tier_2_reason: str = ""
    tier_2_time: str = ""
    
    # Tier 3 (A+ Size - full conviction)
    tier_3_shares: int = 0
    tier_3_price: float = 0.0
    tier_3_reason: str = ""
    tier_3_time: str = ""
    
    @property
    def total_shares(self) -> int:
        return self.tier_1_shares + self.tier_2_shares + self.tier_3_shares
    
    @property
    def avg_entry_price(self) -> float:
        total_cost = (
            self.tier_1_shares * self.tier_1_price +
            self.tier_2_shares * self.tier_2_price +
            self.tier_3_shares * self.tier_3_price
        )
        return total_cost / self.total_shares if self.total_shares > 0 else 0
    
    @property
    def tiers_filled(self) -> int:
        count = 0
        if self.tier_1_shares > 0:
            count += 1
        if self.tier_2_shares > 0:
            count += 1
        if self.tier_3_shares > 0:
            count += 1
        return count
    
    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "trade_style": self.trade_style,
            "total_shares": self.total_shares,
            "avg_entry": self.avg_entry_price,
            "tiers_filled": self.tiers_filled,
            "tier_1": {
                "shares": self.tier_1_shares,
                "price": self.tier_1_price,
                "reason": self.tier_1_reason
            },
            "tier_2": {
                "shares": self.tier_2_shares,
                "price": self.tier_2_price,
                "reason": self.tier_2_reason
            },
            "tier_3": {
                "shares": self.tier_3_shares,
                "price": self.tier_3_price,
                "reason": self.tier_3_reason
            }
        }


def calculate_tier_sizes(
    risk_per_trade: float,  # e.g., $200
    entry_price: float,
    stop_price: float,
    trade_style: str = "trade_2_hold",
    smb_grade: str = "B"
) -> Dict[str, int]:
    """
    Calculate share counts for each tier based on SMB methodology.
    
    Returns:
        Dict with tier_1_pct, tier_2_pct, tier_3_pct and share counts
    """
    risk_per_share = abs(entry_price - stop_price)
    if risk_per_share <= 0:
        return {"tier_1": 0, "tier_2": 0, "tier_3": 0, "total": 0}
    
    max_shares = int(risk_per_trade / risk_per_share)
    
    # Different allocation by trade style
    if trade_style == "move_2_move":
        # M2M: Larger initial position (capture immediate move)
        allocation = {"tier_1": 0.70, "tier_2": 0.20, "tier_3": 0.10}
    elif trade_style == "a_plus":
        # A+: Aggressive scaling
        allocation = {"tier_1": 0.40, "tier_2": 0.30, "tier_3": 0.30}
    else:  # trade_2_hold
        # T2H: Gradual scaling
        allocation = {"tier_1": 0.30, "tier_2": 0.40, "tier_3": 0.30}
    
    # Adjust for grade (A grades can be more aggressive)
    if smb_grade in ["A+", "A"]:
        allocation["tier_1"] *= 1.2
        allocation["tier_3"] *= 1.2
    elif smb_grade in ["C", "D"]:
        allocation["tier_1"] *= 0.7
        allocation["tier_3"] *= 0.5
    
    return {
        "tier_1": int(max_shares * allocation["tier_1"]),
        "tier_2": int(max_shares * allocation["tier_2"]),
        "tier_3": int(max_shares * allocation["tier_3"]),
        "total": max_shares,
        "risk_per_share": risk_per_share
    }


# ==================== UNIFIED SMB SCORE (Bridge to existing system) ====================

def convert_checklist_to_smb_score(checklist_result: Dict) -> SMBVariableScore:
    """
    Convert existing 11-point SMB checklist to SMB 5-Variable score.
    
    Mapping:
    - Big Picture ← Trend + Relative Strength + Sentiment
    - Intraday Fundamental ← Catalyst
    - Technical Level ← Support/Resistance + Risk Reward + MAs
    - Tape Reading ← Volume Analysis + MTF Alignment
    - Intuition ← Proven Success
    """
    if not SMB_AVAILABLE:
        return None
    
    checklist = checklist_result.get("checklist", {})
    
    score = SMBVariableScore()
    
    # 1. BIG PICTURE (from Trend + RS + Sentiment)
    bp_score = 5
    bp_notes = []
    
    if checklist.get("trend", {}).get("passed"):
        bp_score += 2
        bp_notes.append(f"Clear {checklist['trend'].get('direction', '')} trend")
    
    if checklist.get("relative_strength", {}).get("passed"):
        bp_score += 2
        sector_rank = checklist["relative_strength"].get("sector_rank", 50)
        bp_notes.append(f"RS rank #{sector_rank}")
    
    if checklist.get("sentiment", {}).get("passed"):
        bp_score += 1
        bp_notes.append("Sentiment aligned")
    
    score.big_picture = min(10, bp_score)
    score.big_picture_notes = ", ".join(bp_notes) if bp_notes else "Neutral"
    
    # 2. INTRADAY FUNDAMENTAL (from Catalyst)
    fund_score = 5
    fund_notes = []
    
    if checklist.get("catalyst", {}).get("passed"):
        fund_score += 3
        details = checklist["catalyst"].get("details", [])
        fund_notes.extend(details[:2])
    
    score.intraday_fundamental = min(10, fund_score)
    score.fundamental_notes = ", ".join(fund_notes) if fund_notes else "No major catalyst"
    
    # 3. TECHNICAL LEVEL (from S/R + R:R + MAs)
    tech_score = 5
    tech_notes = []
    
    if checklist.get("support_resistance", {}).get("passed"):
        tech_score += 2
        tech_notes.append("Clear S/R levels")
    
    if checklist.get("risk_reward", {}).get("passed"):
        rr = checklist["risk_reward"].get("ratio", 0)
        tech_score += 2
        tech_notes.append(f"R:R {rr:.1f}:1")
    
    if checklist.get("moving_averages", {}).get("passed"):
        tech_score += 1
        tech_notes.append("MAs aligned")
    
    score.technical_level = min(10, tech_score)
    score.technical_notes = ", ".join(tech_notes) if tech_notes else "Unclear levels"
    
    # 4. TAPE READING (from Volume + MTF)
    tape_score = 5
    tape_notes = []
    
    if checklist.get("volume_analysis", {}).get("passed"):
        rvol = checklist["volume_analysis"].get("rvol", 1)
        tape_score += 2
        tape_notes.append(f"RVOL {rvol:.1f}x")
    
    if checklist.get("mtf_alignment", {}).get("passed"):
        tape_score += 2
        tape_notes.append("MTF confluence")
    
    score.tape_reading = min(10, tape_score)
    score.tape_notes = ", ".join(tape_notes) if tape_notes else "Volume neutral"
    
    # 5. INTUITION (from Proven Success)
    int_score = 5
    int_notes = []
    
    if checklist.get("proven_success", {}).get("passed"):
        matched = checklist["proven_success"].get("matched_count", 0)
        int_score += 3
        int_notes.append(f"Matches {matched} setups")
    
    if checklist.get("exit_strategy", {}).get("passed"):
        int_score += 1
        int_notes.append("Exit plan defined")
    
    score.intuition = min(10, int_score)
    score.intuition_notes = ", ".join(int_notes) if int_notes else "No pattern match"
    
    return score


def get_trade_style_recommendation(
    smb_score: SMBVariableScore,
    setup_type: str,
    tape_metrics: Level2BoxMetrics = None,
    market_regime: str = "neutral"
) -> Dict:
    """
    Get trade style recommendation based on SMB score and context.
    
    Returns:
        Dict with style, target_r, exit_rule, tier_allocation, reasoning
    """
    if not SMB_AVAILABLE:
        return {"style": "move_2_move", "target_r": 1.0}
    
    # Get setup default
    config = get_setup_config(setup_type)
    default_style = config.default_style if config else TradeStyle.MOVE_2_MOVE
    
    # Check for A+ upgrade
    if smb_score and smb_score.is_a_plus:
        style = TradeStyle.A_PLUS
        reasoning = ["A+ score: All variables strong (40+, no var below 7)"]
    elif smb_score and smb_score.total_score >= 35:
        # Strong score but not A+ - consider T2H
        if market_regime in ["momentum", "strong_uptrend", "strong_downtrend"]:
            style = TradeStyle.TRADE_2_HOLD
            reasoning = ["Strong score in trending market"]
        elif tape_metrics and tape_metrics.tape_score >= 7:
            style = TradeStyle.TRADE_2_HOLD
            reasoning = ["Strong tape supports holding"]
        else:
            style = default_style
            reasoning = ["Using setup default"]
    elif smb_score and smb_score.total_score < 25:
        # Weak score - only M2M
        style = TradeStyle.MOVE_2_MOVE
        reasoning = ["Weak SMB score - scalp only"]
    else:
        style = default_style
        reasoning = ["Using setup default"]
    
    # Get targets for style
    targets = get_style_targets(style) if SMB_AVAILABLE else {}
    
    return {
        "style": style.value,
        "target_r": targets.get("target_r", 2.0),
        "max_r": targets.get("max_r", 3.0),
        "exit_rule": targets.get("exit_rule", ""),
        "management": targets.get("management", ""),
        "typical_win_rate": targets.get("typical_win_rate", 0.5),
        "reasoning": reasoning
    }


# ==================== AI COACHING INTEGRATION ====================

def generate_smb_coaching_context(
    symbol: str,
    setup_type: str,
    smb_score: SMBVariableScore,
    tape_metrics: Level2BoxMetrics = None,
    earnings_score: EarningsScore = None,
    trade_style_rec: Dict = None
) -> str:
    """
    Generate SMB-style coaching context for AI assistant.
    
    Returns formatted text that can be injected into AI prompts
    for more intelligent trading recommendations.
    """
    lines = [f"## SMB Analysis for {symbol} ({setup_type})"]
    
    # SMB 5-Variable breakdown
    if smb_score:
        lines.append(f"\n### SMB 5-Variable Score: {smb_score.total_score}/50 ({smb_score.grade})")
        lines.append(f"- Big Picture: {smb_score.big_picture}/10 - {smb_score.big_picture_notes}")
        lines.append(f"- Fundamental: {smb_score.intraday_fundamental}/10 - {smb_score.fundamental_notes}")
        lines.append(f"- Technical: {smb_score.technical_level}/10 - {smb_score.technical_notes}")
        lines.append(f"- Tape: {smb_score.tape_reading}/10 - {smb_score.tape_notes}")
        lines.append(f"- Intuition: {smb_score.intuition}/10 - {smb_score.intuition_notes}")
        
        if smb_score.is_a_plus:
            lines.append("\n**A+ SETUP DETECTED** - All variables strong, consider full size")
    
    # Tape reading
    if tape_metrics:
        lines.append(f"\n### Tape Reading: {tape_metrics.tape_score}/10 ({tape_metrics.tape_bias})")
        signals = []
        if tape_metrics.aggressive_buyer:
            signals.append("Aggressive buying")
        if tape_metrics.aggressive_seller:
            signals.append("Aggressive selling")
        if tape_metrics.re_bid_signal:
            signals.append("Re-bid (buyers defending)")
        if tape_metrics.hidden_seller_detected:
            signals.append("Hidden seller warning")
        if signals:
            lines.append(f"- Signals: {', '.join(signals)}")
    
    # Earnings context
    if earnings_score:
        lines.append(f"\n### Earnings Catalyst: {earnings_score.final_score:+d}")
        lines.append(f"- Approach: {earnings_score.trading_approach.value}")
        lines.append(f"- Suggested: {', '.join(earnings_score.suggested_setups[:3])}")
        if earnings_score.avoid_setups:
            lines.append(f"- Avoid: {', '.join(earnings_score.avoid_setups[:3])}")
    
    # Trade style recommendation
    if trade_style_rec:
        style = trade_style_rec.get("style", "")
        target = trade_style_rec.get("target_r", 2.0)
        lines.append(f"\n### Recommended Style: {style.upper()}")
        lines.append(f"- Target: {target}R")
        lines.append(f"- Exit: {trade_style_rec.get('exit_rule', 'Standard')}")
        if trade_style_rec.get("reasoning"):
            lines.append(f"- Reasoning: {trade_style_rec['reasoning'][0]}")
    
    return "\n".join(lines)


def get_ai_coaching_prompts(
    smb_score: SMBVariableScore,
    trade_style: str,
    current_situation: str = "entry"  # "entry", "in_trade", "exit_consideration"
) -> List[str]:
    """
    Get SMB-style coaching prompts for the AI assistant.
    
    Returns list of coaching points to mention.
    """
    prompts = []
    
    if current_situation == "entry":
        if smb_score.is_a_plus:
            prompts.append("This is an A+ setup - consider full position size with conviction")
        elif smb_score.total_score < 25:
            prompts.append("Weak setup score - consider smaller size or waiting for better confirmation")
        
        if smb_score.tape_reading < 5:
            prompts.append("Tape is not confirming - wait for better order flow before entry")
        
        if trade_style == "trade_2_hold":
            prompts.append("T2H style: Plan to hold until a Reason2Sell triggers, not on noise")
            prompts.append("Consider tiered entry: Start with 30%, add on confirmation")
    
    elif current_situation == "in_trade":
        if trade_style == "move_2_move":
            prompts.append("M2M style: Take profits at first target, don't overstay")
        elif trade_style == "trade_2_hold":
            prompts.append("T2H: Only exit on Reason2Sell (9 EMA break, target hit, thesis invalid)")
            prompts.append("Give the trade room - expect some give-back on the way to target")
    
    elif current_situation == "exit_consideration":
        prompts.append("Check Reasons2Sell: Target hit? Trend broken? Thesis invalid?")
        if trade_style == "trade_2_hold":
            prompts.append("For T2H: Don't exit on minor pullbacks, wait for clear signal")
    
    return prompts


logger.info("📊 SMB Unified Scoring Integration loaded")
