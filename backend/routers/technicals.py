"""
Real-Time Technical Analysis API Router
Provides live technical indicators calculated from Alpaca bar data
"""
from fastapi import APIRouter, HTTPException
from typing import Optional, List
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/technicals", tags=["Real-Time Technicals"])


@router.get("/{symbol}")
async def get_technical_snapshot(symbol: str):
    """
    Get comprehensive real-time technical snapshot for a symbol.
    
    Calculates from live Alpaca bar data:
    - VWAP, EMA (9, 20, 50), SMA (200)
    - RSI (14)
    - RVOL (relative volume)
    - ATR and volatility metrics
    - Gap analysis
    - Support/Resistance levels
    - Trend determination
    - Setup indicators (rubber band extension, etc.)
    """
    try:
        from services.realtime_technical_service import get_technical_service
        
        service = get_technical_service()
        snapshot = await service.get_technical_snapshot(symbol.upper())
        
        if not snapshot:
            raise HTTPException(status_code=404, detail=f"Could not fetch technical data for {symbol}")
        
        return {
            "success": True,
            **service.snapshot_to_dict(snapshot)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting technicals: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch")
async def get_batch_technicals(symbols: List[str]):
    """
    Get technical snapshots for multiple symbols.
    More efficient for scanning multiple stocks.
    """
    if len(symbols) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 symbols per batch")
    
    try:
        from services.realtime_technical_service import get_technical_service
        
        service = get_technical_service()
        snapshots = await service.get_batch_snapshots([s.upper() for s in symbols])
        
        results = {}
        for symbol, snapshot in snapshots.items():
            results[symbol] = service.snapshot_to_dict(snapshot)
        
        return {
            "success": True,
            "count": len(results),
            "technicals": results,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting batch technicals: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{symbol}/ai-context")
async def get_technical_ai_context(symbol: str):
    """
    Get formatted technical snapshot for AI assistant context.
    Human-readable format optimized for AI consumption.
    """
    try:
        from services.realtime_technical_service import get_technical_service
        
        service = get_technical_service()
        snapshot = await service.get_technical_snapshot(symbol.upper())
        
        if not snapshot:
            return {
                "success": False,
                "context": f"Technical data unavailable for {symbol}"
            }
        
        context = service.get_snapshot_for_ai(snapshot)
        
        return {
            "success": True,
            "symbol": symbol.upper(),
            "context": context,
            "data_quality": snapshot.data_quality
        }
        
    except Exception as e:
        logger.error(f"Error getting AI context: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{symbol}/setup-check")
async def check_setup_conditions(symbol: str):
    """
    Check if a stock meets conditions for various setups.
    Returns which setups are potentially forming.
    """
    try:
        from services.realtime_technical_service import get_technical_service
        
        service = get_technical_service()
        snapshot = await service.get_technical_snapshot(symbol.upper())
        
        if not snapshot:
            raise HTTPException(status_code=404, detail=f"Could not fetch data for {symbol}")
        
        setups = []
        
        # Rubber Band Long Check
        if snapshot.dist_from_ema9 < -2.0 and snapshot.rsi_14 < 40:
            setups.append({
                "setup": "Rubber Band Long",
                "confidence": "high" if snapshot.dist_from_ema9 < -3.5 and snapshot.rvol >= 2 else "medium",
                "trigger": f"Price crosses above EMA9 (${snapshot.ema_9})",
                "reasons": [
                    f"Extended {abs(snapshot.dist_from_ema9):.1f}% below EMA9",
                    f"RSI oversold at {snapshot.rsi_14:.0f}",
                    f"RVOL: {snapshot.rvol:.1f}x"
                ]
            })
        
        # Rubber Band Short Check
        if snapshot.dist_from_ema9 > 2.5 and snapshot.rsi_14 > 65:
            setups.append({
                "setup": "Rubber Band Short",
                "confidence": "high" if snapshot.dist_from_ema9 > 4.0 and snapshot.rvol >= 2 else "medium",
                "trigger": f"Price crosses below EMA9 (${snapshot.ema_9})",
                "reasons": [
                    f"Extended {snapshot.dist_from_ema9:.1f}% above EMA9",
                    f"RSI overbought at {snapshot.rsi_14:.0f}",
                ]
            })
        
        # VWAP Bounce Check
        if -1.0 < snapshot.dist_from_vwap < 0.5 and snapshot.trend == "uptrend":
            setups.append({
                "setup": "VWAP Bounce",
                "confidence": "medium",
                "trigger": f"Bounce off VWAP (${snapshot.vwap})",
                "reasons": [
                    f"Near VWAP ({snapshot.dist_from_vwap:+.1f}%)",
                    f"Uptrend intact",
                    f"RVOL: {snapshot.rvol:.1f}x"
                ]
            })
        
        # Breakout Check
        dist_to_resistance = ((snapshot.resistance - snapshot.current_price) / snapshot.current_price) * 100
        if 0 < dist_to_resistance < 1.5 and snapshot.rvol >= 2:
            setups.append({
                "setup": "Breakout",
                "confidence": "high" if snapshot.rvol >= 3 else "medium",
                "trigger": f"Break above resistance (${snapshot.resistance})",
                "reasons": [
                    f"Near resistance ({dist_to_resistance:.1f}% away)",
                    f"High volume ({snapshot.rvol:.1f}x RVOL)",
                    f"Trend: {snapshot.trend}"
                ]
            })
        
        # Gap and Go Check
        if snapshot.gap_pct > 4 and snapshot.holding_gap and snapshot.rvol >= 3:
            setups.append({
                "setup": "Gap and Go",
                "confidence": "high" if snapshot.gap_pct > 6 else "medium",
                "trigger": "Break of opening range high",
                "reasons": [
                    f"Gapped up {snapshot.gap_pct:.1f}%",
                    f"Holding gap",
                    f"Strong volume ({snapshot.rvol:.1f}x)"
                ]
            })
        
        # In-Play Check
        is_in_play = snapshot.rvol >= 2 or abs(snapshot.gap_pct) >= 3
        in_play_reasons = []
        if snapshot.rvol >= 2:
            in_play_reasons.append(f"High RVOL ({snapshot.rvol:.1f}x)")
        if abs(snapshot.gap_pct) >= 3:
            in_play_reasons.append(f"Gapping ({snapshot.gap_pct:+.1f}%)")
        if snapshot.atr_percent >= 2:
            in_play_reasons.append(f"Good range ({snapshot.atr_percent:.1f}%)")
        
        return {
            "success": True,
            "symbol": symbol.upper(),
            "current_price": snapshot.current_price,
            "is_in_play": is_in_play,
            "in_play_reasons": in_play_reasons,
            "setups_forming": setups,
            "key_levels": {
                "vwap": snapshot.vwap,
                "ema_9": snapshot.ema_9,
                "resistance": snapshot.resistance,
                "support": snapshot.support
            },
            "technicals_summary": {
                "rvol": snapshot.rvol,
                "rsi": snapshot.rsi_14,
                "trend": snapshot.trend,
                "gap": snapshot.gap_pct
            },
            "data_quality": snapshot.data_quality
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking setups: {e}")
        raise HTTPException(status_code=500, detail=str(e))
