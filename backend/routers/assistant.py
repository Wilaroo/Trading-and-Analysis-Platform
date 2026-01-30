"""
AI Assistant API Router
Endpoints for the intelligent trading assistant.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
import uuid
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assistant", tags=["AI Assistant"])

# Service instance
_assistant_service = None


def init_assistant_router(assistant_service):
    """Initialize the router with the assistant service"""
    global _assistant_service
    _assistant_service = assistant_service


# ===================== Pydantic Models =====================

class ChatRequest(BaseModel):
    message: str = Field(..., description="User message")
    session_id: Optional[str] = Field(default=None, description="Session ID for conversation continuity")


class AnalyzeTradeRequest(BaseModel):
    symbol: str = Field(..., description="Stock symbol")
    action: str = Field(..., description="BUY or SELL")
    session_id: Optional[str] = Field(default=None)


class ProviderRequest(BaseModel):
    provider: str = Field(..., description="LLM provider: emergent, openai, perplexity")


# ===================== Endpoints =====================

@router.post("/chat")
async def chat(request: ChatRequest):
    """
    Chat with the AI assistant.
    
    The assistant has access to:
    - Your learned trading strategies and rules
    - Quality scores and market data
    - Your trading history
    
    It will provide analytical responses and enforce your trading rules.
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    
    # Generate session ID if not provided
    session_id = request.session_id or f"session_{uuid.uuid4().hex[:8]}"
    
    result = await _assistant_service.chat(request.message, session_id)
    
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Chat failed"))
    
    return result


@router.post("/analyze-trade")
async def analyze_trade(request: AnalyzeTradeRequest):
    """
    Get AI analysis of a potential trade.
    
    The assistant will:
    - Check against your learned strategies
    - Verify trading rules aren't violated
    - Assess quality score
    - Provide risk/reward assessment
    - Give a recommendation
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    session_id = request.session_id or f"trade_{uuid.uuid4().hex[:8]}"
    
    result = await _assistant_service.analyze_trade(
        request.symbol.upper(),
        request.action.upper(),
        session_id
    )
    
    return result


@router.get("/premarket-briefing")
async def get_premarket_briefing(session_id: Optional[str] = None):
    """
    Get AI-generated pre-market briefing.
    
    Includes:
    - Market sentiment
    - Key levels to watch
    - Relevant strategies for today
    - Trading rules reminder
    - Setup ideas
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    session_id = session_id or f"briefing_{datetime.now().strftime('%Y%m%d')}"
    
    result = await _assistant_service.get_premarket_briefing(session_id)
    
    return result


@router.get("/review-patterns")
async def review_trading_patterns(session_id: Optional[str] = None):
    """
    Get AI analysis of your trading patterns.
    
    The assistant will analyze your behavior and suggest improvements.
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    session_id = session_id or f"review_{uuid.uuid4().hex[:8]}"
    
    result = await _assistant_service.review_trading_patterns(session_id)
    
    return result


@router.get("/suggestions")
async def get_suggestions():
    """
    Get suggested requests based on your usage patterns.
    
    Returns frequently used request types to help you get started.
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    suggestions = _assistant_service.get_suggested_requests()
    
    return {
        "suggestions": suggestions
    }


@router.get("/history/{session_id}")
async def get_conversation_history(session_id: str):
    """Get conversation history for a session"""
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    history = _assistant_service.get_conversation_history(session_id)
    
    return {
        "session_id": session_id,
        "messages": history,
        "count": len(history)
    }


@router.delete("/history/{session_id}")
async def clear_conversation(session_id: str):
    """Clear conversation history for a session"""
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    _assistant_service.clear_conversation(session_id)
    
    return {"success": True, "message": f"Conversation {session_id} cleared"}


@router.get("/sessions")
async def get_sessions(user_id: str = "default"):
    """Get all conversation sessions for a user"""
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    sessions = _assistant_service.get_all_sessions(user_id)
    
    return {
        "sessions": sessions,
        "count": len(sessions)
    }


@router.get("/providers")
async def get_available_providers():
    """Get available LLM providers"""
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    providers = _assistant_service.get_available_providers()
    current = _assistant_service.provider.value
    
    return {
        "current": current,
        "available": providers
    }


@router.post("/providers")
async def set_provider(request: ProviderRequest):
    """Switch LLM provider"""
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    success = _assistant_service.set_provider(request.provider)
    
    if not success:
        raise HTTPException(status_code=400, detail=f"Invalid or unavailable provider: {request.provider}")
    
    return {
        "success": True,
        "provider": request.provider
    }


@router.get("/status")
async def get_assistant_status():
    """Get assistant service status"""
    if not _assistant_service:
        return {
            "status": "not_initialized",
            "ready": False
        }
    
    providers = _assistant_service.get_available_providers()
    
    return {
        "status": "ready" if providers else "no_providers",
        "ready": len(providers) > 0,
        "current_provider": _assistant_service.provider.value,
        "available_providers": providers,
        "features": {
            "chat": True,
            "trade_analysis": True,
            "premarket_briefing": True,
            "pattern_review": True,
            "conversation_memory": True,
            # New coaching features
            "rule_check": True,
            "position_sizing": True,
            "coaching_alerts": True,
            "trade_review": True,
            "daily_summary": True,
            "setup_analysis": True
        }
    }


# ===================== COACHING ENDPOINTS =====================

class RuleCheckRequest(BaseModel):
    symbol: str = Field(..., description="Stock symbol")
    action: str = Field(..., description="BUY or SELL")
    entry_price: Optional[float] = Field(default=None, description="Planned entry price")
    position_size: Optional[float] = Field(default=None, description="Number of shares")
    stop_loss: Optional[float] = Field(default=None, description="Stop loss price")


class PositionSizingRequest(BaseModel):
    symbol: str = Field(..., description="Stock symbol")
    entry_price: float = Field(..., description="Entry price")
    stop_loss: float = Field(..., description="Stop loss price")
    account_size: Optional[float] = Field(default=None, description="Account size for % calculation")


class CoachingAlertRequest(BaseModel):
    alert_type: str = Field(..., description="Type: market_open, regime_change, losing_streak, overtrading, position_risk, rule_reminder")
    data: Optional[dict] = Field(default=None, description="Context data for the alert")


class TradeReviewRequest(BaseModel):
    symbol: str
    action: str
    entry_price: float
    exit_price: float
    entry_time: Optional[str] = None
    exit_time: Optional[str] = None
    shares: Optional[int] = None
    pnl: Optional[float] = None
    notes: Optional[str] = None


class SetupAnalysisRequest(BaseModel):
    symbol: str = Field(..., description="Stock symbol")
    setup_type: Optional[str] = Field(default=None, description="Type: gap_up, breakout, pullback, reversal, etc.")
    chart_notes: Optional[str] = Field(default=None, description="Your observations about the chart")


@router.post("/coach/check-rules")
async def check_rule_violations(request: RuleCheckRequest):
    """
    Check a trade idea against your trading rules BEFORE taking the trade.
    
    Returns:
    - Rule violations (critical issues)
    - Warnings (concerns to consider)
    - Passed checks (rules you're following)
    - Position sizing recommendation
    - Overall verdict: PROCEED, CAUTION, or DO NOT TRADE
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    result = await _assistant_service.check_rule_violations(
        symbol=request.symbol,
        action=request.action,
        entry_price=request.entry_price,
        position_size=request.position_size,
        stop_loss=request.stop_loss
    )
    
    return result


@router.post("/coach/position-size")
async def get_position_sizing(request: PositionSizingRequest):
    """
    Get AI-powered position sizing recommendation based on:
    - Your trading rules
    - Current market regime
    - Stock volatility (ATR)
    - Risk management best practices
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    result = await _assistant_service.get_position_sizing_guidance(
        symbol=request.symbol,
        entry_price=request.entry_price,
        stop_loss=request.stop_loss,
        account_size=request.account_size
    )
    
    return result


@router.post("/coach/alert")
async def get_coaching_alert(request: CoachingAlertRequest):
    """
    Get proactive coaching alerts for various situations:
    
    Alert types:
    - market_open: Morning coaching tips
    - market_regime_change: Strategy adjustment guidance (include previous_regime, current_regime in data)
    - losing_streak: Support after losses (include consecutive_losses in data)
    - overtrading: Trading frequency warning (include trade_count in data)
    - position_risk: Position size warning (include symbol, shares, exposure in data)
    - rule_reminder: Random rule reminder
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    result = await _assistant_service.get_coaching_alert(
        context_type=request.alert_type,
        data=request.data
    )
    
    return result


@router.post("/coach/review-trade")
async def review_completed_trade(request: TradeReviewRequest):
    """
    Get AI coaching review of a completed trade.
    
    The coach will analyze:
    - Strategy alignment
    - Rule compliance
    - Execution quality
    - Lessons learned
    - Pattern alerts
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    trade_data = {
        "symbol": request.symbol,
        "action": request.action,
        "entry_price": request.entry_price,
        "exit_price": request.exit_price,
        "entry_time": request.entry_time,
        "exit_time": request.exit_time,
        "shares": request.shares,
        "pnl": request.pnl,
        "notes": request.notes
    }
    
    result = await _assistant_service.get_trade_review(trade_data)
    
    return result


@router.get("/coach/daily-summary")
async def get_daily_coaching_summary():
    """
    Get end-of-day coaching summary with:
    - Today's performance review
    - Rule compliance assessment
    - Pattern observations
    - Tomorrow's focus areas
    - Key coaching message
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    result = await _assistant_service.get_daily_coaching_summary()
    
    return result


@router.post("/coach/analyze-setup")
async def analyze_trade_setup(request: SetupAnalysisRequest):
    """
    Get coaching analysis of a trade setup before entry.
    
    Includes:
    - Setup quality rating
    - Strategy match from knowledge base
    - Market regime fit
    - Entry criteria to watch
    - Risk management guidance
    - Warning flags
    - Trade/Wait/Pass verdict
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    result = await _assistant_service.analyze_setup(
        symbol=request.symbol,
        setup_type=request.setup_type,
        chart_notes=request.chart_notes
    )
    
    return result


@router.get("/coach/morning-briefing")
async def get_morning_coaching():
    """
    Quick morning coaching briefing with:
    - Current market regime
    - Best strategies for today
    - Key rule reminder
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    result = await _assistant_service.get_coaching_alert("market_open", {})
    
    return result


@router.get("/coach/rule-reminder")
async def get_random_rule_reminder():
    """
    Get a random trading rule reminder from your knowledge base.
    Good for periodic reminders during trading.
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    result = await _assistant_service.get_coaching_alert("rule_reminder", {})
    
    return result


@router.get("/coach/performance-analysis")
async def analyze_trading_performance(symbol: Optional[str] = None):
    """
    Get AI analysis of your real trading performance from IB.
    Includes insights on patterns, strengths, weaknesses, and recommendations.
    
    Args:
        symbol: Optional - analyze performance for a specific symbol
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    try:
        # Get trade history context
        trade_context = await _assistant_service.get_trade_history_context(symbol)
        
        if "not available" in trade_context.lower() or "not configured" in trade_context.lower():
            return {
                "available": False,
                "message": "Trade history not available. Please configure IB Flex Web Service."
            }
        
        # Ask AI to analyze
        analysis_prompt = f"""Based on the following verified trading performance data from Interactive Brokers, provide a comprehensive analysis:

{trade_context}

Please analyze:
1. **Overall Performance Assessment**: Is the trader profitable? What's the trajectory?
2. **Win Rate & Profit Factor Analysis**: Compare to industry standards (good = 50%+ win rate, 1.5+ profit factor)
3. **Position Sizing Analysis**: Is average win vs average loss ratio healthy?
4. **Symbol Performance Patterns**: Which types of trades work best?
5. **Key Weaknesses Identified**: What patterns are hurting performance?
6. **Top 3 Actionable Recommendations**: Specific changes to improve results

Be direct and analytical. Use the actual numbers. If there are serious issues, highlight them clearly."""

        # Use the assistant's chat functionality
        response = await _assistant_service.chat(
            user_message=analysis_prompt,
            session_id="performance_analysis"
        )
        
        return {
            "available": True,
            "symbol_filter": symbol,
            "analysis": response.get("message", "Analysis unavailable"),
            "raw_metrics": trade_context
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/coach/find-setups/{strategy}")
async def find_strategy_setups(strategy: str, limit: int = 5):
    """
    Find stocks currently matching a specific strategy setup.
    Uses real-time data from scanner and scoring engine.
    
    Args:
        strategy: Strategy name (e.g., 'rubberband', 'breakout', 'momentum')
        limit: Max number of results
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    try:
        from services.scoring_engine import get_scoring_engine
        from services.ib_service import get_ib_service
        
        scoring_engine = get_scoring_engine()
        ib_service = get_ib_service()
        
        strategy_lower = strategy.lower().replace(" ", "_").replace("-", "_")
        
        # Define strategy criteria
        strategy_criteria = {
            "rubber_band": {
                "description": "Mean reversion plays - price extended away from 9 EMA",
                "conditions": ["mean_reversion_signal", "extended_below_ema"],
                "min_score": 60
            },
            "rubberband": {
                "description": "Mean reversion plays - price extended away from 9 EMA",
                "conditions": ["mean_reversion_signal", "extended_below_ema"],
                "min_score": 60
            },
            "breakout": {
                "description": "Price breaking above resistance with volume",
                "conditions": ["breakout_signal", "high_rvol"],
                "min_score": 65
            },
            "momentum": {
                "description": "Strong trending stocks with volume confirmation",
                "conditions": ["trend_strength", "high_rvol"],
                "min_score": 70
            },
            "vwap_bounce": {
                "description": "Price bouncing off VWAP level",
                "conditions": ["near_vwap", "volume_surge"],
                "min_score": 60
            }
        }
        
        criteria = strategy_criteria.get(strategy_lower)
        if not criteria:
            return {
                "strategy": strategy,
                "available_strategies": list(strategy_criteria.keys()),
                "error": f"Strategy '{strategy}' not found. Try: {', '.join(strategy_criteria.keys())}"
            }
        
        # Get list of active stocks to scan (from watchlist or recent scans)
        # For now, use a list of commonly traded stocks
        symbols_to_check = ["AAPL", "TSLA", "NVDA", "META", "MSFT", "AMD", "GOOGL", "AMZN", "SPY", "QQQ",
                          "NFLX", "BA", "DIS", "JPM", "V", "MA", "PYPL", "SQ", "COIN", "SHOP"]
        
        matching_setups = []
        
        for symbol in symbols_to_check:
            try:
                # Get analysis from scoring engine
                analysis = await scoring_engine.analyze_ticker(symbol)
                if not analysis:
                    continue
                
                scores = analysis.get("scores", {})
                trading_summary = analysis.get("trading_summary", {})
                technicals = analysis.get("technicals", {})
                
                overall_score = scores.get("overall", 0)
                
                # Check if it matches strategy criteria
                matches_criteria = False
                match_reasons = []
                
                if strategy_lower in ["rubber_band", "rubberband"]:
                    # Check for mean reversion signal
                    vwap_dist = technicals.get("vwap_distance_pct", 0)
                    ema_dist = technicals.get("distance_from_9ema_pct", 0)
                    
                    # Extended below key levels = potential rubber band long
                    if vwap_dist < -2 or ema_dist < -3:
                        matches_criteria = True
                        match_reasons.append(f"Extended {abs(vwap_dist):.1f}% below VWAP")
                        match_reasons.append(f"Price below 9 EMA by {abs(ema_dist):.1f}%")
                    # Extended above = potential rubber band short
                    elif vwap_dist > 3 or ema_dist > 4:
                        matches_criteria = True
                        match_reasons.append(f"Extended {vwap_dist:.1f}% above VWAP")
                        match_reasons.append("Potential SHORT mean reversion")
                
                elif strategy_lower == "breakout":
                    bias = trading_summary.get("bias", "")
                    if bias == "BULLISH" and overall_score >= 65:
                        matches_criteria = True
                        match_reasons.append(f"Bullish bias with {overall_score} score")
                
                elif strategy_lower == "momentum":
                    rvol = technicals.get("rvol", 0)
                    if rvol > 2 and overall_score >= 70:
                        matches_criteria = True
                        match_reasons.append(f"High RVOL: {rvol:.1f}x")
                
                if matches_criteria and overall_score >= criteria.get("min_score", 50):
                    matching_setups.append({
                        "symbol": symbol,
                        "score": overall_score,
                        "grade": scores.get("grade", "N/A"),
                        "direction": trading_summary.get("suggested_direction", "WAIT"),
                        "bias": trading_summary.get("bias", "NEUTRAL"),
                        "entry": trading_summary.get("entry"),
                        "stop": trading_summary.get("stop_loss"),
                        "target": trading_summary.get("target"),
                        "match_reasons": match_reasons,
                        "technicals": {
                            "vwap_dist": technicals.get("vwap_distance_pct"),
                            "rvol": technicals.get("rvol"),
                            "rsi": technicals.get("rsi_14")
                        }
                    })
                    
            except Exception as e:
                logger.warning(f"Error analyzing {symbol}: {e}")
                continue
        
        # Sort by score and limit
        matching_setups.sort(key=lambda x: x["score"], reverse=True)
        top_setups = matching_setups[:limit]
        
        return {
            "strategy": strategy,
            "description": criteria["description"],
            "total_scanned": len(symbols_to_check),
            "matches_found": len(matching_setups),
            "top_setups": top_setups,
            "message": f"Found {len(top_setups)} {strategy} setups" if top_setups else f"No {strategy} setups found in current market conditions"
        }
        
    except Exception as e:
        logger.error(f"Error finding setups: {e}")
        raise HTTPException(status_code=500, detail=str(e))
