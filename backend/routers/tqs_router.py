"""
TQS API Router - Trade Quality Score Endpoints

Provides API access to the TQS engine for:
- Single symbol scoring
- Batch scoring
- Detailed breakdowns
- Threshold guidance
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from services.tqs import get_tqs_engine

router = APIRouter(prefix="/api/tqs", tags=["tqs"])


class BatchScoreRequest(BaseModel):
    """Request model for batch scoring"""
    opportunities: List[Dict[str, Any]]


class ScoreRequest(BaseModel):
    """Request model for single score calculation"""
    symbol: str
    setup_type: str
    direction: str = "long"
    trade_style: Optional[str] = None  # NEW: move_2_move, trade_2_hold, a_plus, swing, investment
    tape_score: float = 0.0
    tape_confirmation: bool = False
    smb_grade: str = "B"
    smb_5var_score: int = 25
    risk_reward: float = 2.0
    alert_priority: str = "medium"
    market_regime: Optional[str] = None
    time_of_day: Optional[str] = None
    planned_position_size: int = 100
    account_value: float = 100000.0


@router.get("/score/{symbol}")
async def get_tqs_score(
    symbol: str,
    setup_type: str = Query(default="unknown", description="Type of setup (e.g., bull_flag, vwap_bounce)"),
    direction: str = Query(default="long", description="Trade direction: long or short")
):
    """
    Get TQS score for a symbol with basic parameters.
    
    Returns:
    - Overall score (0-100)
    - Grade (A/B+/B/C+/C/D/F)
    - Action recommendation (STRONG_BUY/BUY/HOLD/AVOID/STRONG_AVOID)
    - Pillar scores breakdown
    """
    tqs = get_tqs_engine()
    
    result = await tqs.calculate_tqs(
        symbol=symbol.upper(),
        setup_type=setup_type,
        direction=direction
    )
    
    return {
        "success": True,
        "tqs": result.to_summary()
    }


@router.post("/score")
async def calculate_tqs_score(request: ScoreRequest):
    """
    Calculate detailed TQS score with full parameters.
    
    Use this endpoint when you have additional context like:
    - Tape reading data
    - SMB grades
    - Position sizing info
    - Trade style (move_2_move, trade_2_hold, a_plus, swing, investment)
    """
    tqs = get_tqs_engine()
    
    result = await tqs.calculate_tqs(
        symbol=request.symbol.upper(),
        setup_type=request.setup_type,
        direction=request.direction,
        trade_style=request.trade_style,  # NEW: Pass trade style for timeframe-aware weighting
        tape_score=request.tape_score,
        tape_confirmation=request.tape_confirmation,
        smb_grade=request.smb_grade,
        smb_5var_score=request.smb_5var_score,
        risk_reward=request.risk_reward,
        alert_priority=request.alert_priority,
        market_regime=request.market_regime,
        time_of_day=request.time_of_day,
        planned_position_size=request.planned_position_size,
        account_value=request.account_value
    )
    
    return {
        "success": True,
        "tqs": result.to_dict()
    }


@router.get("/breakdown/{symbol}")
async def get_tqs_breakdown(
    symbol: str,
    setup_type: str = Query(default="unknown"),
    direction: str = Query(default="long")
):
    """
    Get detailed TQS breakdown with all pillar components.
    
    Returns full analysis including:
    - Each pillar's score and grade
    - Component breakdowns within each pillar
    - All factors (positive and negative)
    - Warnings if applicable
    """
    tqs = get_tqs_engine()
    
    result = await tqs.calculate_tqs(
        symbol=symbol.upper(),
        setup_type=setup_type,
        direction=direction
    )
    
    return {
        "success": True,
        "breakdown": result.to_dict()
    }


@router.post("/batch")
async def batch_score(request: BatchScoreRequest):
    """
    Score multiple opportunities at once.
    
    Request body should contain a list of opportunities, each with:
    - symbol (required)
    - setup_type (required)
    - direction (optional, default "long")
    - Other optional parameters
    
    Returns sorted list (highest score first).
    """
    if not request.opportunities:
        return {"success": True, "results": []}
        
    if len(request.opportunities) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 opportunities per batch")
        
    tqs = get_tqs_engine()
    
    results = await tqs.batch_calculate(request.opportunities)
    
    return {
        "success": True,
        "count": len(results),
        "results": [r.to_summary() for r in results]
    }


@router.get("/guidance")
def get_score_guidance(score: float = Query(ge=0, le=100)):
    """
    Get trading guidance for a particular TQS score.
    
    Returns:
    - Recommended action
    - Confidence level
    - Position sizing recommendation
    - General guidance text
    """
    tqs = get_tqs_engine()
    guidance = tqs.get_threshold_guidance(score)
    
    return {
        "success": True,
        "score": score,
        "guidance": guidance
    }


@router.get("/thresholds")
def get_tqs_thresholds():
    """
    Get the current TQS threshold configuration.
    
    Returns the score ranges for each action category.
    """
    tqs = get_tqs_engine()
    
    return {
        "success": True,
        "thresholds": tqs.ACTION_THRESHOLDS,
        "weights": tqs.WEIGHTS,
        "grade_ranges": {
            "A": "85-100",
            "B+": "75-84",
            "B": "65-74",
            "C+": "55-64",
            "C": "45-54",
            "D": "35-44",
            "F": "0-34"
        }
    }


@router.get("/pillars")
def get_pillar_info():
    """
    Get information about the 5 TQS pillars.
    
    Explains what each pillar measures and its weight.
    """
    return {
        "success": True,
        "pillars": {
            "setup": {
                "name": "Setup Quality",
                "weight": "25%",
                "description": "Pattern clarity, historical win rate, expected value, tape confirmation",
                "components": ["pattern_score", "win_rate_score", "ev_score", "tape_score", "smb_score"]
            },
            "technical": {
                "name": "Technical Quality",
                "weight": "25%",
                "description": "Trend alignment, RSI, support/resistance, volatility, volume",
                "components": ["trend_score", "rsi_score", "levels_score", "volatility_score", "volume_score"]
            },
            "fundamental": {
                "name": "Fundamental Quality",
                "weight": "15%",
                "description": "Catalyst presence, short interest, float, institutional ownership, earnings",
                "components": ["catalyst_score", "short_interest_score", "float_score", "institutional_score", "earnings_score"]
            },
            "context": {
                "name": "Context Quality",
                "weight": "20%",
                "description": "Market regime, time of day, sector strength, VIX regime, day of week",
                "components": ["regime_score", "time_score", "sector_score", "vix_score", "day_score"]
            },
            "execution": {
                "name": "Execution Quality",
                "weight": "15%",
                "description": "Your execution history, tilt state, entry/exit tendencies, recent streak",
                "components": ["history_score", "tilt_score", "entry_tendency_score", "exit_tendency_score", "streak_score"]
            }
        }
    }
