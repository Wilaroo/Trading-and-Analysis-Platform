"""
Chart Pattern Detection API Router
Provides endpoints for detecting chart patterns on stocks.
"""
from fastapi import APIRouter, HTTPException
from typing import List
import logging

from services.chart_pattern_service import get_chart_pattern_service

router = APIRouter(prefix="/api/patterns", tags=["Chart Patterns"])
logger = logging.getLogger(__name__)


def _ensure_initialized():
    """Ensure pattern service is initialized"""
    service = get_chart_pattern_service()
    if not service.is_initialized():
        try:
            from services.alpaca_service import get_alpaca_service
            alpaca = get_alpaca_service()
            service.set_alpaca_service(alpaca)
        except Exception as e:
            logger.warning(f"Could not initialize pattern service: {e}")
    return service


@router.get("/detect/{symbol}")
async def detect_patterns(symbol: str):
    """
    Detect all chart patterns for a symbol.
    Returns patterns sorted by quality score.
    """
    try:
        service = _ensure_initialized()
        patterns = await service.detect_patterns(symbol.upper())
        
        return {
            "success": True,
            "symbol": symbol.upper(),
            "count": len(patterns),
            "patterns": [p.to_dict() for p in patterns]
        }
    except Exception as e:
        logger.error(f"Error detecting patterns for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scan")
async def scan_multiple_symbols(symbols: List[str]):
    """
    Scan multiple symbols for chart patterns.
    Returns all detected patterns across symbols.
    """
    try:
        service = _ensure_initialized()
        all_patterns = []
        
        for symbol in symbols[:20]:  # Limit to 20 symbols
            try:
                patterns = await service.detect_patterns(symbol.upper())
                all_patterns.extend(patterns)
            except Exception as e:
                logger.warning(f"Could not scan {symbol}: {e}")
        
        # Sort by score
        all_patterns.sort(key=lambda x: x.pattern_score, reverse=True)
        
        return {
            "success": True,
            "scanned_count": len(symbols),
            "pattern_count": len(all_patterns),
            "patterns": [p.to_dict() for p in all_patterns]
        }
    except Exception as e:
        logger.error(f"Error scanning patterns: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def get_pattern_summary(symbols: str = "AAPL,MSFT,NVDA,TSLA,GOOGL"):
    """
    Get a formatted pattern summary for display.
    Used by AI assistant.
    """
    try:
        service = _ensure_initialized()
        symbol_list = [s.strip().upper() for s in symbols.split(",")]
        summary = await service.get_pattern_summary_for_ai(symbol_list)
        
        return {
            "success": True,
            "summary": summary
        }
    except Exception as e:
        logger.error(f"Error getting pattern summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))
