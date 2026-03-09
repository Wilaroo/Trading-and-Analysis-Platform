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

from services.ev_tracking_service import get_ev_service, EVTrackingService

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
async def get_ev_report(setup_type: str = None):
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
async def get_playbook_summary():
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
async def record_trade_outcome(request: RecordOutcomeRequest):
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
async def calculate_ev(setup_type: str):
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
async def create_trade_idea(request: CreateIdeaRequest):
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
async def grade_trade_idea(request: GradeIdeaRequest):
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
async def create_trade_plan(request: CreatePlanRequest):
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
async def execute_trade(idea_id: str):
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
async def review_trade(request: ReviewTradeRequest):
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
async def get_active_ideas():
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
async def get_setup_gates():
    """
    Get current EV gates for all setups.
    
    Gates determine position sizing:
    - A_SIZE: EV > 0.5R (150% size)
    - GREENLIGHT: EV > 0.2R (100% size)
    - CAUTIOUS: EV > 0R (50% size)
    - REVIEW: EV > -0.2R (25% size)
    - DROP: EV < -0.2R (don't trade)
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
