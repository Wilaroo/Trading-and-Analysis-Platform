"""
Advanced Alert System API Router
Endpoints for organized trade alerts by timeframe (scalp, intraday, swing, position)
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/alerts", tags=["Trade Alerts"])

# Service instance
_alert_system = None


def init_alerts_router(alert_system):
    """Initialize router with alert system"""
    global _alert_system
    _alert_system = alert_system


# ===================== Models =====================

class ScanRequest(BaseModel):
    symbols: Optional[List[str]] = Field(default=None, description="Symbols to scan")
    include_scalp: bool = Field(default=True)
    include_intraday: bool = Field(default=True)
    include_swing: bool = Field(default=True)
    include_position: bool = Field(default=False)


# ===================== Endpoints =====================

@router.post("/scan")
async def scan_all_alerts(request: ScanRequest):
    """
    Scan for all trade setups organized by timeframe.
    
    Returns alerts organized into:
    - Scalp: Setting up now / On watch today
    - Intraday: Setting up now / On watch today  
    - Swing: Setting up today / Setting up this week
    - Position: Long-term setups
    
    Each alert includes:
    - In-play qualification (for scalps)
    - Timeframe-adjusted scores
    - Detailed reasoning
    - Trade plan with entry/stop/targets
    """
    if not _alert_system:
        raise HTTPException(status_code=500, detail="Alert system not initialized")
    
    try:
        results = await _alert_system.scan_all_setups(
            symbols=request.symbols,
            include_scalp=request.include_scalp,
            include_intraday=request.include_intraday,
            include_swing=request.include_swing,
            include_position=request.include_position
        )
        
        # Convert to response format
        response = {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scalp": {
                "setting_up_now": [_format_alert(a) for a in results["scalp_now"][:5]],
                "on_watch_today": [_format_alert(a) for a in results["scalp_watch"][:5]]
            },
            "intraday": {
                "setting_up_now": [_format_alert(a) for a in results["intraday_now"][:5]],
                "on_watch_today": [_format_alert(a) for a in results["intraday_watch"][:5]]
            },
            "swing": {
                "setting_up_today": [_format_alert(a) for a in results["swing_today"][:5]],
                "setting_up_this_week": [_format_alert(a) for a in results["swing_week"][:5]]
            },
            "position": [_format_alert(a) for a in results["position"][:3]],
            "summary": {
                "scalp_now_count": len(results["scalp_now"]),
                "scalp_watch_count": len(results["scalp_watch"]),
                "intraday_count": len(results["intraday_now"]) + len(results["intraday_watch"]),
                "swing_count": len(results["swing_today"]) + len(results["swing_week"]),
            }
        }
        
        return response
        
    except Exception as e:
        logger.error(f"Error scanning alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scalp")
async def get_scalp_alerts():
    """
    Get scalp trading alerts.
    
    Organized into:
    - Setting up now: Ready for immediate scalp
    - On watch today: Developing, watch for trigger
    
    Only stocks that qualify as "in play" are included.
    """
    if not _alert_system:
        raise HTTPException(status_code=500, detail="Alert system not initialized")
    
    alerts = _alert_system.get_scalp_alerts()
    
    return {
        "success": True,
        "timeframe": "scalp",
        "setting_up_now": [_format_alert(a) for a in alerts["setting_up_now"]],
        "on_watch_today": [_format_alert(a) for a in alerts["on_watch_today"]],
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/swing")
async def get_swing_alerts():
    """
    Get swing trading alerts.
    
    Organized into:
    - Setting up today: Ready to trigger today
    - Setting up this week: Developing over days
    
    Fundamentals weighted more heavily for swing trades.
    """
    if not _alert_system:
        raise HTTPException(status_code=500, detail="Alert system not initialized")
    
    alerts = _alert_system.get_swing_alerts()
    
    return {
        "success": True,
        "timeframe": "swing",
        "setting_up_today": [_format_alert(a) for a in alerts["setting_up_today"]],
        "setting_up_this_week": [_format_alert(a) for a in alerts["setting_up_this_week"]],
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/summary")
async def get_alerts_summary():
    """
    Get a quick summary of all active alerts for dashboard display.
    """
    if not _alert_system:
        raise HTTPException(status_code=500, detail="Alert system not initialized")
    
    scalp = _alert_system.get_scalp_alerts()
    swing = _alert_system.get_swing_alerts()
    
    best_scalps = []
    for alert in scalp["setting_up_now"][:3]:
        best_scalps.append({
            "symbol": alert.symbol,
            "setup": alert.setup_type,
            "direction": alert.direction,
            "score": alert.overall_score,
            "win_prob": round(alert.win_probability, 2)
        })
    
    best_swings = []
    for alert in swing["setting_up_today"][:3]:
        best_swings.append({
            "symbol": alert.symbol,
            "setup": alert.setup_type,
            "direction": alert.direction,
            "score": alert.overall_score,
            "fundamental_score": alert.fundamental_score
        })
    
    return {
        "success": True,
        "scalp_count": len(scalp["setting_up_now"]) + len(scalp["on_watch_today"]),
        "swing_count": len(swing["setting_up_today"]) + len(swing["setting_up_this_week"]),
        "best_scalps": best_scalps,
        "best_swings": best_swings,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/ai-context")
async def get_ai_context():
    """
    Get formatted alert context for AI assistant integration.
    """
    if not _alert_system:
        raise HTTPException(status_code=500, detail="Alert system not initialized")
    
    context = _alert_system.get_alerts_summary_for_ai()
    
    return {
        "success": True,
        "context": context,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.post("/check-in-play/{symbol}")
async def check_in_play_status(symbol: str):
    """
    Check if a specific stock qualifies as "in play" for scalping.
    
    A stock is in play if it has:
    - High relative volume (2x+)
    - Gapping or breaking key levels
    - News/catalyst driving movement
    - Good daily range for scalping
    """
    if not _alert_system:
        raise HTTPException(status_code=500, detail="Alert system not initialized")
    
    try:
        market_data = await _alert_system._get_enhanced_market_data(symbol.upper())
        if not market_data:
            raise HTTPException(status_code=404, detail=f"Could not fetch data for {symbol}")
        
        in_play = await _alert_system.check_in_play(symbol.upper(), market_data)
        
        return {
            "success": True,
            "symbol": symbol.upper(),
            "is_in_play": in_play.is_in_play,
            "score": in_play.score,
            "reasons": in_play.reasons,
            "disqualifiers": in_play.disqualifiers,
            "metrics": {
                "rvol": in_play.rvol,
                "gap_pct": in_play.gap_pct,
                "atr_pct": in_play.atr_pct,
                "has_catalyst": in_play.has_catalyst,
                "short_interest": in_play.short_interest
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking in-play status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scoring-weights")
async def get_scoring_weights():
    """
    Get the scoring weights used for each timeframe.
    Shows how fundamentals vs technicals are weighted differently.
    """
    from services.alert_system import TIMEFRAME_WEIGHTS, AlertTimeframe
    
    weights = {}
    for tf in AlertTimeframe:
        weights[tf.value] = TIMEFRAME_WEIGHTS[tf]
    
    return {
        "success": True,
        "weights": weights,
        "explanation": {
            "scalp": "Heavy technical focus (50%), minimal fundamentals (5%) - price action is king",
            "intraday": "Still technical-focused (45%), slight fundamental consideration (10%)",
            "swing": "Balanced approach - fundamentals matter more (25%), regime trends important (17%)",
            "position": "Fundamental-heavy (35%), long-term regime crucial (25%) - business quality matters"
        }
    }


def _format_alert(alert) -> Dict:
    """Format alert for API response"""
    return {
        "id": alert.id,
        "symbol": alert.symbol,
        "setup_type": alert.setup_type,
        "setup_name": alert.setup_type.replace("_", " ").title(),
        "direction": alert.direction,
        "timeframe": alert.timeframe.value,
        "urgency": alert.urgency.value,
        "in_play": {
            "is_in_play": alert.in_play.is_in_play if alert.in_play else None,
            "score": alert.in_play.score if alert.in_play else None,
            "reasons": alert.in_play.reasons[:3] if alert.in_play else []
        } if alert.in_play else None,
        "scores": {
            "overall": alert.overall_score,
            "technical": alert.technical_score,
            "fundamental": alert.fundamental_score,
            "catalyst": alert.catalyst_score,
            "regime": alert.regime_score
        },
        "probabilities": {
            "trigger": round(alert.trigger_probability, 3),
            "win": round(alert.win_probability, 3),
            "expected_value": alert.expected_value
        },
        "trade_plan": {
            "current_price": alert.current_price,
            "entry_zone": alert.entry_zone,
            "stop_loss": alert.stop_loss,
            "target_1": alert.target_1,
            "target_2": alert.target_2,
            "target_3": alert.target_3,
            "risk_reward": alert.risk_reward
        },
        "timing": {
            "estimated_trigger": alert.estimated_trigger_time,
            "minutes_to_trigger": alert.minutes_to_trigger
        },
        "reasoning": {
            "summary": alert.reasoning.summary,
            "technical_reasons": alert.reasoning.technical_reasons,
            "fundamental_reasons": alert.reasoning.fundamental_reasons,
            "catalyst_reasons": alert.reasoning.catalyst_reasons,
            "risk_factors": alert.reasoning.risk_factors,
            "trade_plan": alert.reasoning.trade_plan
        },
        "created_at": alert.created_at
    }
