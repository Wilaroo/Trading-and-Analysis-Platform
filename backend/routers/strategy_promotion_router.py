"""
Strategy Promotion Router - API endpoints for autonomous learning loop

Provides endpoints for:
- Viewing strategy phases (SIMULATION → PAPER → LIVE)
- Checking promotion candidates
- Promoting/demoting strategies
- Recording paper trades
- Getting strategy performance by phase
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List
import logging
import asyncio

from services.strategy_promotion_service import (
    get_strategy_promotion_service,
    init_strategy_promotion_service,
    StrategyPhase
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/strategy-promotion", tags=["strategy-promotion"])


def init_strategy_promotion_router(db=None):
    """Initialize the strategy promotion service"""
    init_strategy_promotion_service(db=db)


class PromoteRequest(BaseModel):
    strategy_name: str = Field(..., description="Name of the strategy to promote")
    target_phase: str = Field(..., description="Target phase: paper, live")
    force: bool = Field(False, description="Force promotion without meeting requirements")
    approved_by: str = Field("user", description="Who approved this promotion")


class PaperTradeRequest(BaseModel):
    strategy_name: str
    symbol: str
    direction: str = Field(..., description="long or short")
    entry_price: float
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    notes: str = ""


class ClosePaperTradeRequest(BaseModel):
    trade_id: str
    exit_price: float
    r_multiple: float
    outcome: str = Field(..., description="win, loss, or breakeven")


@router.get("/phases")
async def get_all_phases():
    """Get current phase for all tracked strategies"""
    try:
        service = get_strategy_promotion_service()
        phases = await asyncio.to_thread(service.get_all_phases)
        
        # Group by phase
        by_phase = {
            "simulation": [],
            "paper": [],
            "live": [],
            "demoted": [],
            "disabled": []
        }
        
        for name, phase in phases.items():
            if phase in by_phase:
                by_phase[phase].append(name)
                
        return {
            "success": True,
            "phases": phases,
            "by_phase": by_phase,
            "total_strategies": len(phases)
        }
    except Exception as e:
        logger.error(f"Error getting phases: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/phase/{strategy_name}")
def get_strategy_phase(strategy_name: str):
    """Get current phase for a specific strategy"""
    try:
        service = get_strategy_promotion_service()
        phase = service.get_strategy_phase(strategy_name)
        
        return {
            "success": True,
            "strategy_name": strategy_name,
            "phase": phase.value,
            "is_live": phase == StrategyPhase.LIVE,
            "is_paper": phase == StrategyPhase.PAPER
        }
    except Exception as e:
        logger.error(f"Error getting phase: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/candidates")
async def get_promotion_candidates():
    """
    Get strategies eligible for promotion.
    
    Returns list of candidates with performance metrics and requirements status.
    """
    try:
        service = get_strategy_promotion_service()
        candidates = await asyncio.to_thread(service.get_promotion_candidates)
        
        # Separate into ready and not-ready
        ready = [c for c in candidates if c.meets_requirements]
        not_ready = [c for c in candidates if not c.meets_requirements]
        
        return {
            "success": True,
            "ready_for_promotion": [c.to_dict() for c in ready],
            "not_ready": [c.to_dict() for c in not_ready],
            "total_candidates": len(candidates),
            "ready_count": len(ready)
        }
    except Exception as e:
        logger.error(f"Error getting promotion candidates: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/promote")
async def promote_strategy(request: PromoteRequest):
    """
    Promote a strategy to the next phase.
    
    Requires human approval for promotion to LIVE.
    """
    try:
        service = get_strategy_promotion_service()
        
        # Parse target phase
        try:
            target = StrategyPhase(request.target_phase.lower())
        except ValueError:
            return {
                "success": False,
                "error": f"Invalid phase: {request.target_phase}. Use: simulation, paper, live"
            }
            
        result = await asyncio.to_thread(
            service.promote_strategy,
            strategy_name=request.strategy_name,
            target_phase=target,
            force=request.force,
            approved_by=request.approved_by
        )
        
        return result
    except Exception as e:
        logger.error(f"Error promoting strategy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/demote/{strategy_name}")
async def demote_strategy(
    strategy_name: str,
    reason: str = Query("Performance degradation", description="Reason for demotion")
):
    """Demote a strategy to a lower phase"""
    try:
        service = get_strategy_promotion_service()
        result = await asyncio.to_thread(service.demote_strategy, strategy_name, reason)
        return result
    except Exception as e:
        logger.error(f"Error demoting strategy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance/{strategy_name}")
async def get_strategy_performance(
    strategy_name: str,
    phase: Optional[str] = Query(None, description="Phase to check (default: current)"),
    days: int = Query(30, description="Days of history to analyze")
):
    """Get performance metrics for a strategy in a specific phase"""
    try:
        service = get_strategy_promotion_service()
        
        phase_enum = None
        if phase:
            try:
                phase_enum = StrategyPhase(phase.lower())
            except ValueError:
                return {"success": False, "error": f"Invalid phase: {phase}"}
                
        perf = await asyncio.to_thread(service.get_strategy_performance, strategy_name, phase_enum, days)
        
        return {
            "success": True,
            "performance": perf.to_dict()
        }
    except Exception as e:
        logger.error(f"Error getting performance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/paper-trade")
async def record_paper_trade(request: PaperTradeRequest):
    """Record a paper trade for a strategy in PAPER phase"""
    try:
        service = get_strategy_promotion_service()
        
        # Verify strategy is in paper phase
        phase = service.get_strategy_phase(request.strategy_name)
        if phase != StrategyPhase.PAPER:
            return {
                "success": False,
                "error": f"Strategy is in {phase.value} phase, not PAPER"
            }
            
        trade_id = await asyncio.to_thread(service.record_paper_trade,
            strategy_name=request.strategy_name,
            symbol=request.symbol,
            direction=request.direction,
            entry_price=request.entry_price,
            stop_price=request.stop_price,
            target_price=request.target_price,
            notes=request.notes
        )
        
        return {
            "success": True,
            "trade_id": trade_id,
            "message": f"Paper trade recorded for {request.strategy_name}"
        }
    except Exception as e:
        logger.error(f"Error recording paper trade: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/paper-trade/close")
async def close_paper_trade(request: ClosePaperTradeRequest):
    """Close an open paper trade"""
    try:
        service = get_strategy_promotion_service()
        
        await asyncio.to_thread(service.close_paper_trade,
            trade_id=request.trade_id,
            exit_price=request.exit_price,
            r_multiple=request.r_multiple,
            outcome=request.outcome
        )
        
        return {
            "success": True,
            "trade_id": request.trade_id,
            "outcome": request.outcome,
            "r_multiple": request.r_multiple
        }
    except Exception as e:
        logger.error(f"Error closing paper trade: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/should-execute/{strategy_name}")
def should_execute_trade(strategy_name: str):
    """
    Check if a trade should be executed for real.
    
    Returns whether to execute, paper track, or skip.
    """
    try:
        service = get_strategy_promotion_service()
        should_execute, reason, should_paper = service.should_execute_trade(strategy_name)
        
        return {
            "success": True,
            "strategy_name": strategy_name,
            "should_execute": should_execute,
            "should_paper_track": should_paper,
            "reason": reason,
            "current_phase": service.get_strategy_phase(strategy_name).value
        }
    except Exception as e:
        logger.error(f"Error checking execution: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/set-phase/{strategy_name}")
def set_strategy_phase_manual(
    strategy_name: str,
    phase: str = Query(..., description="Target phase: simulation, paper, live, demoted, disabled"),
    reason: str = Query("Manual override", description="Reason for change")
):
    """Manually set a strategy's phase (admin function)"""
    try:
        service = get_strategy_promotion_service()
        
        try:
            phase_enum = StrategyPhase(phase.lower())
        except ValueError:
            return {"success": False, "error": f"Invalid phase: {phase}"}
            
        service.set_strategy_phase(strategy_name, phase_enum, reason)
        
        return {
            "success": True,
            "strategy_name": strategy_name,
            "new_phase": phase_enum.value,
            "reason": reason
        }
    except Exception as e:
        logger.error(f"Error setting phase: {e}")
        raise HTTPException(status_code=500, detail=str(e))
