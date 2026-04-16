"""
Slow Learning Router - Phase 6 APIs

Endpoints for backtesting, historical data, and shadow mode.
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional, List
from pydantic import BaseModel
import logging

from services.slow_learning.historical_data_service import get_historical_data_service
from services.slow_learning.backtest_engine import get_backtest_engine, BacktestConfig
from services.slow_learning.shadow_mode_service import get_shadow_mode_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/slow-learning", tags=["Slow Learning - Phase 6"])


# ==================== PYDANTIC MODELS ====================

class HistoricalDataRequest(BaseModel):
    symbol: str
    timeframe: str = "1Day"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    days_back: int = 365


class BacktestRequest(BaseModel):
    symbol: str
    timeframe: str = "1Day"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    name: Optional[str] = None
    
    # Config
    starting_capital: float = 100000.0
    max_position_size_pct: float = 10.0
    max_concurrent_positions: int = 5
    default_stop_pct: float = 2.0
    default_target_pct: float = 4.0
    use_trailing_stop: bool = False
    trailing_stop_pct: float = 1.5
    min_tqs_score: float = 60.0
    min_volume: int = 100000
    min_price: float = 5.0
    max_price: float = 500.0
    max_bars_to_hold: int = 20


class ShadowFilterCreate(BaseModel):
    name: str
    description: str
    filter_type: str
    criteria: dict = {}


class ShadowSignalCreate(BaseModel):
    symbol: str
    direction: str = "long"
    setup_type: str
    signal_price: float
    stop_price: float
    target_price: float
    filter_id: Optional[str] = None
    tqs_score: float = 0
    market_regime: str = ""
    confirmations: List[str] = []
    notes: str = ""


# ==================== HISTORICAL DATA ENDPOINTS ====================

@router.post("/historical/download")
async def download_historical_data(request: HistoricalDataRequest):
    """
    Download and store historical data for a symbol.
    
    Data is fetched from Alpaca and stored in MongoDB for backtesting.
    """
    service = get_historical_data_service()
    result = await service.download_historical_data(
        symbol=request.symbol,
        timeframe=request.timeframe,
        start_date=request.start_date,
        end_date=request.end_date,
        days_back=request.days_back
    )
    return result


@router.get("/historical/bars/{symbol}")
async def get_historical_bars(
    symbol: str,
    timeframe: str = Query("1Day"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit: Optional[int] = Query(None)
):
    """Get stored historical bars for a symbol"""
    service = get_historical_data_service()
    bars = await service.get_bars(
        symbol=symbol,
        timeframe=timeframe,
        start_date=start_date,
        end_date=end_date,
        limit=limit
    )
    return {"success": True, "bars": bars, "count": len(bars)}


@router.get("/historical/stats")
async def get_historical_stats(symbol: Optional[str] = Query(None)):
    """Get statistics about stored historical data"""
    service = get_historical_data_service()
    stats = await service.get_data_stats(symbol)
    return {"success": True, "stats": [s.to_dict() for s in stats]}


@router.get("/historical/symbols")
async def get_available_symbols():
    """Get list of symbols with stored historical data"""
    service = get_historical_data_service()
    symbols = await service.get_available_symbols()
    return {"success": True, "symbols": symbols}


@router.delete("/historical/{symbol}")
async def delete_historical_data(
    symbol: str,
    timeframe: Optional[str] = Query(None)
):
    """Delete stored historical data for a symbol"""
    service = get_historical_data_service()
    result = await service.delete_data(symbol, timeframe)
    return result


# ==================== BACKTEST ENDPOINTS ====================

@router.post("/backtest/run")
async def run_backtest(request: BacktestRequest):
    """
    Run a backtest on historical data.
    
    Uses stored historical data or fetches from Alpaca if not available.
    """
    engine = get_backtest_engine()
    
    # Build config
    config = BacktestConfig(
        starting_capital=request.starting_capital,
        max_position_size_pct=request.max_position_size_pct,
        max_concurrent_positions=request.max_concurrent_positions,
        default_stop_pct=request.default_stop_pct,
        default_target_pct=request.default_target_pct,
        use_trailing_stop=request.use_trailing_stop,
        trailing_stop_pct=request.trailing_stop_pct,
        min_tqs_score=request.min_tqs_score,
        min_volume=request.min_volume,
        min_price=request.min_price,
        max_price=request.max_price,
        max_bars_to_hold=request.max_bars_to_hold
    )
    
    result = await engine.run_backtest(
        symbol=request.symbol,
        timeframe=request.timeframe,
        start_date=request.start_date,
        end_date=request.end_date,
        config=config,
        name=request.name
    )
    
    return {"success": True, "result": result.to_dict()}


@router.get("/backtest/results")
async def get_backtest_results(
    symbol: Optional[str] = Query(None),
    limit: int = Query(20)
):
    """Get stored backtest results"""
    engine = get_backtest_engine()
    results = await engine.get_backtest_results(symbol, limit)
    return {
        "success": True,
        "results": [r.to_dict() for r in results],
        "count": len(results)
    }


@router.get("/backtest/results/{backtest_id}")
async def get_backtest_result(backtest_id: str):
    """Get a specific backtest result"""
    engine = get_backtest_engine()
    result = await engine.get_backtest_result(backtest_id)
    if not result:
        raise HTTPException(status_code=404, detail="Backtest not found")
    return {"success": True, "result": result.to_dict()}


@router.delete("/backtest/results/{backtest_id}")
async def delete_backtest(backtest_id: str):
    """Delete a backtest result"""
    engine = get_backtest_engine()
    success = await engine.delete_backtest(backtest_id)
    if not success:
        raise HTTPException(status_code=404, detail="Backtest not found")
    return {"success": True, "message": "Backtest deleted"}


# ==================== SHADOW MODE ENDPOINTS ====================

@router.post("/shadow/filters")
async def create_shadow_filter(request: ShadowFilterCreate):
    """Create a new filter to test in shadow mode"""
    service = get_shadow_mode_service()
    filter_obj = await service.create_filter(
        name=request.name,
        description=request.description,
        filter_type=request.filter_type,
        criteria=request.criteria
    )
    return {"success": True, "filter": filter_obj.to_dict()}


@router.get("/shadow/filters")
async def get_shadow_filters(active_only: bool = Query(True)):
    """Get all shadow filters"""
    service = get_shadow_mode_service()
    filters = await service.get_all_filters(active_only)
    return {
        "success": True,
        "filters": [f.to_dict() for f in filters],
        "count": len(filters)
    }


@router.get("/shadow/filters/{filter_id}")
async def get_shadow_filter(filter_id: str):
    """Get a specific shadow filter"""
    service = get_shadow_mode_service()
    filter_obj = await service.get_filter(filter_id)
    if not filter_obj:
        raise HTTPException(status_code=404, detail="Filter not found")
    return {"success": True, "filter": filter_obj.to_dict()}


@router.post("/shadow/filters/{filter_id}/validate")
async def validate_shadow_filter(filter_id: str):
    """Validate a shadow filter based on accumulated signals"""
    service = get_shadow_mode_service()
    result = await service.validate_filter(filter_id)
    return {"success": True, **result}


@router.post("/shadow/filters/{filter_id}/deactivate")
async def deactivate_shadow_filter(filter_id: str):
    """Deactivate a shadow filter"""
    service = get_shadow_mode_service()
    success = await service.deactivate_filter(filter_id)
    if not success:
        raise HTTPException(status_code=404, detail="Filter not found")
    return {"success": True, "message": "Filter deactivated"}


@router.post("/shadow/signals")
async def record_shadow_signal(request: ShadowSignalCreate):
    """Record a shadow (paper) trading signal"""
    service = get_shadow_mode_service()
    signal = await service.record_signal(
        symbol=request.symbol,
        direction=request.direction,
        setup_type=request.setup_type,
        signal_price=request.signal_price,
        stop_price=request.stop_price,
        target_price=request.target_price,
        filter_id=request.filter_id,
        tqs_score=request.tqs_score,
        market_regime=request.market_regime,
        confirmations=request.confirmations,
        notes=request.notes
    )
    return {"success": True, "signal": signal.to_dict()}


@router.get("/shadow/signals")
async def get_shadow_signals(
    filter_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    limit: int = Query(50)
):
    """Get shadow signals with optional filters"""
    service = get_shadow_mode_service()
    signals = await service.get_signals(
        filter_id=filter_id,
        status=status,
        symbol=symbol,
        limit=limit
    )
    return {
        "success": True,
        "signals": [s.to_dict() for s in signals],
        "count": len(signals)
    }


@router.post("/shadow/update-outcomes")
async def update_shadow_outcomes():
    """Update pending shadow signals with current price outcomes"""
    service = get_shadow_mode_service()
    result = await service.update_signal_outcomes()
    return {"success": True, **result}


@router.get("/shadow/report")
async def get_shadow_report(days: int = Query(30)):
    """Generate shadow mode performance report"""
    service = get_shadow_mode_service()
    report = await service.generate_report(days)
    return {"success": True, "report": report.to_dict()}


# ==================== STATUS ENDPOINT ====================

@router.get("/status")
def get_slow_learning_status():
    """Get status of all Slow Learning services"""
    return {
        "success": True,
        "services": {
            "historical_data": get_historical_data_service().get_service_stats(),
            "backtest_engine": get_backtest_engine().get_service_stats(),
            "shadow_mode": get_shadow_mode_service().get_service_stats()
        }
    }
