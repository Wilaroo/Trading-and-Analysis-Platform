"""
Strategies API Router
Endpoints for managing and querying trading strategies
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from pydantic import BaseModel, Field
from services.strategy_service import StrategyService

router = APIRouter(prefix="/api/strategies", tags=["Strategies"])

# Service instance (will be injected)
_strategy_service: Optional[StrategyService] = None


def init_strategy_service(service: StrategyService):
    """Initialize the strategy service for this router"""
    global _strategy_service
    _strategy_service = service


# ===================== Pydantic Models =====================

class StrategyCreate(BaseModel):
    id: str = Field(..., description="Unique strategy ID (e.g., INT-01, SWG-01)")
    name: str = Field(..., description="Strategy name")
    category: str = Field(..., description="Category: intraday, swing, or investment")
    criteria: List[str] = Field(..., description="List of criteria for the strategy")
    indicators: List[str] = Field(default=[], description="Technical indicators used")
    timeframe: str = Field(default="", description="Timeframe for the strategy")
    entry_rules: Optional[str] = Field(default=None, description="Entry rules")
    exit_rules: Optional[str] = Field(default=None, description="Exit rules")
    stop_loss: Optional[str] = Field(default=None, description="Stop loss rules")
    notes: Optional[str] = Field(default=None, description="Additional notes")


class StrategyUpdate(BaseModel):
    name: Optional[str] = None
    criteria: Optional[List[str]] = None
    indicators: Optional[List[str]] = None
    timeframe: Optional[str] = None
    entry_rules: Optional[str] = None
    exit_rules: Optional[str] = None
    stop_loss: Optional[str] = None
    notes: Optional[str] = None


# ===================== Endpoints =====================

@router.get("")
async def get_all_strategies(
    category: Optional[str] = Query(None, description="Filter by category: intraday, swing, investment")
):
    """Get all trading strategies or filter by category"""
    if not _strategy_service:
        raise HTTPException(status_code=500, detail="Strategy service not initialized")
    
    strategies = _strategy_service.get_all_strategies(category)
    return {"strategies": strategies, "count": len(strategies)}


@router.get("/categories")
async def get_categories():
    """Get all strategy categories"""
    if not _strategy_service:
        raise HTTPException(status_code=500, detail="Strategy service not initialized")
    
    categories = _strategy_service.get_categories()
    return {"categories": categories}


@router.get("/search")
async def search_strategies(
    q: str = Query(..., description="Search query")
):
    """Search strategies by name, criteria, or indicators"""
    if not _strategy_service:
        raise HTTPException(status_code=500, detail="Strategy service not initialized")
    
    strategies = _strategy_service.search_strategies(q)
    return {"strategies": strategies, "count": len(strategies)}


@router.get("/count")
async def get_strategy_count():
    """Get total number of strategies"""
    if not _strategy_service:
        raise HTTPException(status_code=500, detail="Strategy service not initialized")
    
    count = _strategy_service.get_strategy_count()
    return {"count": count}


@router.get("/{strategy_id}")
async def get_strategy(strategy_id: str):
    """Get specific strategy details by ID"""
    if not _strategy_service:
        raise HTTPException(status_code=500, detail="Strategy service not initialized")
    
    strategy = _strategy_service.get_strategy_by_id(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return strategy


@router.post("")
async def create_strategy(strategy: StrategyCreate):
    """Create a new strategy"""
    if not _strategy_service:
        raise HTTPException(status_code=500, detail="Strategy service not initialized")
    
    # Check if strategy already exists
    existing = _strategy_service.get_strategy_by_id(strategy.id)
    if existing:
        raise HTTPException(status_code=400, detail="Strategy with this ID already exists")
    
    success = _strategy_service.add_strategy(strategy.model_dump())
    if not success:
        raise HTTPException(status_code=500, detail="Failed to create strategy")
    
    return {"message": "Strategy created successfully", "id": strategy.id}


@router.put("/{strategy_id}")
async def update_strategy(strategy_id: str, updates: StrategyUpdate):
    """Update an existing strategy"""
    if not _strategy_service:
        raise HTTPException(status_code=500, detail="Strategy service not initialized")
    
    # Check if strategy exists
    existing = _strategy_service.get_strategy_by_id(strategy_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    # Filter out None values
    update_data = {k: v for k, v in updates.model_dump().items() if v is not None}
    
    if not update_data:
        raise HTTPException(status_code=400, detail="No updates provided")
    
    success = _strategy_service.update_strategy(strategy_id, update_data)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update strategy")
    
    return {"message": "Strategy updated successfully", "id": strategy_id}


@router.delete("/{strategy_id}")
async def delete_strategy(strategy_id: str):
    """Delete a strategy"""
    if not _strategy_service:
        raise HTTPException(status_code=500, detail="Strategy service not initialized")
    
    # Check if strategy exists
    existing = _strategy_service.get_strategy_by_id(strategy_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    success = _strategy_service.delete_strategy(strategy_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete strategy")
    
    return {"message": "Strategy deleted successfully", "id": strategy_id}


@router.post("/batch")
async def get_strategies_batch(strategy_ids: List[str]):
    """Get multiple strategies by their IDs"""
    if not _strategy_service:
        raise HTTPException(status_code=500, detail="Strategy service not initialized")
    
    strategies = _strategy_service.get_strategies_by_ids(strategy_ids)
    return {"strategies": strategies, "count": len(strategies)}
