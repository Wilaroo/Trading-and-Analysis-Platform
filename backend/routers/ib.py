"""
Interactive Brokers API Router
Endpoints for IB connection, account info, trading, and market data
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from services.ib_service import IBService
from services.feature_engine import get_feature_engine

router = APIRouter(prefix="/api/ib", tags=["Interactive Brokers"])

# Service instance (will be injected)
_ib_service: Optional[IBService] = None


def init_ib_service(service: IBService):
    """Initialize the IB service for this router"""
    global _ib_service
    _ib_service = service


# ===================== Pydantic Models =====================

class OrderRequest(BaseModel):
    symbol: str = Field(..., description="Stock symbol")
    action: str = Field(..., description="BUY or SELL")
    quantity: int = Field(..., gt=0, description="Number of shares")
    order_type: str = Field(default="MKT", description="Order type: MKT, LMT, STP, STP_LMT")
    limit_price: Optional[float] = Field(default=None, description="Limit price for LMT orders")
    stop_price: Optional[float] = Field(default=None, description="Stop price for STP orders")


class SubscribeRequest(BaseModel):
    symbol: str = Field(..., description="Stock symbol to subscribe")


# ===================== Connection Endpoints =====================

@router.get("/status")
async def get_connection_status():
    """Get IB connection status"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    return _ib_service.get_connection_status()


@router.post("/connect")
async def connect_to_ib():
    """Connect to Interactive Brokers Gateway/TWS"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    success = await _ib_service.connect()
    
    if success:
        return {"status": "connected", "message": "Successfully connected to IB"}
    else:
        raise HTTPException(
            status_code=503,
            detail="Failed to connect to IB Gateway. Make sure IB Gateway is running on port 4002."
        )


@router.post("/disconnect")
async def disconnect_from_ib():
    """Disconnect from Interactive Brokers"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    await _ib_service.disconnect()
    return {"status": "disconnected", "message": "Disconnected from IB"}


# ===================== Account Endpoints =====================

@router.get("/account/summary")
async def get_account_summary():
    """Get account summary including balances and P&L"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        return await _ib_service.get_account_summary()
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching account summary: {str(e)}")


@router.get("/account/positions")
async def get_positions():
    """Get all current positions"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        positions = await _ib_service.get_positions()
        return {"positions": positions, "count": len(positions)}
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching positions: {str(e)}")


# ===================== Market Data Endpoints =====================

@router.get("/quote/{symbol}")
async def get_quote(symbol: str):
    """Get real-time quote for a symbol"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        quote = await _ib_service.get_quote(symbol)
        if quote:
            return quote
        else:
            raise HTTPException(status_code=404, detail=f"No quote available for {symbol}")
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching quote: {str(e)}")


@router.post("/subscribe")
async def subscribe_market_data(request: SubscribeRequest):
    """Subscribe to streaming market data for a symbol"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        success = await _ib_service.subscribe_market_data(request.symbol)
        if success:
            return {"status": "subscribed", "symbol": request.symbol.upper()}
        else:
            raise HTTPException(status_code=503, detail="Failed to subscribe - not connected to IB")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error subscribing: {str(e)}")


@router.post("/unsubscribe")
async def unsubscribe_market_data(request: SubscribeRequest):
    """Unsubscribe from market data for a symbol"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    success = await _ib_service.unsubscribe_market_data(request.symbol)
    return {"status": "unsubscribed" if success else "not_found", "symbol": request.symbol.upper()}


@router.get("/historical/{symbol}")
async def get_historical_data(
    symbol: str,
    duration: str = "1 D",
    bar_size: str = "5 mins"
):
    """Get historical bar data for a symbol"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        bars = await _ib_service.get_historical_data(symbol, duration, bar_size)
        return {"symbol": symbol.upper(), "bars": bars, "count": len(bars)}
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching historical data: {str(e)}")


# ===================== Trading Endpoints =====================

@router.post("/order")
async def place_order(request: OrderRequest):
    """Place a new order"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    # Validate action
    if request.action.upper() not in ["BUY", "SELL"]:
        raise HTTPException(status_code=400, detail="Action must be BUY or SELL")
    
    # Validate order type
    valid_order_types = ["MKT", "LMT", "STP", "STP_LMT"]
    if request.order_type.upper() not in valid_order_types:
        raise HTTPException(status_code=400, detail=f"Order type must be one of: {valid_order_types}")
    
    # Validate prices based on order type
    if request.order_type.upper() == "LMT" and request.limit_price is None:
        raise HTTPException(status_code=400, detail="Limit price required for limit orders")
    
    if request.order_type.upper() == "STP" and request.stop_price is None:
        raise HTTPException(status_code=400, detail="Stop price required for stop orders")
    
    if request.order_type.upper() == "STP_LMT" and (request.stop_price is None or request.limit_price is None):
        raise HTTPException(status_code=400, detail="Both stop and limit prices required for stop-limit orders")
    
    try:
        result = await _ib_service.place_order(
            symbol=request.symbol,
            action=request.action,
            quantity=request.quantity,
            order_type=request.order_type,
            limit_price=request.limit_price,
            stop_price=request.stop_price
        )
        return result
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error placing order: {str(e)}")


@router.delete("/order/{order_id}")
async def cancel_order(order_id: int):
    """Cancel an open order"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        success = await _ib_service.cancel_order(order_id)
        if success:
            return {"status": "cancelled", "order_id": order_id}
        else:
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found or already filled")
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error cancelling order: {str(e)}")


@router.get("/orders/open")
async def get_open_orders():
    """Get all open orders"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        orders = await _ib_service.get_open_orders()
        return {"orders": orders, "count": len(orders)}
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching orders: {str(e)}")


@router.get("/executions")
async def get_executions():
    """Get today's executions/fills"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        executions = await _ib_service.get_executions()
        return {"executions": executions, "count": len(executions)}
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching executions: {str(e)}")


# ===================== Scanner Endpoints =====================

class ScannerRequest(BaseModel):
    scan_type: str = Field(default="TOP_PERC_GAIN", description="Scanner type")
    max_results: int = Field(default=50, ge=1, le=100, description="Max results")


@router.post("/scanner")
async def run_market_scanner(request: ScannerRequest):
    """
    Run IB market scanner to find trade opportunities.
    
    Available scan types:
    - TOP_PERC_GAIN: Top % gainers
    - TOP_PERC_LOSE: Top % losers
    - MOST_ACTIVE: Most active by volume
    - HOT_BY_VOLUME: Hot by volume
    - HIGH_OPEN_GAP: High opening gap (gap up)
    - LOW_OPEN_GAP: Low opening gap (gap down)
    - TOP_TRADE_COUNT: Most trades
    - HIGH_VS_13W_HL: Near 13-week high
    - LOW_VS_13W_HL: Near 13-week low
    - HIGH_VS_52W_HL: Near 52-week high
    - LOW_VS_52W_HL: Near 52-week low
    """
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        results = await _ib_service.run_scanner(
            scan_type=request.scan_type,
            max_results=request.max_results
        )
        return {"results": results, "count": len(results), "scan_type": request.scan_type}
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error running scanner: {str(e)}")


class EnhancedScannerRequest(BaseModel):
    scan_type: str = Field(default="TOP_PERC_GAIN", description="Scanner type")
    max_results: int = Field(default=25, ge=1, le=50, description="Max results")
    calculate_features: bool = Field(default=True, description="Calculate technical features")


@router.post("/scanner/enhanced")
async def run_enhanced_scanner(request: EnhancedScannerRequest):
    """
    Run IB market scanner with automatic historical data fetching and conviction scoring.
    
    This endpoint:
    1. Runs the market scanner to find opportunities
    2. Fetches quotes for each result
    3. Fetches 5-minute historical bars
    4. Calculates technical features and conviction score
    5. Returns results with HIGH CONVICTION badges
    """
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        import logging
        logger = logging.getLogger(__name__)
        
        # Step 1: Run scanner
        logger.info(f"Running enhanced scanner: {request.scan_type}")
        scanner_results = await _ib_service.run_scanner(
            scan_type=request.scan_type,
            max_results=request.max_results
        )
        
        if not scanner_results:
            return {"results": [], "count": 0, "scan_type": request.scan_type}
        
        # Step 2: Get quotes for all symbols
        symbols = [r["symbol"] for r in scanner_results]
        logger.info(f"Fetching quotes for {len(symbols)} symbols")
        quotes = await _ib_service.get_quotes_batch(symbols)
        quotes_map = {q["symbol"]: q for q in quotes}
        
        enhanced_results = []
        feature_engine = get_feature_engine()
        
        for result in scanner_results:
            symbol = result["symbol"]
            quote = quotes_map.get(symbol, {})
            
            enhanced = {
                **result,
                "quote": quote,
                "conviction": None,
                "features": None,
                "high_conviction": False
            }
            
            if request.calculate_features and quote.get("price"):
                try:
                    # Step 3: Fetch 5-minute historical bars (last 1 day)
                    bars = await _ib_service.get_historical_data(
                        symbol=symbol,
                        duration="1 D",
                        bar_size="5 mins"
                    )
                    
                    if bars and len(bars) >= 5:
                        # Convert bars to feature engine format
                        feature_bars = [{
                            "open": b.get("open", 0),
                            "high": b.get("high", 0),
                            "low": b.get("low", 0),
                            "close": b.get("close", 0),
                            "volume": b.get("volume", 0),
                            "prior_close": quote.get("prev_close", 0),
                            "prior_high": quote.get("high", 0),  # Approximate
                            "prior_low": quote.get("low", 0)
                        } for b in bars]
                        
                        # Step 4: Calculate features
                        features = feature_engine.calculate_all_features(
                            bars_5m=feature_bars,
                            bars_daily=None,
                            session_bars_1m=None,
                            fundamentals=None,
                            market_data=None
                        )
                        
                        enhanced["features"] = {
                            "rsi_14": features.get("rsi_14"),
                            "rvol": features.get("rvol_intraday", features.get("rvol_20", 1)),
                            "vwap": features.get("vwap"),
                            "close_over_vwap_pct": features.get("close_over_vwap_pct"),
                            "atr_14": features.get("atr_14"),
                            "macd_bullish": features.get("macd_bullish"),
                            "roc_10": features.get("roc_10")
                        }
                        
                        # Get conviction score
                        enhanced["conviction"] = {
                            "score": features.get("intraday_conviction_score", 50),
                            "confidence": features.get("conviction_confidence", "MEDIUM"),
                            "signals": features.get("conviction_signals", [])
                        }
                        
                        enhanced["high_conviction"] = features.get("meets_high_conviction", False)
                        
                except Exception as feat_err:
                    logger.warning(f"Error calculating features for {symbol}: {feat_err}")
            
            enhanced_results.append(enhanced)
        
        # Sort by conviction score (highest first)
        enhanced_results.sort(
            key=lambda x: x.get("conviction", {}).get("score", 0) if x.get("conviction") else 0,
            reverse=True
        )
        
        # Count high conviction
        high_conviction_count = sum(1 for r in enhanced_results if r.get("high_conviction"))
        
        return {
            "results": enhanced_results,
            "count": len(enhanced_results),
            "high_conviction_count": high_conviction_count,
            "scan_type": request.scan_type
        }
        
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error running enhanced scanner: {str(e)}")


@router.post("/quotes/batch")
async def get_batch_quotes(symbols: List[str]):
    """Get real-time quotes for multiple symbols"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    if not symbols:
        raise HTTPException(status_code=400, detail="No symbols provided")
    
    if len(symbols) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 symbols per request")
    
    try:
        quotes = await _ib_service.get_quotes_batch(symbols)
        return {"quotes": quotes, "count": len(quotes)}
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching quotes: {str(e)}")


@router.get("/fundamentals/{symbol}")
async def get_fundamentals(symbol: str):
    """Get fundamental data for a symbol"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        data = await _ib_service.get_fundamentals(symbol)
        return data
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching fundamentals: {str(e)}")


# ===================== News Endpoints =====================

@router.get("/news/{symbol}")
async def get_ticker_news(symbol: str):
    """Get news headlines for a specific ticker symbol"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        news = await _ib_service.get_news_for_symbol(symbol.upper())
        return {
            "symbol": symbol.upper(),
            "news": news,
            "count": len(news)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching news: {str(e)}")


@router.get("/news")
async def get_market_news():
    """Get general market news headlines"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        news = await _ib_service.get_general_news()
        return {
            "news": news,
            "count": len(news)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching news: {str(e)}")


# ===================== Comprehensive Ticker Analysis =====================

@router.get("/analysis/{symbol}")
async def get_comprehensive_analysis(symbol: str):
    """
    Get comprehensive analysis for a ticker including:
    - Scores (from Universal Scoring Engine)
    - Fundamentals
    - Technical levels
    - Company info
    - Matched strategies
    - Trading opportunities summary
    """
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        from services.scoring_engine import get_scoring_engine
        from services.feature_engine import get_feature_engine
        from services.strategy_service import StrategyService
        from pymongo import MongoClient
        import os
        
        symbol = symbol.upper()
        analysis = {
            "symbol": symbol,
            "timestamp": None,
            "quote": {},
            "company_info": {},
            "fundamentals": {},
            "technicals": {},
            "scores": {},
            "matched_strategies": [],
            "support_resistance": {},
            "trading_summary": {},
            "news": []
        }
        
        # Get current quote
        try:
            quote = await _ib_service.get_quote(symbol)
            analysis["quote"] = quote or {}
            from datetime import datetime, timezone
            analysis["timestamp"] = datetime.now(timezone.utc).isoformat()
        except:
            pass
        
        # Get fundamentals from IB
        try:
            fundamentals = await _ib_service.get_fundamentals(symbol)
            analysis["fundamentals"] = fundamentals or {}
            
            # Extract company info
            analysis["company_info"] = {
                "name": fundamentals.get("company_name", symbol),
                "sector": fundamentals.get("sector", "Unknown"),
                "industry": fundamentals.get("industry", "Unknown"),
                "market_cap": fundamentals.get("market_cap", 0),
                "employees": fundamentals.get("employees"),
                "description": fundamentals.get("description", "")[:500] if fundamentals.get("description") else ""
            }
        except:
            pass
        
        # Get historical data for technicals
        try:
            hist_data = await _ib_service.get_historical_data(
                symbol=symbol,
                duration="5 D",
                bar_size="5 mins"
            )
            bars = hist_data.get("bars", [])
            
            if bars:
                feature_engine = get_feature_engine()
                
                # Calculate technical features
                features = feature_engine.calc_all_features(bars, symbol)
                
                analysis["technicals"] = {
                    "ema_9": features.get("ema_9", 0),
                    "ema_20": features.get("ema_20", 0),
                    "sma_50": features.get("sma_50", 0),
                    "sma_200": features.get("sma_200", 0),
                    "rsi_14": features.get("rsi_14", 50),
                    "macd": features.get("macd", 0),
                    "macd_signal": features.get("macd_signal", 0),
                    "macd_histogram": features.get("macd_hist", 0),
                    "atr_14": features.get("atr_14", 0),
                    "rvol": features.get("rvol_20", 1),
                    "vwap": features.get("vwap", 0),
                    "vwap_distance_pct": features.get("vwap_distance_pct", 0),
                    "volume_trend": "Above Avg" if features.get("rvol_20", 1) > 1.5 else "Below Avg" if features.get("rvol_20", 1) < 0.7 else "Normal",
                    "trend": "Bullish" if features.get("close", 0) > features.get("ema_20", 0) else "Bearish"
                }
                
                # Calculate support/resistance
                highs = [b.get("high", 0) for b in bars[-50:]]
                lows = [b.get("low", 0) for b in bars[-50:]]
                close = bars[-1].get("close", 0) if bars else 0
                
                analysis["support_resistance"] = {
                    "resistance_1": max(highs) if highs else 0,
                    "resistance_2": sorted(highs, reverse=True)[min(5, len(highs)-1)] if len(highs) > 5 else max(highs) if highs else 0,
                    "support_1": min(lows) if lows else 0,
                    "support_2": sorted(lows)[min(5, len(lows)-1)] if len(lows) > 5 else min(lows) if lows else 0,
                    "pivot": (max(highs) + min(lows) + close) / 3 if highs and lows else close,
                    "day_high": bars[-1].get("high", 0) if bars else 0,
                    "day_low": bars[-1].get("low", 0) if bars else 0
                }
        except Exception as e:
            print(f"Error getting technicals: {e}")
        
        # Get scoring from Universal Scoring Engine
        try:
            scoring_engine = get_scoring_engine()
            if scoring_engine and analysis["quote"]:
                score_result = scoring_engine.calculate_score(
                    symbol=symbol,
                    current_price=analysis["quote"].get("price", 0),
                    vwap=analysis["technicals"].get("vwap", 0),
                    rvol=analysis["technicals"].get("rvol", 1),
                    gap_percent=analysis["quote"].get("change_percent", 0),
                    market_cap=analysis["fundamentals"].get("market_cap", 10000000000),
                    patterns=[],
                    bias="neutral"
                )
                analysis["scores"] = {
                    "overall": score_result.get("overall_score", 50),
                    "technical_score": score_result.get("technical_score", 50),
                    "fundamental_score": score_result.get("fundamental_score", 50),
                    "catalyst_score": score_result.get("catalyst_score", 50),
                    "risk_score": score_result.get("risk_score", 50),
                    "direction": score_result.get("direction", "NEUTRAL"),
                    "confidence": score_result.get("confidence", 50),
                    "grade": "A" if score_result.get("overall_score", 0) >= 80 else "B" if score_result.get("overall_score", 0) >= 65 else "C" if score_result.get("overall_score", 0) >= 50 else "D"
                }
        except Exception as e:
            print(f"Error getting scores: {e}")
            analysis["scores"] = {"overall": 50, "grade": "C", "direction": "NEUTRAL"}
        
        # Match against user strategies
        try:
            mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
            db_name = os.environ.get("DB_NAME", "tradecommand")
            client = MongoClient(mongo_url)
            db = client[db_name]
            
            strategies = list(db["strategies"].find({}, {"_id": 0}))
            matched = []
            
            # Simple strategy matching based on current conditions
            price = analysis["quote"].get("price", 0)
            change_pct = analysis["quote"].get("change_percent", 0)
            rvol = analysis["technicals"].get("rvol", 1)
            rsi = analysis["technicals"].get("rsi_14", 50)
            
            for strat in strategies[:50]:  # Check first 50
                match_score = 0
                match_reasons = []
                
                criteria = strat.get("criteria", [])
                criteria_text = " ".join(criteria).lower()
                
                # Check various conditions
                if "gap" in criteria_text and abs(change_pct) >= 3:
                    match_score += 25
                    match_reasons.append(f"Gap {change_pct:+.1f}%")
                
                if "volume" in criteria_text and rvol >= 2:
                    match_score += 25
                    match_reasons.append(f"High RVOL ({rvol:.1f}x)")
                
                if "momentum" in criteria_text and abs(change_pct) >= 2:
                    match_score += 20
                    match_reasons.append("Strong momentum")
                
                if "oversold" in criteria_text and rsi < 30:
                    match_score += 30
                    match_reasons.append(f"RSI oversold ({rsi:.0f})")
                
                if "overbought" in criteria_text and rsi > 70:
                    match_score += 30
                    match_reasons.append(f"RSI overbought ({rsi:.0f})")
                
                if "breakout" in criteria_text and change_pct > 2:
                    match_score += 25
                    match_reasons.append("Potential breakout")
                
                if "reversal" in criteria_text and ((change_pct < -3 and rsi < 35) or (change_pct > 3 and rsi > 65)):
                    match_score += 25
                    match_reasons.append("Reversal setup")
                
                if match_score >= 25:
                    matched.append({
                        "id": strat.get("id"),
                        "name": strat.get("name"),
                        "category": strat.get("category"),
                        "match_score": match_score,
                        "match_reasons": match_reasons,
                        "entry_rules": strat.get("entry_rules"),
                        "stop_loss": strat.get("stop_loss")
                    })
            
            # Sort by match score
            matched.sort(key=lambda x: x.get("match_score", 0), reverse=True)
            analysis["matched_strategies"] = matched[:5]  # Top 5 matches
            
            client.close()
        except Exception as e:
            print(f"Error matching strategies: {e}")
        
        # Generate trading summary
        quote = analysis["quote"]
        technicals = analysis["technicals"]
        scores = analysis["scores"]
        matched_strats = analysis["matched_strategies"]
        
        # Determine bias
        bullish_signals = 0
        bearish_signals = 0
        
        if technicals.get("rsi_14", 50) > 50: bullish_signals += 1
        else: bearish_signals += 1
        
        if quote.get("change_percent", 0) > 0: bullish_signals += 1
        else: bearish_signals += 1
        
        if technicals.get("vwap_distance_pct", 0) > 0: bullish_signals += 1
        else: bearish_signals += 1
        
        if technicals.get("macd_histogram", 0) > 0: bullish_signals += 1
        else: bearish_signals += 1
        
        if bullish_signals > bearish_signals:
            bias = "BULLISH"
            bias_strength = "Strong" if bullish_signals >= 3 else "Moderate"
        elif bearish_signals > bullish_signals:
            bias = "BEARISH"
            bias_strength = "Strong" if bearish_signals >= 3 else "Moderate"
        else:
            bias = "NEUTRAL"
            bias_strength = ""
        
        # Calculate suggested entry/stop/target
        price = quote.get("price", 0)
        atr = technicals.get("atr_14", price * 0.02)
        
        if bias == "BULLISH":
            entry = price
            stop = price - (1.5 * atr)
            target = price + (3 * atr)
        elif bias == "BEARISH":
            entry = price
            stop = price + (1.5 * atr)
            target = price - (3 * atr)
        else:
            entry = price
            stop = price - (1.5 * atr)
            target = price + (2 * atr)
        
        analysis["trading_summary"] = {
            "bias": bias,
            "bias_strength": bias_strength,
            "overall_score": scores.get("overall", 50),
            "grade": scores.get("grade", "C"),
            "confidence": scores.get("confidence", 50),
            "bullish_signals": bullish_signals,
            "bearish_signals": bearish_signals,
            "suggested_direction": "LONG" if bias == "BULLISH" else "SHORT" if bias == "BEARISH" else "WAIT",
            "entry": round(entry, 2),
            "stop_loss": round(stop, 2),
            "target": round(target, 2),
            "risk_reward": round(abs(target - entry) / abs(entry - stop), 2) if abs(entry - stop) > 0 else 0,
            "top_strategy": matched_strats[0] if matched_strats else None,
            "summary": f"{bias_strength} {bias} bias. " + (f"Top match: {matched_strats[0]['name']} ({matched_strats[0]['match_score']}% match). " if matched_strats else "") + f"Score: {scores.get('overall', 50)}/100 ({scores.get('grade', 'C')})"
        }
        
        # Get news
        try:
            news = await _ib_service.get_news_for_symbol(symbol)
            analysis["news"] = news[:5] if news else []
        except:
            pass
        
        return analysis
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing {symbol}: {str(e)}")
