"""
Alerts Endpoints for IB Router

Handles price alerts and enhanced alerts functionality.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from typing import Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["IB Alerts"])

# Service references (will be set during init)
_ib_service = None
_alpaca_service = None

# In-memory storage for price alerts
_price_alerts = {}
_triggered_alerts = []


def init_alert_services(ib_service, alpaca_service):
    """Initialize the services for this router"""
    global _ib_service, _alpaca_service
    _ib_service = ib_service
    _alpaca_service = alpaca_service


class PriceAlertRequest(BaseModel):
    symbol: str = Field(..., description="Stock symbol")
    target_price: float = Field(..., description="Target price to trigger alert")
    direction: str = Field(..., description="ABOVE or BELOW")
    note: Optional[str] = Field(default=None, description="Optional note for the alert")


# ===================== PRICE ALERTS =====================

@router.post("/alerts/price")
def create_price_alert(request: PriceAlertRequest):
    """Create a new price alert"""
    alert_id = f"{request.symbol}_{request.direction}_{request.target_price}_{datetime.now().timestamp()}"
    
    alert = {
        "id": alert_id,
        "symbol": request.symbol.upper(),
        "target_price": request.target_price,
        "direction": request.direction.upper(),
        "note": request.note,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "triggered": False
    }
    
    _price_alerts[alert_id] = alert
    return {"status": "created", "alert": alert}


@router.get("/alerts/price")
def get_price_alerts():
    """Get all active price alerts"""
    return {
        "alerts": list(_price_alerts.values()),
        "count": len(_price_alerts)
    }


@router.get("/alerts/price/check")
async def check_price_alerts():
    """
    Check all price alerts against current prices.
    Returns triggered alerts.
    """
    triggered = []
    
    if not _price_alerts:
        return {"triggered": [], "count": 0}
    
    # Get unique symbols
    symbols = list(set(a["symbol"] for a in _price_alerts.values()))
    
    # Get current prices - use Alpaca first
    current_prices = {}
    if _alpaca_service:
        try:
            alpaca_quotes = await _alpaca_service.get_quotes_batch(symbols)
            current_prices = {s: q.get("price", 0) for s, q in alpaca_quotes.items()}
        except:
            pass
    
    # Fallback to IB if needed
    if not current_prices and _ib_service:
        try:
            status = _ib_service.get_connection_status()
            if status.get("connected"):
                quotes = await _ib_service.get_quotes_batch(symbols)
                current_prices = {q["symbol"]: q.get("price", 0) for q in quotes}
        except:
            pass
    
    # Check each alert
    for alert_id, alert in list(_price_alerts.items()):
        symbol = alert["symbol"]
        current_price = current_prices.get(symbol, 0)
        
        if current_price <= 0:
            continue
        
        target = alert["target_price"]
        direction = alert["direction"]
        
        is_triggered = False
        if direction == "ABOVE" and current_price >= target:
            is_triggered = True
        elif direction == "BELOW" and current_price <= target:
            is_triggered = True
        
        if is_triggered:
            alert["triggered"] = True
            alert["triggered_at"] = datetime.now(timezone.utc).isoformat()
            alert["triggered_price"] = current_price
            triggered.append(alert)
            _triggered_alerts.append(alert)
            del _price_alerts[alert_id]
    
    return {
        "triggered": triggered,
        "count": len(triggered),
        "active_alerts": len(_price_alerts)
    }


@router.delete("/alerts/price/{alert_id}")
def delete_price_alert(alert_id: str):
    """Delete a price alert"""
    if alert_id in _price_alerts:
        del _price_alerts[alert_id]
        return {"status": "deleted", "alert_id": alert_id}
    return {"status": "not_found", "alert_id": alert_id}


@router.get("/alerts/price/history")
def get_triggered_alerts_history():
    """Get history of triggered alerts"""
    return {
        "triggered": _triggered_alerts[-50:],  # Last 50 triggered alerts
        "count": len(_triggered_alerts)
    }


# ===================== ENHANCED ALERTS =====================

@router.get("/alerts/enhanced")
def get_enhanced_alerts(limit: int = 50):
    """
    Get enhanced alerts with full context including:
    - Exact timestamp when triggered
    - Why it triggered (detailed reason)
    - Timeframe (Scalp/Intraday/Swing/Position)
    - Natural language summary
    - Trade plan with entry, stop, target
    """
    from services.enhanced_alerts import get_alert_manager
    
    manager = get_alert_manager()
    alerts = manager.get_active_alerts(limit)
    
    return {
        "alerts": alerts,
        "count": len(alerts),
        "last_updated": datetime.now(timezone.utc).isoformat()
    }


@router.get("/alerts/enhanced/history")
def get_enhanced_alert_history(limit: int = 100):
    """Get history of all enhanced alerts"""
    from services.enhanced_alerts import get_alert_manager
    
    manager = get_alert_manager()
    history = manager.get_alert_history(limit)
    
    return {
        "history": history,
        "count": len(history)
    }


@router.post("/alerts/enhanced/{alert_id}/viewed")
def mark_alert_viewed(alert_id: str):
    """Mark an alert as viewed"""
    from services.enhanced_alerts import get_alert_manager
    
    manager = get_alert_manager()
    manager.mark_alert_viewed(alert_id)
    
    return {"status": "ok", "alert_id": alert_id}


@router.delete("/alerts/enhanced/{alert_id}")
def archive_enhanced_alert(alert_id: str):
    """Archive/dismiss an alert"""
    from services.enhanced_alerts import get_alert_manager
    
    manager = get_alert_manager()
    manager.archive_alert(alert_id)
    
    return {"status": "archived", "alert_id": alert_id}


@router.get("/alerts/enhanced/generate/{symbol}")
async def generate_enhanced_alert_for_symbol(symbol: str):
    """
    Generate an enhanced alert for a specific symbol.
    Analyzes the symbol and creates a detailed alert if opportunity found.
    """
    from services.enhanced_alerts import (
        create_enhanced_alert, get_alert_manager,
        AlertType
    )
    from services.scoring_engine import get_scoring_engine
    from services.feature_engine import get_feature_engine
    from services.strategy_matching import simple_strategy_match
    
    symbol = symbol.upper()
    
    # Check connection
    is_connected = False
    if _ib_service:
        try:
            status = _ib_service.get_connection_status()
            is_connected = status.get("connected", False)
        except:
            pass
    
    if not is_connected:
        raise HTTPException(
            status_code=503,
            detail={"error": "IB Gateway not connected", "symbol": symbol}
        )
    
    try:
        feature_engine = get_feature_engine()
        scoring_engine = get_scoring_engine()
        
        # Get quote and historical data
        quote = await _ib_service.get_quote(symbol)
        if not quote or not quote.get("price"):
            raise HTTPException(status_code=404, detail=f"No quote data for {symbol}")
        
        hist_data = await _ib_service.get_historical_data(symbol, "5 D", "1 hour")
        if not hist_data or len(hist_data) < 10:
            raise HTTPException(status_code=404, detail=f"Insufficient historical data for {symbol}")
        
        # Calculate features and scores
        features = feature_engine.calculate_all_features(
            bars_5m=hist_data, bars_daily=None, session_bars_1m=None, 
            fundamentals=None, market_data=None
        )
        
        # Build stock_data dict for scoring engine
        stock_data = {
            "symbol": symbol,
            "price": quote.get("price", 0),
            "change_percent": quote.get("change_percent", 0),
            "volume": quote.get("volume", 0),
            **features
        }
        score_result = scoring_engine.calculate_composite_score(stock_data, {})
        
        # Match strategies using simple matcher
        matched = simple_strategy_match(symbol, features, score_result)
        
        if not matched:
            return {
                "symbol": symbol,
                "alert_generated": False,
                "reason": "No strategies matched current setup"
            }
        
        # Determine alert type based on price action
        highs = [bar["high"] for bar in hist_data]
        lows = [bar["low"] for bar in hist_data]
        closes = [bar["close"] for bar in hist_data]
        
        current_price = quote.get("price", 0)
        resistance = max(highs[-20:])
        support = min(lows[-20:])
        prev_close = closes[-2] if len(closes) > 1 else current_price
        
        alert_type = AlertType.STRATEGY_MATCH  # Default
        if current_price > resistance and prev_close <= resistance:
            alert_type = AlertType.BREAKOUT
            features["breakout_level"] = resistance
        elif current_price < support and prev_close >= support:
            alert_type = AlertType.BREAKDOWN
            features["breakdown_level"] = support
        
        # Add levels to features
        features["price"] = current_price
        features["change_percent"] = quote.get("change_percent", 0)
        features["resistance_1"] = resistance
        features["support_1"] = support
        
        # Calculate trading summary
        atr = features.get("atr", current_price * 0.02)
        direction = "LONG" if alert_type != AlertType.BREAKDOWN else "SHORT"
        
        if direction == "LONG":
            stop = round(current_price - (1.5 * atr), 2)
            target = round(current_price + (3 * atr), 2)
        else:
            stop = round(current_price + (1.5 * atr), 2)
            target = round(current_price - (3 * atr), 2)
        
        trading_summary = {
            "direction": direction,
            "entry": round(current_price, 2),
            "stop_loss": stop,
            "target": target,
            "risk_reward": round(abs(target - current_price) / abs(current_price - stop), 2) if abs(current_price - stop) > 0 else 0,
            "position_bias": features.get("bias", "NEUTRAL")
        }
        
        # Get company name
        company_name = quote.get("name", symbol)
        
        # Create enhanced alert
        alert = create_enhanced_alert(
            symbol=symbol,
            company_name=company_name,
            alert_type=alert_type,
            strategy=matched[0],  # Primary strategy
            features=features,
            scores=score_result,
            trading_summary=trading_summary,
            matched_strategies=matched
        )
        
        # Add to alert manager
        manager = get_alert_manager()
        manager.add_alert(alert)
        
        return {
            "symbol": symbol,
            "alert_generated": True,
            "alert": alert
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating enhanced alert for {symbol}: {e}")
        raise HTTPException(
            status_code=500,
            detail={"error": str(e), "symbol": symbol}
        )
