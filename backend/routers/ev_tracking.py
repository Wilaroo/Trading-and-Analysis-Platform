"""
EV Tracking Router - API endpoints for SMB-style Expected Value tracking

Provides endpoints for:
- Getting EV reports per setup
- Recording trade outcomes
- Managing the SMB workflow (Idea → Execute → Review)
- PlayBook summary with positive/negative EV setups
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict
import logging

from services.ev_tracking_service import (
    get_ev_service, 
    EVTrackingService,
    TradeLevels,
    calculate_levels_from_technical,
    calculate_projected_ev
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ev", tags=["EV Tracking"])

# Service instance (initialized on first use)
_service: Optional[EVTrackingService] = None


def get_service() -> EVTrackingService:
    """Get or initialize the EV tracking service"""
    global _service
    if _service is None:
        # Import db connection
        try:
            from pymongo import MongoClient
            import os
            mongo_url = os.environ.get("MONGO_URL")
            db_name = os.environ.get("DB_NAME", "trading_bot")
            if mongo_url:
                client = MongoClient(mongo_url)
                db = client[db_name]
                _service = get_ev_service(db)
            else:
                _service = get_ev_service(None)
        except Exception as e:
            logger.warning(f"Could not connect to MongoDB for EV service: {e}")
            _service = get_ev_service(None)
    return _service


# ==================== REQUEST/RESPONSE MODELS ====================

class RecordOutcomeRequest(BaseModel):
    """Request to record a trade outcome"""
    setup_type: str
    r_multiple: float
    grade: str = "B"  # A/B/C
    outcome: str = "won"  # won/lost/scratched


class CreateIdeaRequest(BaseModel):
    """Request to create a new trade idea"""
    ticker: str
    setup_type: str
    direction: str  # long/short
    catalyst_score: float  # 1-10
    big_picture: str = ""
    technical_thesis: str = ""


class GradeIdeaRequest(BaseModel):
    """Request to grade/filter an idea"""
    idea_id: str
    market_context_score: float = 0.5


class CreatePlanRequest(BaseModel):
    """Request to create a trade plan"""
    idea_id: str
    entry_trigger: float
    stop_loss: float
    target_1: float
    target_2: Optional[float] = None
    reasons_to_sell: Optional[List[str]] = None
    base_shares: int = 100


class ReviewTradeRequest(BaseModel):
    """Request to review a completed trade"""
    idea_id: str
    outcome: str  # won/lost/scratched
    exit_price: float
    actual_pnl: float = 0.0


class CalculateLevelsRequest(BaseModel):
    """Request to calculate trade levels from technical data"""
    current_price: float
    support: float
    resistance: float
    atr: float
    direction: str  # long/short
    vwap: Optional[float] = None
    ema_9: Optional[float] = None
    high_of_day: Optional[float] = None
    low_of_day: Optional[float] = None
    setup_type: str = "default"


class ProjectedEVRequest(BaseModel):
    """Request to calculate projected EV from levels and historical win rate"""
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: Optional[float] = None
    setup_type: str
    partial_target_1_pct: float = 0.5  # Take 50% off at T1


class EVResponse(BaseModel):
    """EV report response"""
    setup_type: str
    total_trades: int
    win_rate: float
    avg_win_r: float
    avg_loss_r: float
    expected_value_r: float
    profit_factor: float
    ev_gate: str
    size_multiplier: float
    recommendation: str
    min_sample_reached: bool


# ==================== ENDPOINTS ====================

@router.get("/report")
def get_ev_report(setup_type: str = None):
    """
    Get Expected Value report for one or all setups.
    
    EV Formula: EV = (win_rate × avg_win_R) – (loss_rate × avg_loss_R)
    
    Returns:
    - Per-setup EV in R-multiples
    - Win rate, average win/loss
    - Trading gate recommendation (A-SIZE, GREENLIGHT, CAUTIOUS, REVIEW, DROP)
    """
    service = get_service()
    return {
        "success": True,
        "report": service.get_ev_report(setup_type)
    }


@router.get("/playbook")
def get_playbook_summary():
    """
    Get PlayBook summary with all setups categorized by EV.
    
    Returns:
    - positive_ev_setups: Setups with edge (keep trading)
    - negative_ev_setups: Setups to review or drop
    - tracking_setups: Need more trades for reliable EV
    """
    service = get_service()
    return {
        "success": True,
        "playbook": service.get_playbook_summary()
    }


@router.post("/record-outcome")
def record_trade_outcome(request: RecordOutcomeRequest):
    """
    Record a trade outcome for EV calculation.
    
    This is the core input for the EV calculator:
    - r_multiple: The R achieved (e.g., +2.5R for win, -1R for stop loss)
    - grade: A/B/C based on trade quality
    - outcome: won/lost/scratched
    """
    service = get_service()
    
    service.record_trade_outcome(
        setup_type=request.setup_type,
        r_multiple=request.r_multiple,
        grade=request.grade,
        outcome=request.outcome
    )
    
    # Get updated EV
    ev_report = service.get_ev_report(request.setup_type)
    
    return {
        "success": True,
        "message": f"Recorded {request.outcome} ({request.r_multiple:+.2f}R) for {request.setup_type}",
        "ev_report": ev_report
    }


@router.post("/calculate")
def calculate_ev(setup_type: str):
    """
    Manually trigger EV calculation for a setup.
    
    SMB Formula: EV = (p_win × avg_win) – (p_loss × avg_loss)
    """
    service = get_service()
    ev = service.calculate_ev(setup_type)
    
    return {
        "success": True,
        "setup_type": setup_type,
        "expected_value_r": ev,
        "report": service.get_ev_report(setup_type)
    }


# ==================== SMB WORKFLOW ENDPOINTS ====================

@router.post("/workflow/idea")
def create_trade_idea(request: CreateIdeaRequest):
    """
    Step 1: Create a new trade idea (Idea Generation)
    
    This starts the SMB workflow:
    1. Idea Gen → 2. Filter/Grade → 3. Plan → 4. Execute → 5. Review
    """
    service = get_service()
    
    idea = service.create_idea(
        ticker=request.ticker,
        setup_type=request.setup_type,
        direction=request.direction,
        catalyst_score=request.catalyst_score,
        big_picture=request.big_picture,
        technical_thesis=request.technical_thesis
    )
    
    return {
        "success": True,
        "idea_id": idea.id,
        "ticker": idea.ticker,
        "setup_type": idea.setup_type,
        "historical_ev_r": idea.historical_ev_r,
        "ev_gate": idea.ev_gate,
        "state": idea.state.value
    }


@router.post("/workflow/grade")
def grade_trade_idea(request: GradeIdeaRequest):
    """
    Step 2: Filter and grade the idea (A/B/C)
    
    Drops ideas with:
    - Low catalyst score (<5)
    - Negative EV for this setup (DROP gate)
    
    Assigns grade based on:
    - Catalyst strength
    - Historical EV
    - Market context
    - Projected R:R
    """
    service = get_service()
    
    idea = service.filter_and_grade(
        idea_id=request.idea_id,
        market_context_score=request.market_context_score
    )
    
    if idea is None:
        return {
            "success": False,
            "message": "Idea dropped (low catalyst or negative EV)",
            "dropped": True
        }
    
    return {
        "success": True,
        "idea_id": idea.id,
        "grade": idea.grade,
        "grade_score": idea.grade_score,
        "grade_reasons": idea.grade_reasons,
        "state": idea.state.value
    }


@router.post("/workflow/plan")
def create_trade_plan(request: CreatePlanRequest):
    """
    Step 3: Create the trade plan with entries, stops, targets
    
    Position size is adjusted based on:
    - EV gate (A-SIZE gets 1.5x, CAUTIOUS gets 0.5x)
    - Trade grade (A-grade gets 1.2x bonus)
    """
    service = get_service()
    
    idea = service.create_trade_plan(
        idea_id=request.idea_id,
        entry_trigger=request.entry_trigger,
        stop_loss=request.stop_loss,
        target_1=request.target_1,
        target_2=request.target_2,
        reasons_to_sell=request.reasons_to_sell,
        base_shares=request.base_shares
    )
    
    if idea is None:
        raise HTTPException(status_code=404, detail="Idea not found")
    
    return {
        "success": True,
        "idea_id": idea.id,
        "ticker": idea.ticker,
        "entry": idea.entry_trigger,
        "stop_loss": idea.stop_loss,
        "target_1": idea.target_1,
        "target_2": idea.target_2,
        "risk_r": idea.risk_r,
        "reward_r": idea.reward_r,
        "base_shares": idea.base_shares,
        "adjusted_shares": idea.adjusted_shares,
        "reasons_to_sell": idea.reasons_to_sell,
        "state": idea.state.value
    }


@router.post("/workflow/execute")
def execute_trade(idea_id: str):
    """
    Step 4: Mark the trade as executed
    """
    service = get_service()
    
    idea = service.execute_trade(idea_id)
    
    if idea is None:
        raise HTTPException(status_code=404, detail="Idea not found")
    
    return {
        "success": True,
        "idea_id": idea.id,
        "ticker": idea.ticker,
        "direction": idea.direction,
        "shares": idea.adjusted_shares,
        "entry": idea.entry_trigger,
        "executed_at": idea.executed_at,
        "state": idea.state.value
    }


@router.post("/workflow/review")
def review_trade(request: ReviewTradeRequest):
    """
    Step 5: Review the completed trade and update EV
    
    This closes the loop:
    - Records the R-multiple achieved
    - Updates the setup's EV
    - Adjusts future sizing recommendations
    """
    service = get_service()
    
    idea = service.review_trade(
        idea_id=request.idea_id,
        outcome=request.outcome,
        exit_price=request.exit_price,
        actual_pnl=request.actual_pnl
    )
    
    if idea is None:
        raise HTTPException(status_code=404, detail="Idea not found")
    
    # Get updated EV for this setup
    ev_report = service.get_ev_report(idea.setup_type)
    
    return {
        "success": True,
        "idea_id": idea.id,
        "ticker": idea.ticker,
        "outcome": idea.outcome,
        "actual_r_multiple": idea.actual_r_multiple,
        "pnl": idea.pnl,
        "grade": idea.grade,
        "state": idea.state.value,
        "ev_report": ev_report
    }


@router.get("/active-ideas")
def get_active_ideas():
    """Get all active trade ideas in the workflow"""
    service = get_service()
    
    ideas = []
    for idea_id, idea in service._active_ideas.items():
        ideas.append({
            "id": idea.id,
            "ticker": idea.ticker,
            "setup_type": idea.setup_type,
            "direction": idea.direction,
            "grade": idea.grade,
            "state": idea.state.value,
            "historical_ev_r": idea.historical_ev_r,
            "ev_gate": idea.ev_gate
        })
    
    return {
        "success": True,
        "count": len(ideas),
        "ideas": ideas
    }


@router.get("/setup-gates")
def get_setup_gates():
    """
    Get current EV gates for all setups.
    
    Gates determine position sizing:
    - A_TRADE: EV ≥ 2.5R (150% size)
    - B_TRADE: EV 1.0-2.5R (100% size)
    - C_TRADE: EV 0.5-1.0R (75% size)
    - D_TRADE: EV 0-0.5R (50% size)
    - F_TRADE: EV < 0R (don't trade)
    """
    service = get_service()
    
    gates = {}
    for setup, record in service._ev_records.items():
        if record.total_trades > 0:
            gates[setup] = {
                "ev_r": record.expected_value_r,
                "gate": record.ev_gate.value,
                "size_multiplier": record.size_multiplier,
                "trades": record.total_trades,
                "min_sample": record.total_trades >= 10
            }
    
    return {
        "success": True,
        "gates": gates
    }


# ==================== TECHNICAL LEVELS & PROJECTED EV ====================

@router.post("/calculate-levels")
def calculate_trade_levels(request: CalculateLevelsRequest):
    """
    Calculate entry, stop, and target levels from technical data.
    
    Uses Support/Resistance levels, ATR, VWAP, and EMAs to determine:
    - Optimal stop loss placement (below support for longs, above resistance for shorts)
    - Target 1: First profit target (typically at next S/R level)
    - Target 2: Extended target for runners
    - Target 3: Full extension target
    
    Returns R-multiples for each target level.
    """
    levels = calculate_levels_from_technical(
        current_price=request.current_price,
        support=request.support,
        resistance=request.resistance,
        atr=request.atr,
        direction=request.direction,
        vwap=request.vwap,
        ema_9=request.ema_9,
        high_of_day=request.high_of_day,
        low_of_day=request.low_of_day,
        setup_type=request.setup_type
    )
    
    r_multiples = levels.get_projected_r_at_targets()
    
    return {
        "success": True,
        "levels": {
            "entry_price": levels.entry_price,
            "stop_loss": round(levels.stop_loss, 2),
            "target_1": round(levels.target_1, 2),
            "target_2": round(levels.target_2, 2) if levels.target_2 else None,
            "target_3": round(levels.target_3, 2) if levels.target_3 else None,
        },
        "r_multiples": r_multiples,
        "risk_per_share": round(abs(levels.entry_price - levels.stop_loss), 2),
        "technical_context": {
            "support": request.support,
            "resistance": request.resistance,
            "atr": request.atr,
            "vwap": request.vwap,
            "setup_type": request.setup_type
        }
    }


@router.post("/projected-ev")
def calculate_projected_ev_endpoint(request: ProjectedEVRequest):
    """
    Calculate projected EV for a trade based on levels and historical performance.
    
    Combines:
    1. Actual price levels (entry, stop, targets) for R-multiple calculation
    2. Historical win rate for the setup type
    3. Partial profit management assumptions (50% at T1, trail rest)
    
    Returns projected EV in R-multiples and trading recommendation.
    """
    service = get_service()
    
    # Get historical win rate for this setup
    ev_report = service.get_ev_report(request.setup_type)
    
    if ev_report and ev_report.get("total_trades", 0) >= 10:
        historical_win_rate = ev_report.get("win_rate", 0.5)
        historical_avg_loss = ev_report.get("avg_loss_r", 1.0)
    else:
        # Default assumptions if no history
        historical_win_rate = 0.50  # Conservative 50%
        historical_avg_loss = 1.0   # Standard 1R stop
    
    # Create levels object
    levels = TradeLevels(
        entry_price=request.entry_price,
        stop_loss=request.stop_loss,
        target_1=request.target_1,
        target_2=request.target_2 or request.target_1 * 1.5
    )
    
    # Calculate projected EV
    projection = calculate_projected_ev(
        win_rate=historical_win_rate,
        levels=levels,
        partial_target_1_pct=request.partial_target_1_pct,
        avg_loss_r=historical_avg_loss
    )
    
    # Determine trade grade based on projected EV
    projected_ev = projection["projected_ev_r"]
    if projected_ev >= 2.5:
        grade = "A_TRADE"
        recommendation = "Excellent projected edge - Full size or larger"
    elif projected_ev >= 1.0:
        grade = "B_TRADE"
        recommendation = "Solid projected edge - Standard position size"
    elif projected_ev >= 0.5:
        grade = "C_TRADE"
        recommendation = "Marginal projected edge - Reduced size recommended"
    elif projected_ev >= 0:
        grade = "D_TRADE"
        recommendation = "Poor projected edge - Minimal size or pass"
    else:
        grade = "F_TRADE"
        recommendation = "Negative projected EV - Do not trade"
    
    return {
        "success": True,
        "setup_type": request.setup_type,
        "projection": {
            "projected_ev_r": round(projected_ev, 2),
            "r_at_target_1": round(projection["r_at_target_1"], 2),
            "r_at_target_2": round(projection["r_at_target_2"], 2),
            "avg_win_r": round(projection["avg_win_r"], 2),
            "win_rate_used": round(historical_win_rate, 2),
            "risk_r": historical_avg_loss
        },
        "grade": grade,
        "recommendation": recommendation,
        "historical_data_used": ev_report.get("total_trades", 0) >= 10,
        "levels_summary": {
            "entry": request.entry_price,
            "stop": request.stop_loss,
            "target_1": request.target_1,
            "target_2": request.target_2,
            "risk_per_share": round(abs(request.entry_price - request.stop_loss), 2)
        }
    }


@router.get("/analyze-alert/{symbol}")
async def analyze_alert_ev(symbol: str, setup_type: str = None):
    """
    Analyze EV for a specific alert/symbol by fetching its technical levels.
    
    This endpoint:
    1. Fetches current technical snapshot for the symbol
    2. Calculates trade levels based on S/R
    3. Combines with historical EV data for the setup
    4. Returns comprehensive EV analysis
    """
    service = get_service()
    
    # Try to get technical data
    try:
        from services.realtime_technical_service import get_technical_service
        tech_service = get_technical_service()
        snapshot = await tech_service.get_technical_snapshot(symbol)
        
        if not snapshot:
            return {
                "success": False,
                "error": f"Could not get technical data for {symbol}"
            }
        
        # Calculate levels from technical data
        # Default to long direction, can be overridden
        direction = "long" if snapshot.rsi_14 < 50 else "short"
        
        levels = calculate_levels_from_technical(
            current_price=snapshot.current_price,
            support=snapshot.support,
            resistance=snapshot.resistance,
            atr=snapshot.atr,
            direction=direction,
            vwap=snapshot.vwap,
            ema_9=snapshot.ema_9,
            high_of_day=snapshot.high_of_day,
            low_of_day=snapshot.low_of_day,
            setup_type=setup_type or "default"
        )
        
        # Get historical EV if setup type provided
        historical_data = None
        if setup_type:
            historical_data = service.get_ev_report(setup_type)
        
        # Calculate projected EV
        win_rate = historical_data.get("win_rate", 0.5) if historical_data else 0.5
        projection = calculate_projected_ev(win_rate=win_rate, levels=levels)
        
        return {
            "success": True,
            "symbol": symbol,
            "direction": direction,
            "setup_type": setup_type,
            "technical_snapshot": {
                "current_price": snapshot.current_price,
                "support": snapshot.support,
                "resistance": snapshot.resistance,
                "vwap": snapshot.vwap,
                "ema_9": snapshot.ema_9,
                "atr": snapshot.atr,
                "rsi": snapshot.rsi_14
            },
            "calculated_levels": {
                "entry": round(levels.entry_price, 2),
                "stop_loss": round(levels.stop_loss, 2),
                "target_1": round(levels.target_1, 2),
                "target_2": round(levels.target_2, 2) if levels.target_2 else None,
                "r_at_target_1": round(levels.calculate_r_multiple(levels.target_1), 2)
            },
            "projected_ev": {
                "ev_r": round(projection["projected_ev_r"], 2),
                "based_on_win_rate": round(win_rate, 2)
            },
            "historical_ev": historical_data if historical_data else {"message": "No historical data"}
        }
        
    except Exception as e:
        logger.error(f"Error analyzing alert EV: {e}")
        return {
            "success": False,
            "error": str(e)
        }

