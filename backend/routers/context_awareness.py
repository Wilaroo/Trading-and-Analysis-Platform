"""
Context Awareness API Router
Exposes the Phase 2 AI context awareness service via REST API.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, List, Any
import logging

from services.context_awareness_service import (
    get_context_awareness_service,
    ContextAwarenessService,
    TradingSession
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/context", tags=["context"])

# Module-level service reference
_context_service: Optional[ContextAwarenessService] = None


def init_context_router(context_service: ContextAwarenessService):
    """Initialize the context router with the service."""
    global _context_service
    _context_service = context_service
    logger.info("Context Awareness router initialized")


class SessionContextResponse(BaseModel):
    """Response model for session context"""
    session: str
    session_name: str
    time_until_next_session: str
    trading_advice: str
    risk_level: str
    strategy_suggestions: List[str]
    avoid_strategies: List[str]


class RegimeContextResponse(BaseModel):
    """Response model for regime context"""
    state: str
    score: float
    risk_level: float
    confidence: float
    recommendation: str
    position_sizing_multiplier: float
    favored_strategies: List[str]


class PositionContextResponse(BaseModel):
    """Response model for position context"""
    has_positions: bool
    position_count: int
    total_exposure: float
    long_exposure: float
    short_exposure: float
    unrealized_pnl: float
    largest_position: Optional[Dict] = None
    at_risk_positions: List[Dict]
    profitable_positions: List[Dict]
    concentration_warning: Optional[str] = None


class FullContextResponse(BaseModel):
    """Response model for full context"""
    session: SessionContextResponse
    regime: RegimeContextResponse
    positions: PositionContextResponse
    combined_advice: str
    risk_factors: List[str]
    opportunities: List[str]


@router.get("/session", response_model=SessionContextResponse)
def get_session_context():
    """
    Get the current trading session context.
    
    Returns time-of-day awareness:
    - Current session (pre-market, open, midday, close, after-hours)
    - Session-specific trading advice
    - Risk level for the current period
    - Strategy suggestions and things to avoid
    """
    service = _context_service or get_context_awareness_service()
    
    try:
        ctx = service.get_session_context()
        return SessionContextResponse(
            session=ctx.session.value,
            session_name=ctx.session_name,
            time_until_next_session=ctx.time_until_next_session,
            trading_advice=ctx.trading_advice,
            risk_level=ctx.risk_level,
            strategy_suggestions=ctx.strategy_suggestions,
            avoid_strategies=ctx.avoid_strategies
        )
    except Exception as e:
        logger.error(f"Error getting session context: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/regime", response_model=RegimeContextResponse)
async def get_regime_context():
    """
    Get the current market regime context.
    
    Returns regime-aware data:
    - Current market state (RISK_ON, CAUTION, RISK_OFF, CONFIRMED_DOWN)
    - Composite score and confidence
    - Position sizing multiplier recommendation
    - Favored strategies for the current regime
    """
    service = _context_service or get_context_awareness_service()
    
    try:
        ctx = await service.get_regime_context()
        return RegimeContextResponse(
            state=ctx.state,
            score=ctx.score,
            risk_level=ctx.risk_level,
            confidence=ctx.confidence,
            recommendation=ctx.recommendation,
            position_sizing_multiplier=ctx.position_sizing_multiplier,
            favored_strategies=ctx.favored_strategies
        )
    except Exception as e:
        logger.error(f"Error getting regime context: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/positions", response_model=PositionContextResponse)
async def get_position_context():
    """
    Get the current position context.
    
    Returns position-aware data:
    - Open position count and exposure
    - Long/short breakdown
    - Unrealized P&L
    - At-risk and profitable positions
    - Concentration warnings
    """
    service = _context_service or get_context_awareness_service()
    
    try:
        ctx = await service.get_position_context()
        return PositionContextResponse(
            has_positions=ctx.has_positions,
            position_count=ctx.position_count,
            total_exposure=ctx.total_exposure,
            long_exposure=ctx.long_exposure,
            short_exposure=ctx.short_exposure,
            unrealized_pnl=ctx.unrealized_pnl,
            largest_position=ctx.largest_position,
            at_risk_positions=ctx.at_risk_positions,
            profitable_positions=ctx.profitable_positions,
            concentration_warning=ctx.concentration_warning
        )
    except Exception as e:
        logger.error(f"Error getting position context: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/full", response_model=FullContextResponse)
async def get_full_context():
    """
    Get the complete trading context.
    
    Combines all context types:
    - Session (time-of-day)
    - Regime (market conditions)
    - Positions (user's holdings)
    
    Plus:
    - Combined advice
    - Risk factors to watch
    - Current opportunities
    """
    service = _context_service or get_context_awareness_service()
    
    try:
        ctx = await service.get_full_context()
        return FullContextResponse(
            session=SessionContextResponse(
                session=ctx.session.session.value,
                session_name=ctx.session.session_name,
                time_until_next_session=ctx.session.time_until_next_session,
                trading_advice=ctx.session.trading_advice,
                risk_level=ctx.session.risk_level,
                strategy_suggestions=ctx.session.strategy_suggestions,
                avoid_strategies=ctx.session.avoid_strategies
            ),
            regime=RegimeContextResponse(
                state=ctx.regime.state,
                score=ctx.regime.score,
                risk_level=ctx.regime.risk_level,
                confidence=ctx.regime.confidence,
                recommendation=ctx.regime.recommendation,
                position_sizing_multiplier=ctx.regime.position_sizing_multiplier,
                favored_strategies=ctx.regime.favored_strategies
            ),
            positions=PositionContextResponse(
                has_positions=ctx.positions.has_positions,
                position_count=ctx.positions.position_count,
                total_exposure=ctx.positions.total_exposure,
                long_exposure=ctx.positions.long_exposure,
                short_exposure=ctx.positions.short_exposure,
                unrealized_pnl=ctx.positions.unrealized_pnl,
                largest_position=ctx.positions.largest_position,
                at_risk_positions=ctx.positions.at_risk_positions,
                profitable_positions=ctx.positions.profitable_positions,
                concentration_warning=ctx.positions.concentration_warning
            ),
            combined_advice=ctx.combined_advice,
            risk_factors=ctx.risk_factors,
            opportunities=ctx.opportunities
        )
    except Exception as e:
        logger.error(f"Error getting full context: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prompt")
async def get_context_for_prompt():
    """
    Get formatted context string for AI prompts.
    
    Returns the context in a format ready to inject into LLM prompts.
    This is what the AI agents use internally for context-aware responses.
    """
    service = _context_service or get_context_awareness_service()
    
    try:
        context_str = await service.get_context_for_prompt()
        return {"context": context_str}
    except Exception as e:
        logger.error(f"Error getting prompt context: {e}")
        raise HTTPException(status_code=500, detail=str(e))
