"""
Trading Rules Router - API endpoints for trading rules and market context
"""
from fastapi import APIRouter, HTTPException
from typing import Optional, List
from pydantic import BaseModel

router = APIRouter(prefix="/api/rules", tags=["trading-rules"])

# Will be initialized from main server
trading_rules_engine = None

def init_trading_rules(engine):
    global trading_rules_engine
    trading_rules_engine = engine


# ===================== PYDANTIC MODELS =====================

class StrategyRecommendationRequest(BaseModel):
    market_regime: str = "low_strength_low_weakness"
    time_of_day: str = "morning_session"
    rvol: float = 1.0
    has_catalyst: bool = False


class SetupValidationRequest(BaseModel):
    strategy_id: str
    rvol: float = 1.0
    against_market_trend: bool = False
    time_of_day: str = "morning_session"
    additional_conditions: dict = {}


# ===================== ENDPOINTS =====================

@router.get("/market-context")
async def get_market_context_rules():
    """Get all market context regime rules"""
    if not trading_rules_engine:
        raise HTTPException(500, "Trading rules engine not initialized")
    
    return trading_rules_engine.market_context_rules


@router.get("/market-context/{regime}")
async def get_regime_rules(regime: str):
    """Get rules for a specific market regime"""
    if not trading_rules_engine:
        raise HTTPException(500, "Trading rules engine not initialized")
    
    regime_rules = trading_rules_engine.market_context_rules["regime_identification"].get(regime)
    
    if not regime_rules:
        raise HTTPException(404, f"Regime '{regime}' not found. Valid regimes: high_strength_high_weakness, high_strength_low_weakness, high_weakness_low_strength, low_strength_low_weakness, breakout_momentum, range_fade")
    
    return {
        "regime": regime,
        **regime_rules
    }


@router.get("/volume")
async def get_volume_rules():
    """Get all volume-related rules"""
    if not trading_rules_engine:
        raise HTTPException(500, "Trading rules engine not initialized")
    
    return trading_rules_engine.volume_rules


@router.get("/time-of-day")
async def get_time_rules():
    """Get time of day trading rules"""
    if not trading_rules_engine:
        raise HTTPException(500, "Trading rules engine not initialized")
    
    return trading_rules_engine.time_rules


@router.get("/setups")
async def get_setup_rules():
    """Get all setup pattern rules"""
    if not trading_rules_engine:
        raise HTTPException(500, "Trading rules engine not initialized")
    
    return trading_rules_engine.setup_rules


@router.get("/exits")
async def get_exit_rules():
    """Get all exit and target rules"""
    if not trading_rules_engine:
        raise HTTPException(500, "Trading rules engine not initialized")
    
    return trading_rules_engine.exit_rules


@router.get("/stops")
async def get_stop_loss_rules():
    """Get all stop loss placement rules"""
    if not trading_rules_engine:
        raise HTTPException(500, "Trading rules engine not initialized")
    
    return trading_rules_engine.get_stop_loss_rules()


@router.get("/avoidance")
async def get_avoidance_rules():
    """Get all avoidance conditions"""
    if not trading_rules_engine:
        raise HTTPException(500, "Trading rules engine not initialized")
    
    return trading_rules_engine.avoidance_rules


@router.get("/catalyst-scoring")
async def get_catalyst_scoring():
    """Get catalyst scoring rubric"""
    if not trading_rules_engine:
        raise HTTPException(500, "Trading rules engine not initialized")
    
    return trading_rules_engine.catalyst_scoring


@router.get("/game-plan")
async def get_game_plan_framework():
    """Get daily game plan framework"""
    if not trading_rules_engine:
        raise HTTPException(500, "Trading rules engine not initialized")
    
    return trading_rules_engine.get_game_plan_framework()


@router.post("/recommend")
async def get_strategy_recommendations(request: StrategyRecommendationRequest):
    """Get recommended strategies based on current conditions"""
    if not trading_rules_engine:
        raise HTTPException(500, "Trading rules engine not initialized")
    
    recommendations = trading_rules_engine.get_recommended_strategies(
        market_regime=request.market_regime,
        time_of_day=request.time_of_day,
        rvol=request.rvol,
        has_catalyst=request.has_catalyst
    )
    
    return {
        "conditions": {
            "market_regime": request.market_regime,
            "time_of_day": request.time_of_day,
            "rvol": request.rvol,
            "has_catalyst": request.has_catalyst
        },
        "recommendations": recommendations
    }


@router.post("/validate")
async def validate_setup(request: SetupValidationRequest):
    """Validate if a setup meets strategy requirements"""
    if not trading_rules_engine:
        raise HTTPException(500, "Trading rules engine not initialized")
    
    conditions = {
        "rvol": request.rvol,
        "against_market_trend": request.against_market_trend,
        "time_of_day": request.time_of_day,
        **request.additional_conditions
    }
    
    validation = trading_rules_engine.validate_setup(
        strategy_id=request.strategy_id,
        conditions=conditions
    )
    
    return {
        "strategy": request.strategy_id,
        "conditions": conditions,
        "validation": validation
    }


@router.get("/summary")
async def get_rules_summary():
    """Get a summary of all trading rules"""
    if not trading_rules_engine:
        raise HTTPException(500, "Trading rules engine not initialized")
    
    return {
        "market_regimes": list(trading_rules_engine.market_context_rules["regime_identification"].keys()),
        "time_windows": list(trading_rules_engine.time_rules["optimal_windows"].keys()),
        "rvol_thresholds": trading_rules_engine.volume_rules["rvol_thresholds"],
        "scaling_methods": list(trading_rules_engine.exit_rules["scaling_methods"].keys()),
        "stop_types": list(trading_rules_engine.get_stop_loss_rules()["placement_rules"].keys()),
        "catalyst_scale": trading_rules_engine.catalyst_scoring["scale"],
        "universal_avoidance_count": len(trading_rules_engine.avoidance_rules["universal_avoidance"]),
        "strategy_specific_rules_count": len(trading_rules_engine.avoidance_rules["strategy_specific"])
    }


@router.get("/quick-reference/{topic}")
async def get_quick_reference(topic: str):
    """Get quick reference for a specific topic"""
    if not trading_rules_engine:
        raise HTTPException(500, "Trading rules engine not initialized")
    
    references = {
        "rvol": {
            "minimum_in_play": "1.5x",
            "strong_interest": "2.0x",
            "high_conviction": "3.0x",
            "exceptional": "5.0x+",
            "rule": "Higher RVOL = higher conviction, tighter stops"
        },
        "stops": {
            "standard": "$.02 below consolidation/level",
            "one_and_done": ["Back$ide", "Off Sides", "HitchHiker"],
            "two_attempts_max": ["Rubber Band"],
            "rule": "Never average down on losing trades"
        },
        "scaling": {
            "thirds": "1/3 at 1R, 1/3 at 2R, 1/3 runner",
            "halves": "1/2 at 2x, 1/2 at 3x",
            "full": "All out at VWAP (Back$ide)",
            "rule": "Always take partial profits"
        },
        "times": {
            "best": "10:00-10:45 AM",
            "opening_plays": "Before 9:45 AM",
            "avoid_scalps": "After 3 PM (exception: ranging stocks)",
            "midday": "11:30-1:30 - reduced activity"
        },
        "context": {
            "trending": "Trade with trend, buy dips/sell rallies",
            "choppy": "Mean reversion, reduce size 50%",
            "volatile": "Both directions work, wider stops",
            "rule": "Always identify regime before trading"
        }
    }
    
    if topic not in references:
        raise HTTPException(404, f"Topic '{topic}' not found. Available: {list(references.keys())}")
    
    return {
        "topic": topic,
        "reference": references[topic]
    }
