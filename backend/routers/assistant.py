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


# ==================== SCANNER COACHING NOTIFICATIONS ====================

@router.get("/coach/scanner-notifications")
async def get_scanner_coaching_notifications(since: Optional[str] = None):
    """
    Get proactive AI coaching notifications from scanner alerts.
    These are generated automatically when high-priority opportunities are detected.
    
    Args:
        since: Optional ISO timestamp to filter notifications after this time
    
    Returns:
        List of coaching notifications with verdict (TAKE/WAIT/PASS)
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    try:
        notifications = _assistant_service.get_coaching_notifications(since)
        return {
            "success": True,
            "notifications": notifications,
            "count": len(notifications),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting scanner notifications: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/coach/scanner-coaching")
async def generate_scanner_coaching_manual(symbol: str, setup_type: str):
    """
    Manually request AI coaching for a specific scanner alert.
    Useful when you want coaching on an opportunity you've spotted.
    
    Args:
        symbol: Stock symbol
        setup_type: Type of setup (e.g., 'rubber_band_long', 'breakout')
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    try:
        # Build minimal alert data
        alert_data = {
            "symbol": symbol.upper(),
            "setup_type": setup_type,
            "direction": "long" if "long" not in setup_type.lower() else "long",
            "current_price": 0,
            "trigger_price": 0,
            "stop_loss": 0,
            "target": 0,
            "risk_reward": 0,
            "win_rate": 0,
            "tape_confirmation": False,
            "headline": f"Manual coaching request: {setup_type} on {symbol}",
            "reasoning": [],
            "time_window": "unknown",
            "market_regime": "unknown",
            "priority": "medium"
        }
        
        result = await _assistant_service.generate_scanner_coaching(alert_data)
        return result
        
    except Exception as e:
        logger.error(f"Error generating scanner coaching: {e}")
        raise HTTPException(status_code=500, detail=str(e))

        logger.error(f"Error finding setups: {e}")
        raise HTTPException(status_code=500, detail=str(e))



# ===================== TRADING INTELLIGENCE ENDPOINTS =====================

class SetupScoreRequest(BaseModel):
    """Request model for comprehensive setup scoring"""
    symbol: str = Field(..., description="Stock symbol")
    strategy: str = Field(..., description="Strategy name (e.g., 'Spencer Scalp', 'Rubber Band')")
    direction: str = Field(..., description="Trade direction: 'long' or 'short'")
    entry_price: float = Field(..., description="Planned entry price")
    stop_price: float = Field(..., description="Stop loss price")
    rvol: Optional[float] = Field(default=1.0, description="Relative volume")
    catalyst_score: Optional[int] = Field(default=0, description="Catalyst score (-10 to +10)")
    market_regime: Optional[str] = Field(default="volatile", description="Market condition")
    time_of_day: Optional[str] = Field(default="prime_time", description="Current time period")
    detected_patterns: Optional[List[str]] = Field(default=None, description="Detected chart patterns")


class ValidateTradeRequest(BaseModel):
    """Request model for trade validation"""
    symbol: str = Field(..., description="Stock symbol")
    strategy: str = Field(..., description="Strategy name")
    direction: str = Field(..., description="Trade direction: 'long' or 'short'")
    entry_price: float = Field(..., description="Planned entry price")
    stop_price: float = Field(..., description="Stop loss price")
    rvol: float = Field(default=1.0, description="Relative volume")
    against_spy_trend: Optional[bool] = Field(default=False, description="Is trade against SPY trend?")
    catalyst_score: Optional[int] = Field(default=0, description="Catalyst score (-10 to +10)")


@router.post("/intelligence/score-setup")
async def score_trade_setup(request: SetupScoreRequest):
    """
    Comprehensive trade setup scoring using the Trading Intelligence System.
    
    Evaluates setup against:
    - Volume requirements for the strategy
    - Time of day alignment
    - Market regime fit
    - Chart pattern synergy
    - Catalyst strength
    - Technical alignment
    - Risk/reward quality
    
    Returns:
    - Total score (0-100+)
    - Letter grade (A+, A, B+, B, C, F)
    - Position sizing recommendation
    - Detailed score breakdown
    - Trade/Skip decision
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    try:
        from services.trading_intelligence import get_trading_intelligence, MarketCondition, TimeOfDay
        
        ti = get_trading_intelligence()
        
        # Map string inputs to enums
        regime_map = {
            "trending_up": MarketCondition.TRENDING_UP,
            "trending_down": MarketCondition.TRENDING_DOWN,
            "range_bound": MarketCondition.RANGE_BOUND,
            "volatile": MarketCondition.VOLATILE,
            "choppy": MarketCondition.CHOPPY,
            "breakout": MarketCondition.BREAKOUT,
            "mean_reversion": MarketCondition.MEAN_REVERSION
        }
        
        time_map = {
            "premarket": TimeOfDay.PREMARKET,
            "opening_auction": TimeOfDay.OPENING_AUCTION,
            "opening_drive": TimeOfDay.OPENING_DRIVE,
            "morning_momentum": TimeOfDay.MORNING_MOMENTUM,
            "prime_time": TimeOfDay.PRIME_TIME,
            "late_morning": TimeOfDay.LATE_MORNING,
            "midday": TimeOfDay.MIDDAY,
            "afternoon": TimeOfDay.AFTERNOON,
            "power_hour": TimeOfDay.POWER_HOUR
        }
        
        market_regime = regime_map.get(request.market_regime, MarketCondition.VOLATILE)
        time_of_day = time_map.get(request.time_of_day, TimeOfDay.PRIME_TIME)
        
        result = ti.score_trade_setup(
            symbol=request.symbol.upper(),
            strategy=request.strategy,
            direction=request.direction.lower(),
            entry_price=request.entry_price,
            stop_price=request.stop_price,
            current_price=request.entry_price,  # Assume current = entry for scoring
            rvol=request.rvol,
            catalyst_score=request.catalyst_score,
            market_regime=market_regime,
            time_of_day=time_of_day,
            detected_patterns=request.detected_patterns
        )
        
        return {
            "success": True,
            **result
        }
        
    except Exception as e:
        logger.error(f"Error scoring setup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/intelligence/validate-trade")
async def validate_trade_idea(request: ValidateTradeRequest):
    """
    Validate a trade idea with go/no-go decision.
    
    Checks:
    - Universal avoidance rules
    - Strategy-specific avoidance
    - Time restrictions
    - Regime alignment
    - Volume requirements
    - Catalyst alignment
    
    Returns:
    - Decision: STRONG GO, GO, NEUTRAL, CAUTION, HIGH RISK, NO TRADE
    - Confidence percentage
    - Blockers (critical issues)
    - Warnings (concerns)
    - Confirmations (positive factors)
    - Human-readable recommendation
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    try:
        from services.trading_intelligence import get_trading_intelligence, MarketCondition, TimeOfDay
        from datetime import datetime
        
        ti = get_trading_intelligence()
        
        # Determine current time of day
        now = datetime.now()
        hour = now.hour
        minute = now.minute
        
        if hour < 9 or (hour == 9 and minute < 30):
            tod = TimeOfDay.PREMARKET
        elif hour == 9 and minute < 35:
            tod = TimeOfDay.OPENING_AUCTION
        elif hour == 9 and minute < 45:
            tod = TimeOfDay.OPENING_DRIVE
        elif hour == 9:
            tod = TimeOfDay.MORNING_MOMENTUM
        elif hour == 10 and minute < 45:
            tod = TimeOfDay.PRIME_TIME
        elif hour < 12 or (hour == 11 and minute < 30):
            tod = TimeOfDay.LATE_MORNING
        elif hour < 14 or (hour == 13 and minute < 30):
            tod = TimeOfDay.MIDDAY
        elif hour < 15:
            tod = TimeOfDay.AFTERNOON
        else:
            tod = TimeOfDay.POWER_HOUR
        
        result = ti.validate_trade_idea(
            symbol=request.symbol.upper(),
            strategy=request.strategy,
            direction=request.direction.lower(),
            entry_price=request.entry_price,
            stop_price=request.stop_price,
            rvol=request.rvol,
            time_of_day=tod,
            market_regime=MarketCondition.VOLATILE,  # Default; could be passed in
            catalyst_score=request.catalyst_score,
            against_spy_trend=request.against_spy_trend
        )
        
        return {
            "success": True,
            "time_of_day": tod.value,
            **result
        }
        
    except Exception as e:
        logger.error(f"Error validating trade: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/intelligence/pattern-strategy-match")
async def match_patterns_to_strategies(
    patterns: str,
    direction: str = "long"
):
    """
    Given detected chart patterns, recommend the best trading strategies.
    
    Args:
        patterns: Comma-separated list of patterns (e.g., "bull_flag,ascending_triangle")
        direction: Trade direction preference ("long" or "short")
    
    Returns:
        List of strategies that synergize well with the detected patterns
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    try:
        from services.trading_intelligence import get_trading_intelligence
        
        ti = get_trading_intelligence()
        pattern_list = [p.strip() for p in patterns.split(",")]
        
        recommendations = ti.match_patterns_to_strategies(pattern_list, direction.lower())
        
        return {
            "success": True,
            "detected_patterns": pattern_list,
            "direction": direction,
            "recommendations": recommendations
        }
        
    except Exception as e:
        logger.error(f"Error matching patterns: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/intelligence/market-analysis")
async def analyze_market_conditions(
    spy_trend: str = "neutral",
    vix_level: float = 15.0,
    breadth: str = "neutral",
    rvol: float = 1.0,
    gaps_filling: bool = False,
    breakouts_working: bool = True
):
    """
    Analyze current market conditions and get regime-specific recommendations.
    
    Returns:
    - Market regime classification
    - Trading bias
    - Recommended strategies
    - Strategies to avoid
    - Position sizing guidance
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    try:
        from services.trading_intelligence import get_trading_intelligence
        
        ti = get_trading_intelligence()
        
        analysis = ti.analyze_market_conditions(
            spy_trend=spy_trend,
            vix_level=vix_level,
            market_breadth=breadth,
            rvol_market=rvol,
            gaps_filling=gaps_filling,
            breakouts_working=breakouts_working
        )
        
        return {
            "success": True,
            "regime": analysis.regime.value,
            "bias": analysis.bias.value,
            "strength_score": analysis.strength_score,
            "vix_assessment": analysis.vix_level,
            "recommended_strategies": analysis.recommended_strategies,
            "avoid_strategies": analysis.avoid_strategies,
            "position_sizing": analysis.position_sizing,
            "notes": analysis.notes
        }
        
    except Exception as e:
        logger.error(f"Error analyzing market: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/intelligence/predict-outcome")
async def predict_trade_outcome(
    setup_score: int,
    pattern_reliability: float = 0.65,
    regime_alignment: float = 75.0,
    volume_strength: float = 2.0
):
    """
    Predict probability of trade success based on multiple factors.
    
    Args:
        setup_score: Overall setup score (0-100)
        pattern_reliability: Historical pattern success rate (0-1, e.g., 0.67 for bull flag)
        regime_alignment: How well strategy fits current regime (0-100)
        volume_strength: RVOL level
    
    Returns:
        Success probability, expected value, confidence level, and factor breakdown
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    try:
        from services.trading_intelligence import get_trading_intelligence
        
        ti = get_trading_intelligence()
        
        prediction = ti.predict_trade_outcome(
            setup_score=setup_score,
            pattern_reliability=pattern_reliability,
            regime_alignment=regime_alignment,
            volume_strength=volume_strength
        )
        
        return {
            "success": True,
            **prediction
        }
        
    except Exception as e:
        logger.error(f"Error predicting outcome: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===================== FUNDAMENTAL ANALYSIS ENDPOINTS =====================

class FundamentalAnalysisRequest(BaseModel):
    """Request model for fundamental stock analysis"""
    symbol: str = Field(..., description="Stock symbol")
    pe_ratio: Optional[float] = Field(default=None, description="Price-to-Earnings ratio")
    pb_ratio: Optional[float] = Field(default=None, description="Price-to-Book ratio")
    peg_ratio: Optional[float] = Field(default=None, description="PEG ratio")
    roe: Optional[float] = Field(default=None, description="Return on Equity (decimal, e.g., 0.15 for 15%)")
    debt_to_equity: Optional[float] = Field(default=None, description="Debt-to-Equity ratio")
    free_cash_flow_positive: Optional[bool] = Field(default=None, description="Whether FCF is positive")
    current_ratio: Optional[float] = Field(default=None, description="Current ratio")
    dividend_yield: Optional[float] = Field(default=None, description="Dividend yield (decimal)")
    eps_growth: Optional[float] = Field(default=None, description="EPS growth rate (decimal)")


@router.post("/analyze-fundamentals")
async def analyze_stock_fundamentals(request: FundamentalAnalysisRequest):
    """
    Analyze a stock's fundamental metrics and get an investment assessment.
    
    Provide any known fundamental metrics and receive:
    - Value score (0-100)
    - Bullish/Bearish signals
    - Warning flags
    - Overall assessment
    - Comparison benchmarks
    
    You can provide partial data - the analysis will use whatever metrics are available.
    
    Example metrics to provide:
    - pe_ratio: 15.5 (lower generally better, compare to industry)
    - pb_ratio: 2.1 (below 1 = below book value)
    - peg_ratio: 0.8 (below 1 = undervalued vs growth)
    - roe: 0.18 (18% - above 15% is good)
    - debt_to_equity: 0.5 (below 1 is conservative)
    - free_cash_flow_positive: true
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    try:
        from services.investopedia_knowledge import get_investopedia_knowledge
        
        investopedia = get_investopedia_knowledge()
        
        # Run the fundamental analysis
        analysis = investopedia.analyze_stock_fundamentals(
            pe=request.pe_ratio,
            pb=request.pb_ratio,
            de=request.debt_to_equity,
            roe=request.roe,
            peg=request.peg_ratio,
            fcf_positive=request.free_cash_flow_positive
        )
        
        # Add benchmark context
        benchmarks = {
            "pe_ratio": {"good": "15-20", "excellent": "<15", "concerning": ">25"},
            "pb_ratio": {"good": "1-3", "value_opportunity": "<1", "concerning": ">3"},
            "peg_ratio": {"undervalued": "<1", "fair": "1", "overvalued": ">1"},
            "roe": {"excellent": ">20%", "good": "15-20%", "below_average": "<10%"},
            "debt_to_equity": {"conservative": "<0.5", "moderate": "0.5-1", "leveraged": ">2"},
            "current_ratio": {"strong": ">2", "healthy": "1.5-2", "tight": "<1"}
        }
        
        # Generate recommendation
        score = analysis["value_score"]
        if score >= 75:
            recommendation = "FUNDAMENTALLY ATTRACTIVE - Consider for long-term investment"
        elif score >= 60:
            recommendation = "DECENT FUNDAMENTALS - May be worth further research"
        elif score >= 45:
            recommendation = "MIXED FUNDAMENTALS - Proceed with caution"
        else:
            recommendation = "FUNDAMENTAL CONCERNS - High risk for value investors"
        
        return {
            "success": True,
            "symbol": request.symbol.upper(),
            "value_score": analysis["value_score"],
            "overall_assessment": analysis["overall_assessment"],
            "recommendation": recommendation,
            "bullish_signals": analysis["signals"],
            "warning_flags": analysis["warnings"],
            "metrics_provided": {
                "pe_ratio": request.pe_ratio,
                "pb_ratio": request.pb_ratio,
                "peg_ratio": request.peg_ratio,
                "roe": f"{request.roe:.1%}" if request.roe else None,
                "debt_to_equity": request.debt_to_equity,
                "free_cash_flow_positive": request.free_cash_flow_positive,
                "current_ratio": request.current_ratio,
                "dividend_yield": f"{request.dividend_yield:.2%}" if request.dividend_yield else None
            },
            "benchmarks": benchmarks
        }
        
    except Exception as e:
        logger.error(f"Error analyzing fundamentals: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/fundamentals/metric/{metric_name}")
async def get_fundamental_metric_info(metric_name: str):
    """
    Get detailed information about a specific fundamental metric.
    
    Available metrics:
    - pe_ratio (Price-to-Earnings)
    - pb_ratio (Price-to-Book)
    - peg_ratio (PEG Ratio)
    - eps (Earnings Per Share)
    - roe (Return on Equity)
    - debt_to_equity (Debt-to-Equity)
    - free_cash_flow (Free Cash Flow)
    - current_ratio
    - interest_coverage
    - dividend_yield
    - price_to_sales
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    try:
        from services.investopedia_knowledge import get_investopedia_knowledge
        
        investopedia = get_investopedia_knowledge()
        metric_data = investopedia.get_fundamental_metric(metric_name)
        
        if not metric_data:
            available = investopedia.get_all_fundamental_metrics()
            raise HTTPException(
                status_code=404, 
                detail=f"Metric '{metric_name}' not found. Available: {', '.join(available)}"
            )
        
        return {
            "success": True,
            "metric": metric_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting metric info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/fundamentals/all-metrics")
async def get_all_fundamental_metrics():
    """
    Get list of all available fundamental analysis metrics.
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    try:
        from services.investopedia_knowledge import get_investopedia_knowledge
        
        investopedia = get_investopedia_knowledge()
        metrics = investopedia.get_all_fundamental_metrics()
        
        # Categorize metrics
        categorized = {
            "valuation": [],
            "profitability": [],
            "solvency": [],
            "liquidity": []
        }
        
        for metric_name in metrics:
            metric = investopedia.get_fundamental_metric(metric_name)
            if metric:
                category = metric.get("category", "other")
                if category in categorized:
                    categorized[category].append({
                        "id": metric_name,
                        "name": metric["name"],
                        "description": metric["description"][:100] + "..." if len(metric["description"]) > 100 else metric["description"]
                    })
        
        return {
            "success": True,
            "total_metrics": len(metrics),
            "metrics_by_category": categorized
        }
        
    except Exception as e:
        logger.error(f"Error getting metrics list: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/fundamentals/knowledge")
async def get_fundamental_analysis_knowledge():
    """
    Get comprehensive fundamental analysis knowledge for education/reference.
    Includes all valuation metrics, profitability measures, solvency ratios,
    and how to combine technical and fundamental analysis.
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    try:
        from services.investopedia_knowledge import get_investopedia_knowledge
        
        investopedia = get_investopedia_knowledge()
        knowledge = investopedia.get_fundamental_analysis_context_for_ai()
        
        return {
            "success": True,
            "knowledge": knowledge,
            "source": "Investopedia",
            "last_updated": "December 2025"
        }
        
    except Exception as e:
        logger.error(f"Error getting fundamental knowledge: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===================== REAL-TIME FUNDAMENTAL DATA ENDPOINTS =====================

@router.get("/realtime/fundamentals/{symbol}")
async def get_realtime_fundamentals(symbol: str):
    """
    Fetch REAL-TIME fundamental data for a stock from Finnhub.
    
    Returns comprehensive fundamental metrics including:
    - Valuation: P/E, P/B, P/S, PEG, EV/EBITDA
    - Profitability: ROE, ROA, margins
    - Growth: EPS growth, revenue growth
    - Financial Health: D/E ratio, current ratio, interest coverage
    - Per Share: EPS, book value, dividend yield
    - Market Data: market cap, beta, 52-week range
    
    This uses LIVE data from Finnhub API.
    """
    try:
        from services.fundamental_data_service import get_fundamental_data_service
        
        service = get_fundamental_data_service()
        data = await service.get_fundamentals(symbol)
        
        if not data:
            raise HTTPException(
                status_code=404, 
                detail=f"No fundamental data available for {symbol}. Check if the symbol is valid."
            )
        
        # Convert dataclass to dict for response
        return {
            "success": True,
            "symbol": data.symbol,
            "valuation": {
                "pe_ratio": data.pe_ratio,
                "forward_pe": data.forward_pe,
                "pb_ratio": data.pb_ratio,
                "ps_ratio": data.ps_ratio,
                "peg_ratio": data.peg_ratio,
                "ev_to_ebitda": data.ev_to_ebitda,
                "price_to_fcf": data.price_to_fcf
            },
            "profitability": {
                "roe": f"{data.roe:.2%}" if data.roe else None,
                "roa": f"{data.roa:.2%}" if data.roa else None,
                "roic": f"{data.roic:.2%}" if data.roic else None,
                "gross_margin": f"{data.gross_margin:.2%}" if data.gross_margin else None,
                "operating_margin": f"{data.operating_margin:.2%}" if data.operating_margin else None,
                "net_margin": f"{data.net_margin:.2%}" if data.net_margin else None
            },
            "growth": {
                "eps_growth_yoy": f"{data.eps_growth_yoy:.2%}" if data.eps_growth_yoy else None,
                "eps_growth_3y": f"{data.eps_growth_3y:.2%}" if data.eps_growth_3y else None,
                "eps_growth_5y": f"{data.eps_growth_5y:.2%}" if data.eps_growth_5y else None,
                "revenue_growth_yoy": f"{data.revenue_growth_yoy:.2%}" if data.revenue_growth_yoy else None,
                "revenue_growth_3y": f"{data.revenue_growth_3y:.2%}" if data.revenue_growth_3y else None
            },
            "financial_health": {
                "debt_to_equity": data.debt_to_equity,
                "current_ratio": data.current_ratio,
                "quick_ratio": data.quick_ratio,
                "interest_coverage": data.interest_coverage
            },
            "per_share": {
                "eps_ttm": data.eps_ttm,
                "book_value_per_share": data.book_value_per_share,
                "revenue_per_share": data.revenue_per_share,
                "fcf_per_share": data.fcf_per_share,
                "dividend_yield": f"{data.dividend_yield:.2%}" if data.dividend_yield else None,
                "dividend_per_share": data.dividend_per_share,
                "payout_ratio": f"{data.payout_ratio:.0%}" if data.payout_ratio else None
            },
            "market_data": {
                "market_cap_millions": data.market_cap,
                "enterprise_value_millions": data.enterprise_value,
                "beta": data.beta,
                "52_week_high": data.high_52_week,
                "52_week_low": data.low_52_week
            },
            "timestamp": data.timestamp,
            "source": data.source
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching real-time fundamentals: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/realtime/analyze/{symbol}")
async def analyze_stock_realtime(symbol: str, include_technicals: bool = True):
    """
    Get comprehensive REAL-TIME stock analysis combining fundamentals and technicals.
    
    This is the most powerful analysis endpoint - it fetches:
    1. Live fundamental data from Finnhub (P/E, ROE, D/E, margins, growth, etc.)
    2. Technical analysis from the scoring engine (if available)
    3. Company profile information
    4. Combined scoring with weighted fundamentals + technicals
    
    Returns:
    - Fundamental score (0-100) with signals and warnings
    - Technical score and trading bias
    - Combined score and overall verdict
    - All underlying metrics
    """
    try:
        from services.fundamental_data_service import get_fundamental_data_service
        
        service = get_fundamental_data_service()
        analysis = await service.get_full_stock_analysis(symbol, include_technicals)
        
        return {
            "success": True,
            **analysis
        }
        
    except Exception as e:
        logger.error(f"Error analyzing stock: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/realtime/company/{symbol}")
async def get_company_profile(symbol: str):
    """
    Get company profile information including sector, industry, and basic info.
    """
    try:
        from services.fundamental_data_service import get_fundamental_data_service
        
        service = get_fundamental_data_service()
        profile = await service.get_company_profile(symbol)
        
        if not profile:
            raise HTTPException(
                status_code=404,
                detail=f"No company profile found for {symbol}"
            )
        
        return {
            "success": True,
            **profile
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching company profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/realtime/compare")
async def compare_stocks_fundamentals(symbols: List[str]):
    """
    Compare fundamental metrics across multiple stocks.
    Useful for finding the best value among similar companies.
    
    Request body: ["AAPL", "MSFT", "GOOGL"]
    """
    if len(symbols) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 symbols allowed")
    
    if len(symbols) < 2:
        raise HTTPException(status_code=400, detail="At least 2 symbols required for comparison")
    
    try:
        from services.fundamental_data_service import get_fundamental_data_service
        
        service = get_fundamental_data_service()
        
        comparisons = []
        for symbol in symbols:
            analysis = await service.analyze_fundamentals(symbol)
            if analysis.get("available"):
                comparisons.append({
                    "symbol": symbol.upper(),
                    "value_score": analysis.get("value_score"),
                    "assessment": analysis.get("assessment"),
                    "pe_ratio": analysis.get("metrics", {}).get("valuation", {}).get("pe_ratio"),
                    "peg_ratio": analysis.get("metrics", {}).get("valuation", {}).get("peg_ratio"),
                    "roe": analysis.get("metrics", {}).get("profitability", {}).get("roe"),
                    "debt_to_equity": analysis.get("metrics", {}).get("financial_health", {}).get("debt_to_equity"),
                    "signals_count": len(analysis.get("signals", [])),
                    "warnings_count": len(analysis.get("warnings", []))
                })
            else:
                comparisons.append({
                    "symbol": symbol.upper(),
                    "error": "Data unavailable"
                })
        
        # Rank by value score
        ranked = sorted(
            [c for c in comparisons if "value_score" in c],
            key=lambda x: x["value_score"],
            reverse=True
        )
        
        return {
            "success": True,
            "comparisons": comparisons,
            "ranking": [c["symbol"] for c in ranked],
            "best_value": ranked[0]["symbol"] if ranked else None,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error comparing stocks: {e}")
        raise HTTPException(status_code=500, detail=str(e))
