"""
Market Scanner API Router
=========================
API endpoints for market-wide strategy scanning.
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, Query
from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/market-scanner", tags=["Market Scanner"])

# Service instance (will be injected)
_market_scanner_service = None


def init_market_scanner_router(service):
    """Initialize router with the market scanner service"""
    global _market_scanner_service
    _market_scanner_service = service


# ===================== Enums & Models =====================

class TradeStyleEnum(str, Enum):
    INTRADAY = "intraday"
    SWING = "swing"
    INVESTMENT = "investment"
    ALL = "all"


class ScanFiltersModel(BaseModel):
    """Pre-filters for market scanning"""
    trade_style: TradeStyleEnum = Field(TradeStyleEnum.ALL, description="Trading style filter")
    min_adv_intraday: int = Field(500_000, description="Min ADV for intraday setups")
    min_adv_swing: int = Field(100_000, description="Min ADV for swing setups")
    min_adv_investment: int = Field(50_000, description="Min ADV for investment")
    min_rvol: float = Field(0.8, description="Minimum relative volume")
    min_price: float = Field(5.0, description="Minimum stock price")
    max_price: float = Field(500.0, description="Maximum stock price")
    min_market_cap: Optional[float] = Field(None, description="Minimum market cap")
    exclude_otc: bool = Field(True, description="Exclude OTC stocks")
    exclude_penny_stocks: bool = Field(True, description="Exclude penny stocks")
    sectors: Optional[List[str]] = Field(None, description="Filter by sectors")


class StartScanRequest(BaseModel):
    """Request to start a market scan"""
    name: Optional[str] = Field(None, description="Name for this scan")
    trade_style: TradeStyleEnum = Field(TradeStyleEnum.ALL, description="Trading style")
    strategies: Optional[List[str]] = Field(None, description="Specific strategy IDs (None = all)")
    filters: Optional[ScanFiltersModel] = Field(None, description="Pre-filters")
    run_in_background: bool = Field(True, description="Run as background job")


# ===================== Endpoints =====================

@router.get("/status")
def get_scanner_status():
    """Get market scanner service status"""
    if not _market_scanner_service:
        raise HTTPException(status_code=500, detail="Market scanner service not initialized")
    
    return _market_scanner_service.get_service_status()


@router.get("/symbols")
async def get_symbol_universe(refresh: bool = Query(False, description="Force refresh from API")):
    """
    Get the US stock universe used for scanning.
    Returns count and sample of available symbols.
    """
    if not _market_scanner_service:
        raise HTTPException(status_code=500, detail="Market scanner service not initialized")
    
    symbols = await _market_scanner_service.get_symbol_universe(refresh=refresh)
    
    return {
        "success": True,
        "total_symbols": len(symbols),
        "sample": symbols[:50],  # First 50 as sample
        "exchanges": list(set(s.get("exchange", "") for s in symbols[:500]))
    }


@router.post("/start")
async def start_market_scan(request: StartScanRequest, background_tasks: BackgroundTasks):
    """
    Start a market-wide scan for strategy signals.
    
    This scans the entire US market (or filtered subset) for trading opportunities
    based on your strategies and filters.
    
    Trade Styles:
    - intraday: Uses 500K min ADV, 5-min bars, momentum/breakout patterns
    - swing: Uses 100K min ADV, daily bars, trend/pullback patterns  
    - investment: Uses 50K min ADV, daily bars, value/growth patterns
    - all: Scans with all strategies
    """
    if not _market_scanner_service:
        raise HTTPException(status_code=500, detail="Market scanner service not initialized")
    
    from services.market_scanner_service import TradeStyle, ScanFilters
    
    # Convert request to service types
    trade_style = TradeStyle(request.trade_style.value)
    
    filters = None
    if request.filters:
        filters = ScanFilters(
            trade_style=trade_style,
            min_adv_intraday=request.filters.min_adv_intraday,
            min_adv_swing=request.filters.min_adv_swing,
            min_adv_investment=request.filters.min_adv_investment,
            min_rvol=request.filters.min_rvol,
            min_price=request.filters.min_price,
            max_price=request.filters.max_price,
            min_market_cap=request.filters.min_market_cap,
            exclude_otc=request.filters.exclude_otc,
            exclude_penny_stocks=request.filters.exclude_penny_stocks,
            sectors=request.filters.sectors
        )
    
    result = await _market_scanner_service.start_market_scan(
        name=request.name,
        trade_style=trade_style,
        strategies=request.strategies,
        filters=filters,
        run_in_background=request.run_in_background
    )
    
    return {
        "success": True,
        "scan_id": result.id,
        "status": result.status.value,
        "message": f"Scan started with {len(result.strategies_scanned)} strategies",
        "strategies": result.strategies_scanned[:10],  # First 10
        "filters": result.filters
    }


@router.get("/scan/{scan_id}")
async def get_scan_status(scan_id: str):
    """Get status and results of a market scan"""
    if not _market_scanner_service:
        raise HTTPException(status_code=500, detail="Market scanner service not initialized")
    
    result = await _market_scanner_service.get_scan_status(scan_id)
    
    if not result:
        raise HTTPException(status_code=404, detail=f"Scan {scan_id} not found")
    
    return {
        "success": True,
        "scan": result
    }


@router.get("/scan/{scan_id}/signals")
async def get_scan_signals(
    scan_id: str,
    strategy_id: Optional[str] = Query(None, description="Filter by strategy"),
    sector: Optional[str] = Query(None, description="Filter by sector"),
    min_expected_r: Optional[float] = Query(None, description="Min expected R-multiple"),
    limit: int = Query(100, description="Max results")
):
    """Get signals from a completed scan with optional filters"""
    if not _market_scanner_service:
        raise HTTPException(status_code=500, detail="Market scanner service not initialized")
    
    signals = await _market_scanner_service.get_scan_signals(
        scan_id=scan_id,
        strategy_id=strategy_id,
        sector=sector,
        min_expected_r=min_expected_r,
        limit=limit
    )
    
    return {
        "success": True,
        "scan_id": scan_id,
        "count": len(signals),
        "signals": signals
    }


@router.get("/scans")
async def list_scans(
    status: Optional[str] = Query(None, description="Filter by status"),
    trade_style: Optional[str] = Query(None, description="Filter by trade style"),
    limit: int = Query(20, description="Max results")
):
    """List recent market scans"""
    if not _market_scanner_service:
        raise HTTPException(status_code=500, detail="Market scanner service not initialized")
    
    from services.market_scanner_service import ScanStatus
    
    scan_status = None
    if status:
        try:
            scan_status = ScanStatus(status)
        except ValueError:
            pass
    
    scans = await _market_scanner_service.list_scans(
        status=scan_status,
        trade_style=trade_style,
        limit=limit
    )
    
    return {
        "success": True,
        "count": len(scans),
        "scans": scans
    }


@router.delete("/scan/{scan_id}")
async def cancel_scan(scan_id: str):
    """Cancel a running scan"""
    if not _market_scanner_service:
        raise HTTPException(status_code=500, detail="Market scanner service not initialized")
    
    cancelled = await _market_scanner_service.cancel_scan(scan_id)
    
    if not cancelled:
        raise HTTPException(status_code=404, detail=f"Scan {scan_id} not found or not running")
    
    return {
        "success": True,
        "message": f"Scan {scan_id} cancelled"
    }


@router.get("/filters/presets")
def get_filter_presets():
    """Get pre-configured filter presets for different trading styles"""
    return {
        "success": True,
        "presets": {
            "intraday": {
                "description": "Fast-moving stocks for day trading",
                "filters": {
                    "trade_style": "intraday",
                    "min_adv_intraday": 500_000,
                    "min_rvol": 0.8,
                    "min_price": 10.0,
                    "max_price": 200.0,
                    "exclude_otc": True,
                    "exclude_penny_stocks": True
                },
                "strategies_count": 47,
                "typical_hold_time": "Minutes to hours"
            },
            "swing": {
                "description": "Multi-day momentum and pattern trades",
                "filters": {
                    "trade_style": "swing",
                    "min_adv_swing": 100_000,
                    "min_rvol": 0.8,
                    "min_price": 5.0,
                    "max_price": 500.0,
                    "exclude_otc": True,
                    "exclude_penny_stocks": True
                },
                "strategies_count": 15,
                "typical_hold_time": "Days to weeks"
            },
            "investment": {
                "description": "Long-term value and growth opportunities",
                "filters": {
                    "trade_style": "investment",
                    "min_adv_investment": 50_000,
                    "min_price": 5.0,
                    "max_price": 1000.0,
                    "exclude_otc": True,
                    "exclude_penny_stocks": True
                },
                "strategies_count": 15,
                "typical_hold_time": "Weeks to years"
            },
            "aggressive_momentum": {
                "description": "High volume movers for aggressive trading",
                "filters": {
                    "trade_style": "intraday",
                    "min_adv_intraday": 1_000_000,
                    "min_rvol": 1.5,
                    "min_price": 20.0,
                    "max_price": 150.0,
                    "exclude_otc": True,
                    "exclude_penny_stocks": True
                },
                "strategies_count": 47,
                "typical_hold_time": "Minutes"
            }
        }
    }


@router.get("/sectors")
def get_available_sectors():
    """Get list of available sectors for filtering"""
    return {
        "success": True,
        "sectors": [
            "Technology",
            "Healthcare", 
            "Financial",
            "Consumer Cyclical",
            "Communication Services",
            "Industrials",
            "Consumer Defensive",
            "Energy",
            "Utilities",
            "Real Estate",
            "Basic Materials"
        ]
    }
