"""
Sector Analysis API Router
Provides endpoints for sector rotation and industry strength data.
"""
from fastapi import APIRouter, HTTPException
import logging

from services.sector_analysis_service import get_sector_analysis_service

router = APIRouter(prefix="/api/sectors", tags=["Sector Analysis"])
logger = logging.getLogger(__name__)


def _ensure_initialized():
    """Ensure sector service is initialized with Alpaca"""
    service = get_sector_analysis_service()
    if not service.is_initialized():
        try:
            from services.alpaca_service import get_alpaca_service
            alpaca = get_alpaca_service()
            service.set_alpaca_service(alpaca)
        except Exception as e:
            logger.warning(f"Could not initialize sector service: {e}")
    return service


@router.get("/rankings")
async def get_sector_rankings(force_refresh: bool = False):
    """
    Get current sector performance rankings.
    Returns all 11 S&P sectors sorted by performance.
    """
    try:
        service = _ensure_initialized()
        rankings = await service.get_sector_rankings(force_refresh)
        
        return {
            "success": True,
            "count": len(rankings),
            "sectors": [s.to_dict() for s in rankings]
        }
    except Exception as e:
        logger.error(f"Error getting sector rankings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rotation")
async def get_rotation_signals():
    """
    Get current sector rotation signals and trading implications.
    Detects risk-on/risk-off/inflation patterns.
    """
    try:
        service = _ensure_initialized()
        signals = await service.get_rotation_signals()
        
        return {
            "success": True,
            **signals
        }
    except Exception as e:
        logger.error(f"Error getting rotation signals: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/context/{symbol}")
async def get_stock_sector_context(symbol: str):
    """
    Get sector context for a specific stock.
    Returns sector strength, relative performance, and recommendation.
    """
    try:
        service = _ensure_initialized()
        
        # Ensure cache is populated first
        rankings = await service.get_sector_rankings()
        if not rankings:
            return {
                "success": False,
                "symbol": symbol.upper(),
                "message": "Sector rankings unavailable - market may be closed"
            }
        
        context = await service.get_stock_sector_context(symbol)
        
        if not context:
            # Check if symbol is in the mapping
            from services.sector_analysis_service import STOCK_SECTORS
            if symbol.upper() not in STOCK_SECTORS:
                return {
                    "success": False,
                    "symbol": symbol.upper(),
                    "message": "Symbol not in sector mapping. Try adding to STOCK_SECTORS."
                }
            return {
                "success": False,
                "symbol": symbol.upper(),
                "message": "Sector data not available for this symbol"
            }
        
        return {
            "success": True,
            **context.to_dict()
        }
    except Exception as e:
        logger.error(f"Error getting sector context for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def get_sector_summary():
    """
    Get a formatted sector summary for display.
    Used by AI assistant and market intel.
    """
    try:
        service = _ensure_initialized()
        summary = await service.get_sector_summary_for_ai()
        
        return {
            "success": True,
            "summary": summary
        }
    except Exception as e:
        logger.error(f"Error getting sector summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))
