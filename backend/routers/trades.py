"""
Trades Router - API endpoints for trade journal and performance tracking
"""
from fastapi import APIRouter, HTTPException
from typing import Optional, List
from pydantic import BaseModel

router = APIRouter(prefix="/api/trades", tags=["trades"])

# Will be initialized from main server
trade_journal_service = None

def init_trade_journal_service(service):
    global trade_journal_service
    trade_journal_service = service


class TradeCreate(BaseModel):
    symbol: str
    strategy_id: str
    strategy_name: Optional[str] = ""
    entry_price: float
    shares: float
    direction: Optional[str] = "long"
    market_context: Optional[str] = ""
    context_confidence: Optional[int] = 0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    notes: Optional[str] = ""
    tags: Optional[List[str]] = []


class TradeClose(BaseModel):
    exit_price: float
    notes: Optional[str] = ""


class TradeUpdate(BaseModel):
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    shares: Optional[float] = None


class TemplateCreate(BaseModel):
    name: str
    template_type: str = "basic"  # basic or strategy
    strategy_id: Optional[str] = ""
    strategy_name: Optional[str] = ""
    market_context: Optional[str] = ""
    direction: Optional[str] = "long"
    default_shares: Optional[float] = 100
    risk_percent: Optional[float] = 1.0
    reward_ratio: Optional[float] = 2.0
    notes: Optional[str] = ""
    is_default: Optional[bool] = False


class TemplateTradeCreate(BaseModel):
    template_id: Optional[str] = None
    symbol: str
    entry_price: float
    shares: Optional[float] = None
    direction: Optional[str] = None
    market_context: Optional[str] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    notes: Optional[str] = None


@router.post("")
async def create_trade(trade: TradeCreate):
    """Log a new trade"""
    if not trade_journal_service:
        raise HTTPException(500, "Trade journal service not initialized")
    
    result = await trade_journal_service.log_trade(trade.dict())
    return result


@router.get("")
async def get_trades(
    status: Optional[str] = None,
    strategy_id: Optional[str] = None,
    market_context: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = 50
):
    """Get trades with optional filters"""
    if not trade_journal_service:
        raise HTTPException(500, "Trade journal service not initialized")
    
    trades = await trade_journal_service.get_trades(
        status=status,
        strategy_id=strategy_id,
        market_context=market_context,
        symbol=symbol,
        limit=limit
    )
    
    return {
        "trades": trades,
        "count": len(trades)
    }


@router.get("/open")
async def get_open_trades():
    """Get all open trades"""
    if not trade_journal_service:
        raise HTTPException(500, "Trade journal service not initialized")
    
    trades = await trade_journal_service.get_trades(status="open", limit=100)
    
    return {
        "trades": trades,
        "count": len(trades)
    }


@router.get("/performance")
async def get_performance_summary():
    """Get overall trading performance summary"""
    if not trade_journal_service:
        raise HTTPException(500, "Trade journal service not initialized")
    
    summary = await trade_journal_service.get_performance_summary()
    return summary


@router.get("/performance/strategy/{strategy_id}")
async def get_strategy_performance(strategy_id: str, market_context: Optional[str] = None):
    """Get performance for a specific strategy"""
    if not trade_journal_service:
        raise HTTPException(500, "Trade journal service not initialized")
    
    perfs = await trade_journal_service.get_strategy_performance(
        strategy_id=strategy_id,
        market_context=market_context
    )
    
    return {
        "strategy_id": strategy_id,
        "performance": perfs
    }


@router.get("/performance/matrix")
async def get_strategy_context_matrix():
    """
    Get strategy-context performance matrix
    Shows which strategies perform best in which market contexts
    """
    if not trade_journal_service:
        raise HTTPException(500, "Trade journal service not initialized")
    
    matrix = await trade_journal_service.get_strategy_context_matrix()
    return matrix


@router.get("/{trade_id}")
async def get_trade(trade_id: str):
    """Get a specific trade by ID"""
    if not trade_journal_service:
        raise HTTPException(500, "Trade journal service not initialized")
    
    trade = await trade_journal_service.get_trade_by_id(trade_id)
    
    if not trade:
        raise HTTPException(404, "Trade not found")
    
    return trade


@router.post("/{trade_id}/close")
async def close_trade(trade_id: str, close_data: TradeClose):
    """Close an open trade"""
    if not trade_journal_service:
        raise HTTPException(500, "Trade journal service not initialized")
    
    try:
        result = await trade_journal_service.close_trade(
            trade_id, 
            close_data.exit_price,
            close_data.notes
        )
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.patch("/{trade_id}")
async def patch_trade(trade_id: str, updates: TradeUpdate):
    """Update an open trade (PATCH method)"""
    if not trade_journal_service:
        raise HTTPException(500, "Trade journal service not initialized")
    
    # Filter out None values
    update_dict = {k: v for k, v in updates.dict().items() if v is not None}
    
    if not update_dict:
        raise HTTPException(400, "No updates provided")
    
    result = await trade_journal_service.update_trade(trade_id, update_dict)
    return result


@router.put("/{trade_id}")
async def update_trade(trade_id: str, updates: TradeUpdate):
    """Update an open trade"""
    if not trade_journal_service:
        raise HTTPException(500, "Trade journal service not initialized")
    
    # Filter out None values
    update_dict = {k: v for k, v in updates.dict().items() if v is not None}
    
    if not update_dict:
        raise HTTPException(400, "No updates provided")
    
    result = await trade_journal_service.update_trade(trade_id, update_dict)
    return result


@router.delete("/{trade_id}")
async def delete_trade(trade_id: str):
    """Delete an open or cancelled trade"""
    if not trade_journal_service:
        raise HTTPException(500, "Trade journal service not initialized")
    
    success = await trade_journal_service.delete_trade(trade_id)
    
    if not success:
        raise HTTPException(400, "Cannot delete closed trades or trade not found")
    
    return {"success": True, "message": "Trade deleted"}


# ==================== TRADE TEMPLATES ====================

@router.get("/templates/defaults")
async def get_default_templates():
    """Get default system templates for quick trade logging"""
    if not trade_journal_service:
        raise HTTPException(500, "Trade journal service not initialized")
    
    defaults = await trade_journal_service.get_default_templates()
    return {
        "templates": defaults,
        "count": len(defaults)
    }


@router.get("/templates/list")
async def get_templates(template_type: Optional[str] = None):
    """Get all user trade templates"""
    if not trade_journal_service:
        raise HTTPException(500, "Trade journal service not initialized")
    
    user_templates = await trade_journal_service.get_templates(template_type)
    default_templates = await trade_journal_service.get_default_templates()
    
    # Combine user templates with defaults
    all_templates = default_templates + user_templates
    
    return {
        "templates": all_templates,
        "user_count": len(user_templates),
        "default_count": len(default_templates)
    }


@router.post("/templates/create")
async def create_template(template: TemplateCreate):
    """Create a new trade template"""
    if not trade_journal_service:
        raise HTTPException(500, "Trade journal service not initialized")
    
    result = await trade_journal_service.create_template(template.dict())
    return result


@router.put("/templates/{template_id}")
async def update_template(template_id: str, updates: TemplateCreate):
    """Update a trade template"""
    if not trade_journal_service:
        raise HTTPException(500, "Trade journal service not initialized")
    
    result = await trade_journal_service.update_template(template_id, updates.dict())
    
    if not result:
        raise HTTPException(404, "Template not found")
    
    return result


@router.delete("/templates/{template_id}")
async def delete_template(template_id: str):
    """Delete a trade template"""
    if not trade_journal_service:
        raise HTTPException(500, "Trade journal service not initialized")
    
    success = await trade_journal_service.delete_template(template_id)
    
    if not success:
        raise HTTPException(404, "Template not found")
    
    return {"success": True, "message": "Template deleted"}


@router.post("/from-template")
async def create_trade_from_template(trade: TemplateTradeCreate):
    """Create a trade using a template"""
    if not trade_journal_service:
        raise HTTPException(500, "Trade journal service not initialized")
    
    trade_data = {
        "symbol": trade.symbol.upper(),
        "entry_price": trade.entry_price,
    }
    
    # Add optional fields if provided
    if trade.shares is not None:
        trade_data["shares"] = trade.shares
    if trade.direction:
        trade_data["direction"] = trade.direction
    if trade.market_context:
        trade_data["market_context"] = trade.market_context
    if trade.stop_loss is not None:
        trade_data["stop_loss"] = trade.stop_loss
    if trade.take_profit is not None:
        trade_data["take_profit"] = trade.take_profit
    if trade.notes:
        trade_data["notes"] = trade.notes
    
    result = await trade_journal_service.log_trade_from_template(
        trade.template_id,
        trade_data
    )
    
    return result
