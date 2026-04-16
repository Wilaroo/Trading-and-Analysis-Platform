"""
SMB Integration Router

Provides API endpoints for:
- Setup configuration lookup
- SMB 5-Variable scoring
- Trade style recommendations
- Earnings catalyst scoring
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/smb", tags=["SMB Integration"])

# Import SMB services
try:
    from services.smb_integration import (
        SETUP_REGISTRY, SMB_SETUP_ALIASES,
        get_setup_config, resolve_setup_name, get_default_trade_style,
        get_setup_direction, get_directional_setup_name,
        SMBVariableScore, calculate_smb_score,
        TRADE_STYLE_TARGETS, get_style_targets,
        get_setups_by_category, get_setups_by_direction,
        get_all_long_setups, get_all_short_setups,
        TradeStyle, SetupDirection, SetupCategory
    )
    from services.earnings_scoring_service import (
        EarningsData, EarningsScore, GuidanceDirection,
        calculate_earnings_score, get_score_description,
        format_score_for_display, get_earnings_service
    )
    SMB_AVAILABLE = True
except ImportError as e:
    logger.warning(f"SMB Integration not fully available: {e}")
    SMB_AVAILABLE = False


# ==================== Pydantic Models ====================

class SetupConfigResponse(BaseModel):
    name: str
    display_name: str
    category: str
    default_style: str
    direction: str
    typical_r_target: float
    typical_win_rate: float
    requires_tape_confirmation: bool
    requires_catalyst: bool
    min_rvol: float
    smb_aliases: List[str]
    valid_time_windows: List[str]
    valid_regimes: List[str]


class SMBScoreRequest(BaseModel):
    spy_trend: str = "neutral"
    sector_alignment: bool = True
    market_regime: str = "range_bound"
    catalyst_score: float = 5.0
    has_news: bool = False
    earnings_score: int = 0
    support_clarity: float = 5.0
    resistance_clarity: float = 5.0
    atr_reasonable: bool = True
    tape_score: float = 5.0
    bid_ask_healthy: bool = True
    volume_confirming: bool = True
    setup_confidence: float = 5.0
    similar_patterns_won: bool = True


class SMBScoreResponse(BaseModel):
    big_picture: int
    intraday_fundamental: int
    technical_level: int
    tape_reading: int
    intuition: int
    total_score: int
    min_variable: int
    grade: str
    is_a_plus: bool
    trade_style: str
    size_multiplier: float
    notes: Dict[str, str]


class EarningsScoreRequest(BaseModel):
    symbol: str
    report_date: str
    eps_actual: float
    eps_estimate: float
    revenue_actual: float
    revenue_estimate: float
    margin_actual: Optional[float] = None
    margin_previous: Optional[float] = None
    q_guidance_provided: bool = False
    q_guidance_direction: str = "none"
    fy_guidance_provided: bool = False
    fy_guidance_direction: str = "none"
    revenue_guidance_provided: bool = False
    revenue_guidance_direction: str = "none"
    management_track_record: str = "neutral"
    competitor_comparison: str = "similar"
    quarter_position: int = 1


class EarningsScoreResponse(BaseModel):
    symbol: str
    base_score: int
    modifier_adjustment: int
    final_score: int
    direction: str
    trading_approach: str
    suggested_setups: List[str]
    avoid_setups: List[str]
    base_score_reasoning: List[str]
    modifier_reasoning: List[str]
    eps_surprise_pct: float
    revenue_surprise_pct: float
    guidance_summary: str
    score_description: Dict


# ==================== Setup Endpoints ====================

@router.get("/setups", response_model=Dict[str, Any])
def get_all_setups():
    """Get all available setups with their configurations"""
    if not SMB_AVAILABLE:
        raise HTTPException(500, "SMB Integration not available")
    
    setups = {}
    for name, config in SETUP_REGISTRY.items():
        setups[name] = {
            "display_name": config.display_name,
            "category": config.category.value,
            "default_style": config.default_style.value,
            "direction": config.direction.value,
            "typical_r_target": config.typical_r_target
        }
    
    return {
        "total_setups": len(setups),
        "setups": setups,
        "aliases": SMB_SETUP_ALIASES
    }


@router.get("/setup/{setup_name}", response_model=SetupConfigResponse)
def get_setup(setup_name: str):
    """Get configuration for a specific setup by name or alias"""
    if not SMB_AVAILABLE:
        raise HTTPException(500, "SMB Integration not available")
    
    config = get_setup_config(setup_name)
    if not config:
        raise HTTPException(404, f"Setup '{setup_name}' not found")
    
    return SetupConfigResponse(
        name=config.name,
        display_name=config.display_name,
        category=config.category.value,
        default_style=config.default_style.value,
        direction=config.direction.value,
        typical_r_target=config.typical_r_target,
        typical_win_rate=config.typical_win_rate,
        requires_tape_confirmation=config.requires_tape_confirmation,
        requires_catalyst=config.requires_catalyst,
        min_rvol=config.min_rvol,
        smb_aliases=config.smb_aliases,
        valid_time_windows=config.valid_time_windows,
        valid_regimes=config.valid_regimes
    )


@router.get("/setups/by-category/{category}")
def get_setups_by_category_endpoint(category: str):
    """Get all setups in a specific category"""
    if not SMB_AVAILABLE:
        raise HTTPException(500, "SMB Integration not available")
    
    try:
        cat_enum = SetupCategory(category)
    except ValueError:
        valid = [c.value for c in SetupCategory]
        raise HTTPException(400, f"Invalid category. Valid: {valid}")
    
    setups = get_setups_by_category(cat_enum)
    return {"category": category, "setups": setups, "count": len(setups)}


@router.get("/setups/by-direction/{direction}")
def get_setups_by_direction_endpoint(direction: str):
    """Get all setups by direction bias (long/short/both)"""
    if not SMB_AVAILABLE:
        raise HTTPException(500, "SMB Integration not available")
    
    if direction == "long":
        setups = get_all_long_setups()
    elif direction == "short":
        setups = get_all_short_setups()
    elif direction == "both":
        setups = get_setups_by_direction(SetupDirection.BOTH)
    else:
        raise HTTPException(400, "Invalid direction. Valid: long, short, both")
    
    return {"direction": direction, "setups": setups, "count": len(setups)}


@router.get("/setups/summary")
def get_setups_summary():
    """Get summary statistics of all setups"""
    if not SMB_AVAILABLE:
        raise HTTPException(500, "SMB Integration not available")
    
    return {
        "total_setups": len(SETUP_REGISTRY),
        "by_direction": {
            "long": len(get_all_long_setups()),
            "short": len(get_all_short_setups()),
            "both": len(get_setups_by_direction(SetupDirection.BOTH))
        },
        "by_category": {
            cat.value: len(get_setups_by_category(cat))
            for cat in SetupCategory
        },
        "by_style": {
            "scalp": len([n for n, c in SETUP_REGISTRY.items() 
                              if c.default_style == TradeStyle.SCALP]),
            "intraday": len([n for n, c in SETUP_REGISTRY.items() 
                               if c.default_style == TradeStyle.INTRADAY]),
            "multi_day": len([n for n, c in SETUP_REGISTRY.items() 
                               if c.default_style == TradeStyle.MULTI_DAY]),
        },
        "aliases_count": len(SMB_SETUP_ALIASES)
    }


# ==================== SMB Scoring Endpoints ====================

@router.post("/score", response_model=SMBScoreResponse)
def calculate_smb_variable_score(request: SMBScoreRequest):
    """Calculate SMB 5-Variable score from inputs"""
    if not SMB_AVAILABLE:
        raise HTTPException(500, "SMB Integration not available")
    
    score = calculate_smb_score(
        spy_trend=request.spy_trend,
        sector_alignment=request.sector_alignment,
        market_regime=request.market_regime,
        catalyst_score=request.catalyst_score,
        has_news=request.has_news,
        earnings_score=request.earnings_score,
        support_clarity=request.support_clarity,
        resistance_clarity=request.resistance_clarity,
        atr_reasonable=request.atr_reasonable,
        tape_score=request.tape_score,
        bid_ask_healthy=request.bid_ask_healthy,
        volume_confirming=request.volume_confirming,
        setup_confidence=request.setup_confidence,
        similar_patterns_won=request.similar_patterns_won
    )
    
    return SMBScoreResponse(**score.to_dict())


@router.get("/trade-styles")
def get_trade_styles():
    """Get all trade styles with their targets and rules"""
    if not SMB_AVAILABLE:
        raise HTTPException(500, "SMB Integration not available")
    
    return {
        style.value: {
            **targets,
            "description": {
                "scalp": "Scalp - capture immediate next move, exit quickly. Target 1R.",
                "intraday": "Intraday swing - hold for Reason2Sell trigger. Target 3-5R.",
                "multi_day": "Max conviction when all 5 variables align. Target 10R+.",
                # Backwards compatibility
                "move_2_move": "Scalp - capture immediate next move, exit quickly. Target 1R.",
                "trade_2_hold": "Intraday swing - hold for Reason2Sell trigger. Target 3-5R.",
                "a_plus": "Max conviction when all 5 variables align. Target 10R+."
            }.get(style.value, "")
        }
        for style, targets in TRADE_STYLE_TARGETS.items()
    }


# ==================== Earnings Scoring Endpoints ====================

@router.post("/earnings/score", response_model=EarningsScoreResponse)
def score_earnings_catalyst(request: EarningsScoreRequest):
    """Score an earnings catalyst using SMB methodology"""
    if not SMB_AVAILABLE:
        raise HTTPException(500, "SMB Integration not available")
    
    # Convert guidance directions
    q_dir = GuidanceDirection(request.q_guidance_direction) if request.q_guidance_direction != "none" else GuidanceDirection.NONE
    fy_dir = GuidanceDirection(request.fy_guidance_direction) if request.fy_guidance_direction != "none" else GuidanceDirection.NONE
    rev_dir = GuidanceDirection(request.revenue_guidance_direction) if request.revenue_guidance_direction != "none" else GuidanceDirection.NONE
    
    data = EarningsData(
        symbol=request.symbol,
        report_date=request.report_date,
        eps_actual=request.eps_actual,
        eps_estimate=request.eps_estimate,
        revenue_actual=request.revenue_actual,
        revenue_estimate=request.revenue_estimate,
        margin_actual=request.margin_actual,
        margin_previous=request.margin_previous,
        q_guidance_provided=request.q_guidance_provided,
        q_guidance_direction=q_dir,
        fy_guidance_provided=request.fy_guidance_provided,
        fy_guidance_direction=fy_dir,
        revenue_guidance_provided=request.revenue_guidance_provided,
        revenue_guidance_direction=rev_dir
    )
    
    score = calculate_earnings_score(
        data=data,
        management_track_record=request.management_track_record,
        competitor_comparison=request.competitor_comparison,
        quarter_position=request.quarter_position
    )
    
    return EarningsScoreResponse(
        symbol=score.symbol,
        base_score=score.base_score,
        modifier_adjustment=score.modifier_adjustment,
        final_score=score.final_score,
        direction=score.direction,
        trading_approach=score.trading_approach.value,
        suggested_setups=score.suggested_setups,
        avoid_setups=score.avoid_setups,
        base_score_reasoning=score.base_score_reasoning,
        modifier_reasoning=score.modifier_reasoning,
        eps_surprise_pct=score.eps_surprise_pct,
        revenue_surprise_pct=score.revenue_surprise_pct,
        guidance_summary=score.guidance_summary,
        score_description=get_score_description(score.final_score)
    )


@router.get("/earnings/descriptions")
def get_all_score_descriptions():
    """Get descriptions for all earnings score levels"""
    if not SMB_AVAILABLE:
        raise HTTPException(500, "SMB Integration not available")
    
    from services.earnings_scoring_service import SCORE_DESCRIPTIONS
    return SCORE_DESCRIPTIONS


@router.get("/resolve-alias/{alias}")
def resolve_setup_alias(alias: str):
    """Resolve an SMB setup alias to canonical name"""
    if not SMB_AVAILABLE:
        raise HTTPException(500, "SMB Integration not available")
    
    canonical = resolve_setup_name(alias)
    is_alias = alias.lower() != canonical
    
    config = get_setup_config(canonical)
    
    return {
        "input": alias,
        "canonical_name": canonical,
        "was_alias": is_alias,
        "exists": config is not None,
        "display_name": config.display_name if config else None
    }


# ==================== Reasons2Sell Endpoints ====================

class Reason2SellRequest(BaseModel):
    entry_price: float
    current_price: float
    target: float
    stop_loss: float
    direction: str = "long"
    peak_price: Optional[float] = None
    ema_9: Optional[float] = None
    vwap: Optional[float] = None
    trade_style: str = "intraday"


@router.post("/reasons-to-sell/check")
def check_reasons_to_sell(request: Reason2SellRequest):
    """Check all Reasons2Sell for a position"""
    try:
        from services.smb_unified_scoring import check_reasons_to_sell, Reason2Sell
        
        position = {
            "entry_price": request.entry_price,
            "target": request.target,
            "stop_loss": request.stop_loss,
            "direction": request.direction,
            "peak_price": request.peak_price or request.entry_price
        }
        
        current_quote = {
            "price": request.current_price,
            "ema_9": request.ema_9 or 0,
            "vwap": request.vwap or 0
        }
        
        result = check_reasons_to_sell(
            position=position,
            current_quote=current_quote,
            trade_style=request.trade_style
        )
        
        return {
            "triggered": result.triggered,
            "reasons": result.reasons,
            "severity": result.severity,
            "recommended_action": result.recommended_action,
            "details": result.details,
            "reason_descriptions": {
                "price_target": "Price target reached",
                "trend_violation": "9 EMA or trendline broken",
                "thesis_invalid": "Original trade thesis no longer valid",
                "market_resistance": "SPY/QQQ at major resistance",
                "tape_exhaustion": "Volume/momentum dried up",
                "parabolic_extension": "Price too extended from value",
                "end_of_day": "Market close approaching",
                "give_back_rule": "Gave back too much of peak profit"
            }
        }
    except ImportError:
        raise HTTPException(500, "Reasons2Sell module not available")


@router.get("/reasons-to-sell/list")
def list_reasons_to_sell():
    """Get all Reasons2Sell with descriptions"""
    return {
        "reasons": [
            {"code": "price_target", "name": "Price Target Hit", "description": "Exit at predetermined target level"},
            {"code": "trend_violation", "name": "Trend Violation", "description": "Price broke 9 EMA or key trendline (critical for T2H)"},
            {"code": "thesis_invalid", "name": "Thesis Invalidation", "description": "Original reason for trade no longer valid"},
            {"code": "market_resistance", "name": "Market Resistance", "description": "SPY/QQQ hit major level that may stall momentum"},
            {"code": "tape_exhaustion", "name": "Tape Exhaustion", "description": "Buying/selling volume dissipated, tape slowing"},
            {"code": "parabolic_extension", "name": "Parabolic Extension", "description": "Price too far from VWAP/moving averages"},
            {"code": "breaking_news", "name": "Breaking News", "description": "Fresh headlines that change the setup"},
            {"code": "end_of_day", "name": "End of Day", "description": "Market close approaching (last 15 min)"},
            {"code": "give_back_rule", "name": "Give-Back Rule", "description": "Gave back 30-50% of peak open profit"},
            {"code": "time_stop", "name": "Time Stop", "description": "Trade not working within expected time window"}
        ],
        "by_trade_style": {
            "scalp": ["price_target", "tape_exhaustion", "time_stop"],
            "intraday": ["price_target", "trend_violation", "thesis_invalid", "give_back_rule"],
            "multi_day": ["trend_violation", "thesis_invalid", "market_resistance"],
            # Backwards compatibility
            "move_2_move": ["price_target", "tape_exhaustion", "time_stop"],
            "trade_2_hold": ["price_target", "trend_violation", "thesis_invalid", "give_back_rule"],
            "a_plus": ["trend_violation", "thesis_invalid", "market_resistance"]
        }
    }


# ==================== Tiered Entry Endpoints ====================

class TieredEntryRequest(BaseModel):
    risk_per_trade: float  # e.g., $200
    entry_price: float
    stop_price: float
    trade_style: str = "intraday"
    smb_grade: str = "B"


@router.post("/tiered-entry/calculate")
def calculate_tiered_entry(request: TieredEntryRequest):
    """Calculate tiered entry sizes based on SMB methodology"""
    try:
        from services.smb_unified_scoring import calculate_tier_sizes
        
        result = calculate_tier_sizes(
            risk_per_trade=request.risk_per_trade,
            entry_price=request.entry_price,
            stop_price=request.stop_price,
            trade_style=request.trade_style,
            smb_grade=request.smb_grade
        )
        
        risk_per_share = result.get("risk_per_share", 0)
        
        return {
            "tiers": {
                "tier_1": {
                    "shares": result["tier_1"],
                    "description": "Feelers - initial position at key level",
                    "trigger": "Entry at trigger price with tape confirmation"
                },
                "tier_2": {
                    "shares": result["tier_2"],
                    "description": "Confirmation - add after setup confirms",
                    "trigger": "Setup holds, tape improves, pattern validates"
                },
                "tier_3": {
                    "shares": result["tier_3"],
                    "description": "A+ Size - full conviction add",
                    "trigger": "All 5 SMB variables align, A+ grade confirmed"
                }
            },
            "total_shares": result["total"],
            "risk_per_share": risk_per_share,
            "total_risk": request.risk_per_trade,
            "allocation_percentages": {
                "tier_1": round(result["tier_1"] / result["total"] * 100, 1) if result["total"] > 0 else 0,
                "tier_2": round(result["tier_2"] / result["total"] * 100, 1) if result["total"] > 0 else 0,
                "tier_3": round(result["tier_3"] / result["total"] * 100, 1) if result["total"] > 0 else 0
            },
            "style_rules": {
                "move_2_move": "Larger Tier 1 (70%), quick in-and-out",
                "trade_2_hold": "Gradual scaling (30/40/30), hold for target",
                "a_plus": "Aggressive (40/30/30), max conviction"
            }.get(request.trade_style, "Standard scaling")
        }
    except ImportError:
        raise HTTPException(500, "Tiered entry module not available")


# ==================== Tape Reading Endpoints ====================

class TapeAnalysisRequest(BaseModel):
    symbol: str
    price: float
    bid: float
    ask: float
    volume: int
    avg_volume: int
    bid_size: int = 0
    ask_size: int = 0
    change_percent: float = 0


@router.post("/tape/analyze")
def analyze_tape(request: TapeAnalysisRequest):
    """Analyze tape/order flow and return Level 2 Box metrics"""
    try:
        from services.smb_unified_scoring import analyze_tape_from_quote_data
        
        quote_data = {
            "price": request.price,
            "bid": request.bid,
            "ask": request.ask,
            "volume": request.volume,
            "avg_volume": request.avg_volume,
            "bid_size": request.bid_size,
            "ask_size": request.ask_size,
            "change_percent": request.change_percent
        }
        
        metrics = analyze_tape_from_quote_data(
            symbol=request.symbol,
            quote_data=quote_data
        )
        
        return metrics.to_dict()
    except ImportError:
        raise HTTPException(500, "Tape analysis module not available")


logger.info("📊 SMB Integration Router loaded with Reasons2Sell, Tiered Entry, and Tape Analysis")
