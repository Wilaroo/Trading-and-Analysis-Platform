"""
Trade History Router - Endpoints for fetching and analyzing verified trade history
"""
from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone
from typing import Optional, List
import logging

from services.ib_flex_service import ib_flex_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/trade-history", tags=["trade-history"])


@router.get("/status")
async def get_trade_history_status():
    """Check if trade history sync is configured."""
    return {
        "configured": ib_flex_service.is_configured,
        "service": "IB Flex Web Service (Kinfo)",
        "message": "Ready to sync verified trade history" if ib_flex_service.is_configured else "IB Flex credentials not configured"
    }


@router.post("/sync")
async def sync_trade_history():
    """
    Fetch latest trade history from Interactive Brokers.
    Uses the same Flex Query that Kinfo uses for verified data.
    """
    if not ib_flex_service.is_configured:
        raise HTTPException(
            status_code=400,
            detail="IB Flex Web Service not configured. Please add IB_FLEX_TOKEN and IB_FLEX_QUERY_ID to environment."
        )
    
    try:
        logger.info("Starting trade history sync from IB Flex...")
        trades = await ib_flex_service.fetch_trades()
        
        if trades is None:
            raise HTTPException(
                status_code=500,
                detail="Failed to fetch trade data from Interactive Brokers"
            )
        
        # Calculate metrics
        metrics = ib_flex_service.calculate_performance_metrics(trades)
        
        return {
            "success": True,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "trades_count": len(trades),
            "trades": trades[-50:],  # Return last 50 trades
            "performance_metrics": metrics
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Trade history sync failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance")
async def get_performance_metrics():
    """Get performance metrics from recent trade history."""
    if not ib_flex_service.is_configured:
        raise HTTPException(status_code=400, detail="IB Flex not configured")
    
    try:
        trades = await ib_flex_service.fetch_trades()
        
        if trades is None:
            raise HTTPException(status_code=500, detail="Failed to fetch trades")
        
        metrics = ib_flex_service.calculate_performance_metrics(trades)
        
        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": metrics
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get performance metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trades")
async def get_trade_history(
    symbol: Optional[str] = None,
    limit: int = 100
):
    """
    Get trade history with optional filtering.
    
    Args:
        symbol: Filter by symbol (optional)
        limit: Maximum trades to return (default 100)
    """
    if not ib_flex_service.is_configured:
        raise HTTPException(status_code=400, detail="IB Flex not configured")
    
    try:
        trades = await ib_flex_service.fetch_trades()
        
        if trades is None:
            raise HTTPException(status_code=500, detail="Failed to fetch trades")
        
        # Filter by symbol if provided
        if symbol:
            symbol_upper = symbol.upper()
            trades = [t for t in trades if 
                     symbol_upper in (t.get("symbol", "").upper() or "") or
                     symbol_upper in (t.get("underlying_symbol", "").upper() or "")]
        
        # Sort by execution time (most recent first)
        trades.sort(key=lambda x: x.get("execution_time") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        
        return {
            "success": True,
            "total": len(trades),
            "trades": trades[:limit]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get trade history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analysis/{symbol}")
async def analyze_symbol_performance(symbol: str):
    """
    Analyze trading performance for a specific symbol.
    Useful for AI coaching to understand patterns.
    """
    if not ib_flex_service.is_configured:
        raise HTTPException(status_code=400, detail="IB Flex not configured")
    
    try:
        trades = await ib_flex_service.fetch_trades()
        
        if trades is None:
            raise HTTPException(status_code=500, detail="Failed to fetch trades")
        
        # Filter for this symbol
        symbol_upper = symbol.upper()
        symbol_trades = [t for t in trades if 
                        symbol_upper in (t.get("symbol", "").upper() or "") or
                        symbol_upper in (t.get("underlying_symbol", "").upper() or "")]
        
        if not symbol_trades:
            return {
                "symbol": symbol,
                "trades_found": 0,
                "message": f"No trades found for {symbol}"
            }
        
        # Calculate symbol-specific metrics
        pnl_trades = [t for t in symbol_trades if t.get("realized_pnl")]
        winning = [t for t in pnl_trades if t["realized_pnl"] > 0]
        losing = [t for t in pnl_trades if t["realized_pnl"] < 0]
        
        total_pnl = sum(t["realized_pnl"] for t in pnl_trades)
        win_rate = (len(winning) / len(pnl_trades) * 100) if pnl_trades else 0
        
        # Time analysis
        trades_by_hour = {}
        for t in symbol_trades:
            if t.get("execution_time"):
                hour = t["execution_time"].hour
                if hour not in trades_by_hour:
                    trades_by_hour[hour] = {"count": 0, "pnl": 0}
                trades_by_hour[hour]["count"] += 1
                trades_by_hour[hour]["pnl"] += t.get("realized_pnl", 0)
        
        return {
            "symbol": symbol,
            "total_trades": len(symbol_trades),
            "closed_trades": len(pnl_trades),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": round(win_rate, 1),
            "total_pnl": round(total_pnl, 2),
            "average_pnl": round(total_pnl / len(pnl_trades), 2) if pnl_trades else 0,
            "largest_win": round(max([t["realized_pnl"] for t in winning], default=0), 2),
            "largest_loss": round(abs(min([t["realized_pnl"] for t in losing], default=0)), 2),
            "trades_by_hour": trades_by_hour,
            "recent_trades": symbol_trades[:10]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to analyze symbol: {e}")
        raise HTTPException(status_code=500, detail=str(e))
