"""
Dynamic Risk Management API Router
====================================
Endpoints for controlling and monitoring the dynamic risk engine.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict
import logging

from services.dynamic_risk_engine import get_dynamic_risk_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/dynamic-risk", tags=["Dynamic Risk"])


# ==================== REQUEST MODELS ====================

class ConfigUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    min_multiplier: Optional[float] = Field(None, ge=0.1, le=1.0)
    max_multiplier: Optional[float] = Field(None, ge=1.0, le=5.0)
    base_position_size: Optional[float] = Field(None, ge=100)
    weights: Optional[Dict[str, float]] = None
    thresholds: Optional[Dict[str, float]] = None


class OverrideRequest(BaseModel):
    multiplier: float = Field(..., ge=0.1, le=5.0)
    duration_minutes: int = Field(60, ge=1, le=1440)  # Max 24 hours
    reason: str = ""


class AssessRequest(BaseModel):
    symbol: Optional[str] = None
    setup_type: Optional[str] = None


# ==================== ENDPOINTS ====================

@router.get("/status")
def get_status():
    """
    Get current dynamic risk engine status.
    
    Returns:
        Current multiplier, risk level, and latest assessment
    """
    try:
        engine = get_dynamic_risk_engine()
        status = engine.get_status()
        return {"success": True, **status}
    except Exception as e:
        logger.error(f"Error getting dynamic risk status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config")
def get_config():
    """
    Get current dynamic risk configuration.
    
    Returns:
        All configuration parameters including weights and thresholds
    """
    try:
        engine = get_dynamic_risk_engine()
        config = engine.get_config()
        return {"success": True, "config": config}
    except Exception as e:
        logger.error(f"Error getting dynamic risk config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config")
def update_config(request: ConfigUpdateRequest):
    """
    Update dynamic risk configuration.
    
    Allows updating:
    - enabled: Turn engine on/off
    - min_multiplier: Floor for position sizing (0.1 - 1.0)
    - max_multiplier: Ceiling for position sizing (1.0 - 5.0)
    - base_position_size: Base dollar amount per position
    - weights: Factor weights (must sum to 1.0)
    - thresholds: Various threshold values
    """
    try:
        engine = get_dynamic_risk_engine()
        update_data = request.model_dump(exclude_none=True)
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No configuration provided")
        
        new_config = engine.update_config(update_data)
        return {"success": True, "config": new_config, "message": "Configuration updated"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating dynamic risk config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/toggle")
def toggle_engine():
    """
    Toggle the dynamic risk engine on/off.
    """
    try:
        engine = get_dynamic_risk_engine()
        current_config = engine.get_config()
        new_enabled = not current_config["enabled"]
        engine.update_config({"enabled": new_enabled})
        
        status = "enabled" if new_enabled else "disabled"
        return {
            "success": True,
            "enabled": new_enabled,
            "message": f"Dynamic risk engine {status}"
        }
    except Exception as e:
        logger.error(f"Error toggling dynamic risk: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/assess")
async def assess_risk(request: AssessRequest):
    """
    Perform a risk assessment for a potential trade.
    
    Args:
        symbol: Optional stock symbol for stock-specific scoring
        setup_type: Optional setup type for learning layer scoring
    
    Returns:
        Complete risk assessment with multiplier and factor breakdown
    """
    try:
        engine = get_dynamic_risk_engine()
        assessment = await engine.assess_risk(
            symbol=request.symbol,
            setup_type=request.setup_type
        )
        return {"success": True, "assessment": assessment.to_dict()}
    except Exception as e:
        logger.error(f"Error performing risk assessment: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/override")
def set_override(request: OverrideRequest):
    """
    Set a temporary override multiplier.
    
    Use this for manual intervention when you want to force a specific
    position size regardless of calculated risk.
    
    Args:
        multiplier: Override multiplier (0.1 - 5.0)
        duration_minutes: How long the override should last (1-1440 mins)
        reason: Optional reason for the override
    """
    try:
        engine = get_dynamic_risk_engine()
        result = engine.set_override(
            multiplier=request.multiplier,
            duration_minutes=request.duration_minutes,
            reason=request.reason
        )
        return {"success": True, **result}
    except Exception as e:
        logger.error(f"Error setting override: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/override")
def clear_override():
    """
    Clear any active override and return to calculated risk assessment.
    """
    try:
        engine = get_dynamic_risk_engine()
        result = engine.clear_override()
        return result
    except Exception as e:
        logger.error(f"Error clearing override: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
def get_history(limit: int = 20):
    """
    Get recent assessment history.
    
    Args:
        limit: Number of recent assessments to return (default 20)
    
    Returns:
        List of recent risk assessments
    """
    try:
        engine = get_dynamic_risk_engine()
        history = engine.get_history(limit=min(limit, 100))
        return {"success": True, "history": history, "count": len(history)}
    except Exception as e:
        logger.error(f"Error getting history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/factors")
def get_factor_summary():
    """
    Get summary statistics for each risk factor.
    
    Useful for analytics and understanding which factors are
    most impacting position sizing decisions.
    """
    try:
        engine = get_dynamic_risk_engine()
        summary = engine.get_factor_summary()
        return {"success": True, "factors": summary}
    except Exception as e:
        logger.error(f"Error getting factor summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/explain")
def explain_current():
    """
    Get a human-readable explanation of the current risk state.
    
    Useful for SentCom to explain risk decisions to the user.
    """
    try:
        engine = get_dynamic_risk_engine()
        status = engine.get_status()
        config = engine.get_config()
        
        # Build explanation
        if not config["enabled"]:
            explanation = "Dynamic risk management is currently disabled. All trades will use standard position sizing."
        elif status["override"]["active"]:
            explanation = f"Manual override is active at {status['override']['multiplier']}x sizing. Reason: {status['override']['reason'] or 'Not specified'}. Override expires at {status['override']['expiry']}."
        else:
            latest = status.get("last_assessment")
            if latest:
                explanation = latest.get("explanation", "No recent assessment available.")
                
                # Add factor details
                factor_details = []
                for f in latest.get("factors", []):
                    score_desc = "favorable" if f["score"] >= 0.6 else "neutral" if f["score"] >= 0.4 else "concerning"
                    factor_details.append(f"{f['name']}: {score_desc} ({f['score']:.0%})")
                
                if factor_details:
                    explanation += "\n\nFactor Breakdown:\n" + "\n".join(f"- {d}" for d in factor_details)
            else:
                explanation = "No risk assessment has been performed yet."
        
        return {
            "success": True,
            "explanation": explanation,
            "multiplier": status.get("current_multiplier", 1.0),
            "risk_level": status.get("current_risk_level", "normal"),
            "enabled": config["enabled"]
        }
    except Exception as e:
        logger.error(f"Error generating explanation: {e}")
        raise HTTPException(status_code=500, detail=str(e))
