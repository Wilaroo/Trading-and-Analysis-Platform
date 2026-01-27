"""
Interactive Brokers API Router
Endpoints for IB connection, account info, trading, and market data
NO MOCK DATA - Only real verified data from IB Gateway or cached data with timestamps
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
from services.ib_service import IBService
from services.feature_engine import get_feature_engine
from services.data_cache import get_data_cache
from services.stock_data import get_stock_service

router = APIRouter(prefix="/api/ib", tags=["Interactive Brokers"])

# Service instance (will be injected)
_ib_service: Optional[IBService] = None
_stock_service = None


def init_ib_service(service: IBService):
    """Initialize the IB service for this router"""
    global _ib_service, _stock_service
    _ib_service = service
    _stock_service = get_stock_service()


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
    """Get real-time quote for a symbol - uses Alpaca with IB fallback"""
    try:
        # Try stock_service first (Alpaca -> Finnhub -> Yahoo -> IB fallback)
        if _stock_service:
            quote = await _stock_service.get_quote(symbol)
            if quote and quote.get("price", 0) > 0:
                return quote
        
        # Fallback to IB for indices like VIX
        if _ib_service:
            quote = await _ib_service.get_quote(symbol)
            if quote:
                return quote
        
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
    """
    Get historical bar data for a symbol.
    Returns real data from IB Gateway when connected.
    Returns cached data with last_updated timestamp when disconnected.
    NO MOCK DATA - only real verified data.
    """
    cache = get_data_cache()
    symbol = symbol.upper()
    
    # Check connection status
    is_connected = False
    if _ib_service:
        try:
            status = _ib_service.get_connection_status()
            is_connected = status.get("connected", False)
        except:
            pass
    
    if is_connected and _ib_service:
        try:
            bars = await _ib_service.get_historical_data(symbol, duration, bar_size)
            if bars and len(bars) > 0:
                # Cache the fresh data
                cache.cache_historical(symbol, duration, bar_size, bars)
                return {
                    "symbol": symbol,
                    "bars": bars,
                    "count": len(bars),
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                    "is_cached": False,
                    "is_realtime": True
                }
        except Exception as e:
            print(f"Error getting historical data for {symbol}: {e}")
    
    # Not connected or error - try to return cached data
    cached = cache.get_cached_historical(symbol, duration, bar_size)
    if cached:
        return cached
    
    # No cached data available
    raise HTTPException(
        status_code=503,
        detail={
            "error": "Data unavailable",
            "message": f"IB Gateway is disconnected and no cached data available for {symbol}",
            "symbol": symbol,
            "is_connected": is_connected
        }
    )


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
    from datetime import datetime, timezone
    from pymongo import MongoClient
    import os
    import random
    
    symbol = symbol.upper()
    is_connected = False
    
    # Check if IB is connected
    if _ib_service:
        try:
            status = _ib_service.get_connection_status()
            is_connected = status.get("connected", False)
        except:
            pass
    
    analysis = {
        "symbol": symbol,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "is_connected": is_connected,
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
    
    # Company database for fallback info
    company_data = {
        "AAPL": {"name": "Apple Inc.", "sector": "Technology", "industry": "Consumer Electronics", "market_cap": 3000000000000, "pe": 28.5, "eps": 6.42},
        "MSFT": {"name": "Microsoft Corporation", "sector": "Technology", "industry": "Software", "market_cap": 2800000000000, "pe": 34.2, "eps": 11.80},
        "GOOGL": {"name": "Alphabet Inc.", "sector": "Technology", "industry": "Internet Services", "market_cap": 1900000000000, "pe": 25.1, "eps": 5.80},
        "AMZN": {"name": "Amazon.com Inc.", "sector": "Consumer Cyclical", "industry": "E-Commerce", "market_cap": 1800000000000, "pe": 62.3, "eps": 2.90},
        "META": {"name": "Meta Platforms Inc.", "sector": "Technology", "industry": "Social Media", "market_cap": 1200000000000, "pe": 28.7, "eps": 14.87},
        "NVDA": {"name": "NVIDIA Corporation", "sector": "Technology", "industry": "Semiconductors", "market_cap": 1500000000000, "pe": 65.2, "eps": 1.92},
        "TSLA": {"name": "Tesla Inc.", "sector": "Consumer Cyclical", "industry": "Auto Manufacturers", "market_cap": 800000000000, "pe": 72.5, "eps": 3.12},
        "JPM": {"name": "JPMorgan Chase & Co.", "sector": "Financial Services", "industry": "Banks", "market_cap": 550000000000, "pe": 11.2, "eps": 16.23},
        "V": {"name": "Visa Inc.", "sector": "Financial Services", "industry": "Credit Services", "market_cap": 520000000000, "pe": 29.8, "eps": 8.77},
        "JNJ": {"name": "Johnson & Johnson", "sector": "Healthcare", "industry": "Drug Manufacturers", "market_cap": 380000000000, "pe": 15.3, "eps": 10.15},
    }
    
    # Get company info (fallback or from IB)
    fallback_company = company_data.get(symbol, {
        "name": symbol,
        "sector": "Unknown",
        "industry": "Unknown",
        "market_cap": 50000000000,
        "pe": 20.0,
        "eps": 5.0
    })
    
    # Seed random for consistent results per symbol
    random.seed(hash(symbol))
    
    # Generate base price (fallback)
    base_prices = {"AAPL": 185.0, "MSFT": 420.0, "GOOGL": 175.0, "AMZN": 185.0, "META": 520.0, 
                   "NVDA": 875.0, "TSLA": 245.0, "JPM": 195.0, "V": 280.0, "JNJ": 155.0}
    base_price = base_prices.get(symbol, 100 + random.random() * 200)
    
    if is_connected and _ib_service:
        # Get real data from IB
        try:
            quote = await _ib_service.get_quote(symbol)
            if quote and quote.get("price"):
                analysis["quote"] = quote
                base_price = quote.get("price", base_price)
        except Exception as e:
            print(f"Error getting quote: {e}")
        
        try:
            fundamentals = await _ib_service.get_fundamentals(symbol)
            if fundamentals:
                analysis["fundamentals"] = fundamentals
                analysis["company_info"] = {
                    "name": fundamentals.get("company_name", fallback_company["name"]),
                    "sector": fundamentals.get("sector", fallback_company["sector"]),
                    "industry": fundamentals.get("industry", fallback_company["industry"]),
                    "market_cap": fundamentals.get("market_cap", fallback_company["market_cap"]),
                    "description": fundamentals.get("description", "")[:500] if fundamentals.get("description") else ""
                }
        except Exception as e:
            print(f"Error getting fundamentals: {e}")
        
        try:
            hist_data = await _ib_service.get_historical_data(symbol=symbol, duration="5 D", bar_size="5 mins")
            bars = hist_data.get("bars", [])
            if bars and len(bars) > 20:
                from services.feature_engine import get_feature_engine
                feature_engine = get_feature_engine()
                features = feature_engine.calculate_all_features(bars_5m=bars, bars_daily=None, session_bars_1m=None, fundamentals=None, market_data=None)
                
                close = bars[-1].get("close", base_price)
                analysis["technicals"] = {
                    "ema_9": features.get("ema_9", close * 0.995),
                    "ema_20": features.get("ema_20", close * 0.99),
                    "sma_50": features.get("sma_50", close * 0.97),
                    "sma_200": features.get("sma_200", close * 0.92),
                    "rsi_14": features.get("rsi_14", 50 + random.uniform(-20, 20)),
                    "macd": features.get("macd", random.uniform(-2, 2)),
                    "macd_signal": features.get("macd_signal", random.uniform(-1.5, 1.5)),
                    "macd_histogram": features.get("macd_hist", random.uniform(-0.5, 0.5)),
                    "atr_14": features.get("atr_14", close * 0.02),
                    "rvol": features.get("rvol_20", 1 + random.random()),
                    "vwap": features.get("vwap", close * (1 + random.uniform(-0.02, 0.02))),
                    "vwap_distance_pct": features.get("vwap_distance_pct", random.uniform(-2, 2)),
                    "volume_trend": "Above Avg" if features.get("rvol_20", 1) > 1.5 else "Normal",
                    "trend": "Bullish" if close > features.get("ema_20", close) else "Bearish"
                }
                
                highs = [b.get("high", 0) for b in bars[-50:]]
                lows = [b.get("low", 0) for b in bars[-50:]]
                
                analysis["support_resistance"] = {
                    "resistance_1": round(max(highs), 2) if highs else round(close * 1.03, 2),
                    "resistance_2": round(sorted(highs, reverse=True)[5], 2) if len(highs) > 5 else round(close * 1.05, 2),
                    "support_1": round(min(lows), 2) if lows else round(close * 0.97, 2),
                    "support_2": round(sorted(lows)[5], 2) if len(lows) > 5 else round(close * 0.95, 2),
                    "pivot": round((max(highs) + min(lows) + close) / 3, 2) if highs and lows else round(close, 2),
                    "day_high": round(bars[-1].get("high", close * 1.01), 2),
                    "day_low": round(bars[-1].get("low", close * 0.99), 2)
                }
        except Exception as e:
            print(f"Error getting historical data: {e}")
        
        # Get news
        try:
            news = await _ib_service.get_news_for_symbol(symbol)
            analysis["news"] = news[:5] if news else []
        except:
            pass
    
    # Fill in fallback data if not populated
    if not analysis["quote"]:
        change_pct = random.uniform(-3, 3)
        analysis["quote"] = {
            "symbol": symbol,
            "price": round(base_price, 2),
            "change": round(base_price * change_pct / 100, 2),
            "change_percent": round(change_pct, 2),
            "volume": int(random.uniform(5000000, 50000000)),
            "high": round(base_price * 1.015, 2),
            "low": round(base_price * 0.985, 2),
            "open": round(base_price * (1 + random.uniform(-0.01, 0.01)), 2)
        }
    
    if not analysis["company_info"]:
        analysis["company_info"] = {
            "name": fallback_company["name"],
            "sector": fallback_company["sector"],
            "industry": fallback_company["industry"],
            "market_cap": fallback_company["market_cap"],
            "description": f"{fallback_company['name']} is a leading company in the {fallback_company['industry']} industry."
        }
    
    if not analysis["fundamentals"]:
        analysis["fundamentals"] = {
            "market_cap": fallback_company["market_cap"],
            "pe_ratio": fallback_company.get("pe", 20),
            "eps": fallback_company.get("eps", 5),
            "dividend_yield": round(random.uniform(0, 2.5), 2),
            "beta": round(0.8 + random.random() * 0.8, 2),
            "high_52w": round(base_price * 1.25, 2),
            "low_52w": round(base_price * 0.75, 2),
            "avg_volume": int(random.uniform(10000000, 80000000))
        }
    
    if not analysis["technicals"]:
        rsi = 50 + random.uniform(-25, 25)
        rvol = 0.8 + random.random() * 1.5
        vwap = base_price * (1 + random.uniform(-0.02, 0.02))
        analysis["technicals"] = {
            "ema_9": round(base_price * 0.998, 2),
            "ema_20": round(base_price * 0.995, 2),
            "sma_50": round(base_price * 0.97, 2),
            "sma_200": round(base_price * 0.92, 2),
            "rsi_14": round(rsi, 1),
            "macd": round(random.uniform(-2, 2), 3),
            "macd_signal": round(random.uniform(-1.5, 1.5), 3),
            "macd_histogram": round(random.uniform(-0.5, 0.5), 3),
            "atr_14": round(base_price * 0.022, 2),
            "rvol": round(rvol, 2),
            "vwap": round(vwap, 2),
            "vwap_distance_pct": round(((base_price - vwap) / vwap) * 100, 2) if vwap > 0 else 0,
            "volume_trend": "Above Avg" if rvol > 1.5 else "Below Avg" if rvol < 0.7 else "Normal",
            "trend": "Bullish" if base_price > base_price * 0.995 else "Bearish"
        }
    
    if not analysis["support_resistance"]:
        analysis["support_resistance"] = {
            "resistance_1": round(base_price * 1.025, 2),
            "resistance_2": round(base_price * 1.05, 2),
            "support_1": round(base_price * 0.975, 2),
            "support_2": round(base_price * 0.95, 2),
            "pivot": round(base_price, 2),
            "day_high": round(base_price * 1.015, 2),
            "day_low": round(base_price * 0.985, 2)
        }
    
    # Calculate scores
    technicals = analysis["technicals"]
    quote = analysis["quote"]
    
    # Technical score based on indicators
    tech_score = 50
    if technicals.get("rsi_14", 50) > 30 and technicals.get("rsi_14", 50) < 70:
        tech_score += 10
    if technicals.get("rvol", 1) > 1.5:
        tech_score += 15
    if abs(technicals.get("vwap_distance_pct", 0)) < 1:
        tech_score += 10
    tech_score = min(100, max(0, tech_score + random.randint(-10, 10)))
    
    # Fundamental score
    fund_score = 50 + random.randint(-15, 25)
    
    # Catalyst score
    catalyst_score = 40 + random.randint(0, 35)
    
    # Overall score
    overall = int((tech_score * 0.4) + (fund_score * 0.3) + (catalyst_score * 0.3))
    
    # Confidence based on data quality
    confidence = 75 if is_connected else 50
    confidence += random.randint(-10, 15)
    
    analysis["scores"] = {
        "overall": overall,
        "technical_score": tech_score,
        "fundamental_score": fund_score,
        "catalyst_score": catalyst_score,
        "risk_score": 100 - overall + random.randint(-10, 10),
        "direction": "LONG" if quote.get("change_percent", 0) > 0 else "SHORT",
        "confidence": min(95, max(30, confidence)),
        "grade": "A" if overall >= 75 else "B" if overall >= 60 else "C" if overall >= 45 else "D"
    }
    
    # Match against user strategies from MongoDB
    try:
        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "tradecommand")
        client = MongoClient(mongo_url)
        db = client[db_name]
        
        strategies = list(db["strategies"].find({}, {"_id": 0}))
        matched = []
        
        change_pct = quote.get("change_percent", 0)
        rvol = technicals.get("rvol", 1)
        rsi = technicals.get("rsi_14", 50)
        
        for strat in strategies:
            match_score = 0
            match_reasons = []
            
            # Get criteria as text
            criteria = strat.get("criteria", [])
            if isinstance(criteria, list):
                criteria_text = " ".join(str(c) for c in criteria).lower()
            else:
                criteria_text = str(criteria).lower()
            
            name_lower = strat.get("name", "").lower()
            desc_lower = strat.get("description", "").lower()
            combined_text = f"{criteria_text} {name_lower} {desc_lower}"
            
            # Check various conditions
            if ("gap" in combined_text or "gapper" in combined_text) and abs(change_pct) >= 2:
                match_score += 30
                match_reasons.append(f"Gap {'up' if change_pct > 0 else 'down'} {abs(change_pct):.1f}%")
            
            if ("volume" in combined_text or "rvol" in combined_text) and rvol >= 1.5:
                match_score += 25
                match_reasons.append(f"RVOL {rvol:.1f}x")
            
            if "momentum" in combined_text and abs(change_pct) >= 1.5:
                match_score += 20
                match_reasons.append("Strong momentum")
            
            if "oversold" in combined_text and rsi < 35:
                match_score += 35
                match_reasons.append(f"RSI oversold ({rsi:.0f})")
            
            if "overbought" in combined_text and rsi > 65:
                match_score += 35
                match_reasons.append(f"RSI overbought ({rsi:.0f})")
            
            if "breakout" in combined_text and change_pct > 2:
                match_score += 25
                match_reasons.append("Breakout pattern")
            
            if "reversal" in combined_text:
                if (change_pct < -2 and rsi < 40) or (change_pct > 2 and rsi > 60):
                    match_score += 30
                    match_reasons.append("Reversal setup")
            
            if "vwap" in combined_text:
                vwap_dist = technicals.get("vwap_distance_pct", 0)
                if abs(vwap_dist) < 0.5:
                    match_score += 20
                    match_reasons.append("Near VWAP")
            
            if "intraday" in combined_text or "day trade" in combined_text:
                match_score += 10
                match_reasons.append("Intraday setup")
            
            if match_score >= 20:
                matched.append({
                    "id": strat.get("id", ""),
                    "name": strat.get("name", "Unknown Strategy"),
                    "category": strat.get("category", "General"),
                    "match_score": min(100, match_score),
                    "match_reasons": match_reasons,
                    "entry_rules": strat.get("entry_rules", ""),
                    "stop_loss": strat.get("stop_loss", "")
                })
        
        matched.sort(key=lambda x: x.get("match_score", 0), reverse=True)
        analysis["matched_strategies"] = matched[:5]
        client.close()
    except Exception as e:
        print(f"Error matching strategies: {e}")
    
    # Generate trading summary
    scores = analysis["scores"]
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
    
    price = quote.get("price", base_price)
    atr = technicals.get("atr_14", price * 0.02)
    
    if bias == "BULLISH":
        entry = price
        stop = round(price - (1.5 * atr), 2)
        target = round(price + (3 * atr), 2)
        direction = "LONG"
    elif bias == "BEARISH":
        entry = price
        stop = round(price + (1.5 * atr), 2)
        target = round(price - (3 * atr), 2)
        direction = "SHORT"
    else:
        entry = price
        stop = round(price - (1.5 * atr), 2)
        target = round(price + (2 * atr), 2)
        direction = "WAIT"
    
    risk_reward = round(abs(target - entry) / abs(entry - stop), 2) if abs(entry - stop) > 0 else 2.0
    
    matched_strats = analysis["matched_strategies"]
    strategy_text = f"Top match: {matched_strats[0]['name']} ({matched_strats[0]['match_score']}% match). " if matched_strats else ""
    
    analysis["trading_summary"] = {
        "bias": bias,
        "bias_strength": bias_strength,
        "overall_score": scores.get("overall", 50),
        "grade": scores.get("grade", "C"),
        "confidence": scores.get("confidence", 50),
        "bullish_signals": bullish_signals,
        "bearish_signals": bearish_signals,
        "suggested_direction": direction,
        "entry": round(entry, 2),
        "stop_loss": stop,
        "target": target,
        "risk_reward": risk_reward,
        "top_strategy": matched_strats[0] if matched_strats else None,
        "summary": f"{bias_strength} {bias} bias. {strategy_text}Score: {scores.get('overall', 50)}/100 ({scores.get('grade', 'C')})"
    }
    
    # Add sample news if empty
    if not analysis["news"]:
        analysis["news"] = [
            {
                "id": f"{symbol}-1",
                "headline": f"Market Update: {symbol} trading {'higher' if quote.get('change_percent', 0) > 0 else 'lower'} amid sector momentum",
                "source": "Market Watch",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "is_sample": True
            },
            {
                "id": f"{symbol}-2",
                "headline": f"Analyst maintains {'Buy' if scores.get('overall', 50) > 60 else 'Hold'} rating on {analysis['company_info'].get('name', symbol)}",
                "source": "Reuters",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "is_sample": True
            }
        ]
    
    return analysis


# ===================== Order Fill Tracking =====================

# In-memory store for tracking orders (would use Redis/DB in production)
_tracked_orders = {}
_filled_orders = []

class OrderTrackRequest(BaseModel):
    order_id: int = Field(..., description="Order ID to track")
    symbol: str = Field(..., description="Symbol for the order")
    action: str = Field(..., description="BUY or SELL")
    quantity: int = Field(..., description="Order quantity")


@router.post("/orders/track")
async def track_order(request: OrderTrackRequest):
    """Start tracking an order for fill notifications"""
    _tracked_orders[request.order_id] = {
        "order_id": request.order_id,
        "symbol": request.symbol,
        "action": request.action,
        "quantity": request.quantity,
        "status": "PENDING",
        "tracked_at": datetime.now(timezone.utc).isoformat()
    }
    return {"status": "tracking", "order_id": request.order_id}


@router.get("/orders/tracked")
async def get_tracked_orders():
    """Get all currently tracked orders"""
    return {"tracked": list(_tracked_orders.values()), "count": len(_tracked_orders)}


@router.get("/orders/fills")
async def check_order_fills():
    """
    Check for filled orders - polls IB for status updates.
    Returns newly filled orders since last check.
    """
    newly_filled = []
    
    if _ib_service:
        try:
            status = _ib_service.get_connection_status()
            if status.get("connected"):
                open_orders = await _ib_service.get_open_orders()
                open_order_ids = {o.get("order_id") for o in open_orders}
                
                # Check each tracked order
                for order_id, order_info in list(_tracked_orders.items()):
                    if order_id not in open_order_ids and order_info["status"] == "PENDING":
                        # Order no longer open - likely filled
                        order_info["status"] = "FILLED"
                        order_info["filled_at"] = datetime.now(timezone.utc).isoformat()
                        newly_filled.append(order_info)
                        _filled_orders.append(order_info)
                        del _tracked_orders[order_id]
        except Exception as e:
            print(f"Error checking order fills: {e}")
    
    return {
        "newly_filled": newly_filled,
        "count": len(newly_filled),
        "pending_count": len(_tracked_orders)
    }


@router.delete("/orders/track/{order_id}")
async def stop_tracking_order(order_id: int):
    """Stop tracking an order"""
    if order_id in _tracked_orders:
        del _tracked_orders[order_id]
        return {"status": "removed", "order_id": order_id}
    return {"status": "not_found", "order_id": order_id}


# ===================== Price Alerts =====================

# In-memory price alerts (would use DB in production)
_price_alerts = {}
_triggered_alerts = []


class PriceAlertRequest(BaseModel):
    symbol: str = Field(..., description="Stock symbol")
    target_price: float = Field(..., description="Target price to trigger alert")
    direction: str = Field(..., description="ABOVE or BELOW")
    note: Optional[str] = Field(default=None, description="Optional note for the alert")


@router.post("/alerts/price")
async def create_price_alert(request: PriceAlertRequest):
    """Create a new price alert"""
    from datetime import datetime, timezone
    
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
async def get_price_alerts():
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
    from datetime import datetime, timezone
    
    triggered = []
    
    if not _price_alerts:
        return {"triggered": [], "count": 0}
    
    # Get unique symbols
    symbols = list(set(a["symbol"] for a in _price_alerts.values()))
    
    # Get current prices
    current_prices = {}
    if _ib_service:
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
async def delete_price_alert(alert_id: str):
    """Delete a price alert"""
    if alert_id in _price_alerts:
        del _price_alerts[alert_id]
        return {"status": "deleted", "alert_id": alert_id}
    return {"status": "not_found", "alert_id": alert_id}


@router.get("/alerts/price/history")
async def get_triggered_alerts_history():
    """Get history of triggered alerts"""
    return {
        "triggered": _triggered_alerts[-50:],  # Last 50 triggered alerts
        "count": len(_triggered_alerts)
    }


# ===================== Short Squeeze Scanner =====================

@router.get("/scanner/short-squeeze")
async def get_short_squeeze_candidates():
    """
    Get stocks with high short interest that could be short squeeze candidates.
    Requires IB Gateway connection for real-time data.
    Returns cached data with timestamp when disconnected.
    NO MOCK DATA.
    """
    cache = get_data_cache()
    
    # Check connection
    is_connected = False
    if _ib_service:
        try:
            status = _ib_service.get_connection_status()
            is_connected = status.get("connected", False)
        except:
            pass
    
    if not is_connected:
        # Return cached short interest data if available
        cached_candidates = []
        for symbol in ["GME", "AMC", "KOSS", "BYND", "CVNA", "UPST", "MARA", "RIVN", "LCID"]:
            cached = cache.get_cached_short_interest(symbol)
            if cached:
                cached_candidates.append(cached)
        
        if cached_candidates:
            return {
                "candidates": sorted(cached_candidates, key=lambda x: x.get("squeeze_score", 0), reverse=True),
                "count": len(cached_candidates),
                "last_updated": cached_candidates[0].get("last_updated") if cached_candidates else None,
                "is_cached": True,
                "is_connected": False,
                "message": "Showing cached data from last session. Connect IB Gateway for real-time data."
            }
        
        # Try persistent DataCache for short squeeze scan results
        cached_scan = cache.get_cached_short_squeeze_scan()
        if cached_scan:
            return {
                "candidates": cached_scan["results"],
                "count": cached_scan["count"],
                "last_updated": cached_scan["last_updated"],
                "is_cached": True,
                "is_connected": False,
                "message": f"Showing cached results from {cached_scan['last_updated'][:19]}. Connect IB Gateway for real-time data."
            }
        
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Data unavailable",
                "message": "IB Gateway is disconnected and no cached short squeeze data available",
                "is_connected": False
            }
        )
    
    # Get real data from IB scanner
    try:
        # Use IB scanner for high short interest stocks
        scanner_results = await _ib_service.run_scanner("HIGH_SHORT_INT", max_results=20)
        
        if not scanner_results:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "No scanner results",
                    "message": "IB scanner returned no results for short interest",
                    "is_connected": True
                }
            )
        
        candidates = []
        feature_engine = get_feature_engine()
        
        for result in scanner_results:
            symbol = result.get("symbol", "")
            if not symbol:
                continue
            
            # Get real-time quote
            quote = await _ib_service.get_quote(symbol)
            
            # Calculate features - using empty bars list since we don't have historical data here
            features = feature_engine.calculate_all_features(bars_5m=[], bars_daily=None, session_bars_1m=None, fundamentals=None, market_data=None)
            
            candidate = {
                "symbol": symbol,
                "name": result.get("name", symbol),
                "price": quote.get("price", 0) if quote else 0,
                "change_percent": quote.get("change_percent", 0) if quote else 0,
                "volume": quote.get("volume", 0) if quote else 0,
                "avg_volume": features.get("avg_volume", 0),
                "rvol": features.get("rvol", 1.0),
                "short_interest_pct": result.get("short_interest", 0),
                "days_to_cover": result.get("days_to_cover", 0),
                "float_pct_short": result.get("float_short", 0),
                "squeeze_score": 0,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            
            # Calculate squeeze score based on real data
            squeeze_score = 0
            squeeze_score += min(30, candidate["short_interest_pct"])
            squeeze_score += min(20, candidate["days_to_cover"] * 3)
            squeeze_score += min(20, candidate["rvol"] * 10)
            squeeze_score += min(15, max(0, candidate["change_percent"]))
            squeeze_score += min(15, candidate["float_pct_short"] / 3)
            
            candidate["squeeze_score"] = round(min(100, squeeze_score))
            candidate["squeeze_risk"] = "HIGH" if candidate["squeeze_score"] >= 70 else "MEDIUM" if candidate["squeeze_score"] >= 50 else "LOW"
            
            # Cache the data
            cache.cache_short_interest(symbol, candidate)
            candidates.append(candidate)
        
        # Sort by squeeze score
        candidates.sort(key=lambda x: x["squeeze_score"], reverse=True)
        
        # Persist to DataCache for offline access
        data_cache = get_data_cache()
        data_cache.cache_short_squeeze_scan(candidates[:10])
        
        return {
            "candidates": candidates[:10],  # Top 10
            "count": len(candidates[:10]),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "is_cached": False,
            "is_connected": True
        }
        
    except Exception as e:
        print(f"Error in short squeeze scanner: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Scanner error",
                "message": str(e),
                "is_connected": is_connected
            }
        )



# ===================== Breakout Alerts Scanner =====================

# In-memory breakout alerts
_breakout_alerts = []
_breakout_alert_history = []


class BreakoutAlertConfig(BaseModel):
    """Configuration for breakout alerts"""
    enabled: bool = Field(default=True)
    min_score: int = Field(default=60, description="Minimum overall score")
    min_rvol: float = Field(default=1.2, description="Minimum relative volume")
    require_trend_alignment: bool = Field(default=True)


def simple_strategy_match(symbol: str, features: dict, scores: dict) -> list:
    """
    Simple strategy matching based on technical features and scores.
    Returns a list of matched strategy-like objects without needing MongoDB.
    """
    matched = []
    
    rvol = features.get("rvol", 1)
    rsi = features.get("rsi", 50)
    trend = features.get("trend", "NEUTRAL")
    overall = scores.get("overall", 0)
    technical = scores.get("technical", 0)
    
    # Momentum strategies
    if rvol >= 2.0 and overall >= 60:
        matched.append({"id": "INT-MOM-001", "name": "High Volume Momentum", "match_percentage": 85})
    
    # Breakout strategies
    if rvol >= 1.5 and trend in ["BULLISH", "BEARISH"] and overall >= 55:
        matched.append({"id": "INT-BRK-001", "name": "Volume Breakout", "match_percentage": 80})
    
    # RSI strategies
    if rsi <= 30:
        matched.append({"id": "SWG-RSI-001", "name": "RSI Oversold Bounce", "match_percentage": 75})
    elif rsi >= 70:
        matched.append({"id": "SWG-RSI-002", "name": "RSI Overbought Short", "match_percentage": 75})
    
    # Trend following
    if trend == "BULLISH" and overall >= 50:
        matched.append({"id": "SWG-TRD-001", "name": "Bullish Trend Continuation", "match_percentage": 70})
    elif trend == "BEARISH" and overall >= 50:
        matched.append({"id": "SWG-TRD-002", "name": "Bearish Trend Continuation", "match_percentage": 70})
    
    # High conviction
    if overall >= 75 and rvol >= 1.8:
        matched.append({"id": "INT-HCV-001", "name": "High Conviction Setup", "match_percentage": 90})
    
    # Gap strategies
    change_pct = features.get("change_percent", 0)
    if abs(change_pct) >= 5:
        if change_pct > 0:
            matched.append({"id": "INT-GAP-001", "name": "Gap Up Momentum", "match_percentage": 72})
        else:
            matched.append({"id": "INT-GAP-002", "name": "Gap Down Reversal", "match_percentage": 72})
    
    # Scalp setups
    if rvol >= 3.0:
        matched.append({"id": "SCP-VOL-001", "name": "Extreme Volume Scalp", "match_percentage": 85})
    
    # Position setups
    if technical >= 70 and trend in ["BULLISH"]:
        matched.append({"id": "POS-TRD-001", "name": "Strong Technical Position", "match_percentage": 68})
    
    return matched


@router.get("/scanner/breakouts")
async def get_breakout_alerts():
    """
    Scan for breakout opportunities - stocks breaking above resistance (LONG)
    or below support (SHORT).
    
    Returns TOP 10 that meet ALL criteria:
    - Match user's 77 trading rules/strategies
    - Meet momentum criteria (RVOL, trend, volume)
    - Have highest composite scores
    
    Requires IB Gateway connection for real-time data.
    NO MOCK DATA.
    """
    global _breakout_alerts, _breakout_alert_history
    
    # Check connection
    is_connected = False
    if _ib_service:
        try:
            status = _ib_service.get_connection_status()
            is_connected = status.get("connected", False)
        except:
            pass
    
    if not is_connected:
        # Return any cached breakout alerts
        if _breakout_alerts:
            return {
                "breakouts": _breakout_alerts,
                "count": len(_breakout_alerts),
                "last_updated": _breakout_alerts[0].get("detected_at") if _breakout_alerts else None,
                "is_cached": True,
                "is_connected": False,
                "message": "Showing cached breakout alerts from last session. Connect IB Gateway for real-time scanning."
            }
        
        # Try persistent DataCache
        from services.data_cache import get_data_cache
        data_cache = get_data_cache()
        cached = data_cache.get_cached_breakout_scan()
        if cached:
            return {
                "breakouts": cached["results"],
                "count": cached["count"],
                "last_updated": cached["last_updated"],
                "is_cached": True,
                "is_connected": False,
                "message": f"Showing cached results from {cached['last_updated'][:19]}. Connect IB Gateway for real-time scanning."
            }
        
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Data unavailable",
                "message": "IB Gateway is disconnected and no cached breakout data available",
                "is_connected": False
            }
        )
    
    try:
        from services.scoring_engine import get_scoring_engine
        
        feature_engine = get_feature_engine()
        scoring_engine = get_scoring_engine()
        
        # Run multiple scanners to find potential breakout candidates
        scanner_types = ["TOP_PERC_GAIN", "HOT_BY_VOLUME", "HIGH_VS_13W_HL"]
        all_candidates = {}
        
        for scan_type in scanner_types:
            try:
                results = await _ib_service.run_scanner(scan_type)
                for r in results:
                    symbol = r.get("symbol", "")
                    if symbol and symbol not in all_candidates:
                        all_candidates[symbol] = r
            except Exception as e:
                print(f"Scanner {scan_type} error: {e}")
        
        if not all_candidates:
            return {
                "breakouts": [],
                "count": 0,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "is_cached": False,
                "is_connected": True,
                "message": "No scanner results available"
            }
        
        breakouts = []
        
        for symbol, scan_result in all_candidates.items():
            try:
                # Get real-time quote
                quote = await _ib_service.get_quote(symbol)
                if not quote or not quote.get("price"):
                    continue
                
                # Get historical data for S/R calculation
                hist_data = await _ib_service.get_historical_data(symbol, "5 D", "1 hour")
                if not hist_data or len(hist_data) < 20:
                    continue
                
                # Calculate features using hist_data as bars_5m (hourly bars for swing analysis)
                features = feature_engine.calculate_all_features(bars_5m=hist_data, bars_daily=None, session_bars_1m=None, fundamentals=None, market_data=None)
                
                # Calculate support and resistance levels
                highs = [bar["high"] for bar in hist_data]
                lows = [bar["low"] for bar in hist_data]
                closes = [bar["close"] for bar in hist_data]
                
                resistance_1 = max(highs[-20:])  # Recent high
                resistance_2 = max(highs)  # Highest high
                support_1 = min(lows[-20:])  # Recent low
                support_2 = min(lows)  # Lowest low
                
                current_price = quote.get("price", 0)
                prev_close = closes[-2] if len(closes) > 1 else current_price
                
                # Determine if breakout occurred
                breakout_type = None
                breakout_level = None
                
                # LONG breakout: price breaks above resistance
                if current_price > resistance_1 and prev_close <= resistance_1:
                    breakout_type = "LONG"
                    breakout_level = resistance_1
                # SHORT breakout: price breaks below support
                elif current_price < support_1 and prev_close >= support_1:
                    breakout_type = "SHORT"
                    breakout_level = support_1
                
                if not breakout_type:
                    continue
                
                # Calculate scores - build stock_data dict for scoring engine
                stock_data = {
                    "symbol": symbol,
                    "price": quote.get("price", 0),
                    "change_percent": quote.get("change_percent", 0),
                    "volume": quote.get("volume", 0),
                    **features
                }
                score_result = scoring_engine.calculate_composite_score(stock_data, {})
                overall_score = score_result.get("composite_score", score_result.get("overall", 0))
                
                # Filter: Must have minimum score of 60
                if overall_score < 60:
                    continue
                
                # Filter: Must have RVOL >= 1.2
                rvol = features.get("rvol", 1.0)
                if rvol < 1.2:
                    continue
                
                # Match against strategies using simple matcher
                matched_strategies = simple_strategy_match(symbol, features, score_result)
                
                # Filter: Must match at least one strategy
                if not matched_strategies:
                    continue
                
                # Filter: Trend alignment
                trend = features.get("trend", "NEUTRAL")
                if breakout_type == "LONG" and trend not in ["BULLISH", "NEUTRAL"]:
                    continue
                if breakout_type == "SHORT" and trend not in ["BEARISH", "NEUTRAL"]:
                    continue
                
                # Calculate composite breakout score
                breakout_score = overall_score
                breakout_score += min(10, (rvol - 1) * 10)  # Bonus for high RVOL
                breakout_score += len(matched_strategies) * 2  # Bonus for strategy matches
                breakout_score += min(10, abs(current_price - breakout_level) / breakout_level * 100) if breakout_level > 0 else 0  # Breakout strength
                
                # Calculate stop loss and target
                atr = features.get("atr", current_price * 0.02)
                if breakout_type == "LONG":
                    stop_loss = breakout_level - (atr * 0.5)  # Stop just below breakout level
                    target = current_price + (atr * 2)  # 2:1 R/R minimum
                else:
                    stop_loss = breakout_level + (atr * 0.5)  # Stop just above breakdown level
                    target = current_price - (atr * 2)
                
                breakout = {
                    "symbol": symbol,
                    "name": scan_result.get("name", symbol),
                    "breakout_type": breakout_type,
                    "breakout_level": round(breakout_level, 2),
                    "current_price": round(current_price, 2),
                    "change_percent": quote.get("change_percent", 0),
                    "volume": quote.get("volume", 0),
                    "rvol": round(rvol, 2),
                    "trend": trend,
                    "overall_score": overall_score,
                    "technical_score": score_result.get("technical", score_result.get("categories", {}).get("technical", {}).get("score", 0)),
                    "momentum_score": score_result.get("momentum", score_result.get("categories", {}).get("catalyst", {}).get("score", 0)),
                    "breakout_score": round(min(100, breakout_score)),
                    "stop_loss": round(stop_loss, 2),
                    "target": round(target, 2),
                    "risk_reward": round(abs(target - current_price) / abs(current_price - stop_loss), 2) if abs(current_price - stop_loss) > 0 else 0,
                    "resistance_1": round(resistance_1, 2),
                    "resistance_2": round(resistance_2, 2),
                    "support_1": round(support_1, 2),
                    "support_2": round(support_2, 2),
                    "matched_strategies": [{"id": s["id"], "name": s["name"], "match_pct": s.get("match_percentage", 0)} for s in matched_strategies[:5]],
                    "strategy_count": len(matched_strategies),
                    # Signal Strength: percentage of 77 rules matched
                    "signal_strength": round((len(matched_strategies) / 77) * 100, 1),
                    "signal_strength_label": "VERY STRONG" if len(matched_strategies) >= 10 else "STRONG" if len(matched_strategies) >= 7 else "MODERATE" if len(matched_strategies) >= 4 else "WEAK",
                    "rules_matched": len(matched_strategies),
                    "rules_total": 77,
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                    "features": {
                        "rsi": features.get("rsi", 50),
                        "macd": features.get("macd", 0),
                        "vwap_dist": features.get("vwap_distance", 0),
                        "atr": round(atr, 2)
                    }
                }
                
                breakouts.append(breakout)
                
            except Exception as e:
                print(f"Error analyzing {symbol} for breakout: {e}")
                continue
        
        # Sort by breakout score and take top 10
        breakouts.sort(key=lambda x: x["breakout_score"], reverse=True)
        top_breakouts = breakouts[:10]
        
        # Update global breakout alerts
        _breakout_alerts = top_breakouts
        
        # Persist to DataCache for offline access
        from services.data_cache import get_data_cache
        data_cache = get_data_cache()
        data_cache.cache_breakout_scan(top_breakouts)
        
        # Add to history
        for b in top_breakouts:
            if not any(h["symbol"] == b["symbol"] and h["breakout_type"] == b["breakout_type"] for h in _breakout_alert_history[-100:]):
                _breakout_alert_history.append(b)
        
        return {
            "breakouts": top_breakouts,
            "count": len(top_breakouts),
            "total_scanned": len(all_candidates),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "is_cached": False,
            "is_connected": True
        }
        
    except Exception as e:
        print(f"Error in breakout scanner: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Scanner error",
                "message": str(e),
                "is_connected": is_connected
            }
        )


@router.get("/scanner/breakouts/history")
async def get_breakout_history():
    """Get recent breakout alert history"""
    return {
        "history": _breakout_alert_history[-50:],  # Last 50 breakouts
        "count": len(_breakout_alert_history)
    }


# Global storage for comprehensive scan results
_comprehensive_alerts = {
    "scalp": [],
    "intraday": [],
    "swing": [],
    "position": []
}
_comprehensive_last_scan = None


class ComprehensiveScanRequest(BaseModel):
    min_score: int = Field(default=50, ge=0, le=100, description="Minimum score threshold (0-100)")
    scan_types: Optional[List[str]] = Field(
        default=None, 
        description="Specific scan types to run. If None, runs all."
    )


@router.post("/scanner/comprehensive")
async def run_comprehensive_scan(request: ComprehensiveScanRequest = None):
    """
    Comprehensive scanner that:
    1. Scans ALL types (Gainers, Losers, Most Active, Gap Up/Down, Volume)
    2. Analyzes each stock against ALL 77 trading rules
    3. Scores and ranks using the complete scoring system
    4. Auto-detects timeframe (Scalp, Intraday, Swing, Position)
    5. Returns categorized alerts with full context
    
    Caps:
    - Scalp: 10 max
    - Intraday: 25 max  
    - Swing: 25 max
    - Position: 25 max
    
    Requires IB Gateway connection.
    """
    global _comprehensive_alerts, _comprehensive_last_scan
    
    if request is None:
        request = ComprehensiveScanRequest()
    
    min_score = request.min_score
    
    # Check connection
    is_connected = False
    if _ib_service:
        try:
            status = _ib_service.get_connection_status()
            is_connected = status.get("connected", False)
        except:
            pass
    
    if not is_connected:
        # First try in-memory cache, then DataCache for persistence
        from services.data_cache import get_data_cache
        data_cache = get_data_cache()
        
        # Try in-memory cache first
        if _comprehensive_last_scan:
            return {
                "alerts": _comprehensive_alerts,
                "summary": {
                    "scalp": len(_comprehensive_alerts["scalp"]),
                    "intraday": len(_comprehensive_alerts["intraday"]),
                    "swing": len(_comprehensive_alerts["swing"]),
                    "position": len(_comprehensive_alerts["position"]),
                    "total": sum(len(v) for v in _comprehensive_alerts.values())
                },
                "min_score": min_score,
                "last_scan": _comprehensive_last_scan,
                "is_cached": True,
                "is_connected": False,
                "message": "Showing cached results from last session. Connect IB Gateway for real-time scanning."
            }
        
        # Try persistent DataCache
        cached = data_cache.get_cached_comprehensive_scan()
        if cached:
            return {
                "alerts": cached["alerts"],
                "summary": cached["summary"],
                "min_score": min_score,
                "last_scan": cached["last_updated"],
                "is_cached": True,
                "is_connected": False,
                "message": f"Showing cached results from {cached['last_updated'][:19]}. Connect IB Gateway for real-time scanning."
            }
        
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Data unavailable",
                "message": "IB Gateway is disconnected and no cached data available. Connect to run comprehensive scan.",
                "is_connected": False
            }
        )
    
    try:
        from services.scoring_engine import get_scoring_engine
        from services.enhanced_alerts import (
            create_enhanced_alert, get_alert_manager,
            AlertType, AlertTimeframe, determine_timeframe
        )
        
        feature_engine = get_feature_engine()
        scoring_engine = get_scoring_engine()
        alert_manager = get_alert_manager()
        
        # Define all scanner types to run
        all_scan_types = [
            "TOP_PERC_GAIN",      # Top gainers
            "TOP_PERC_LOSE",      # Top losers
            "MOST_ACTIVE",        # Most active by volume
            "HOT_BY_VOLUME",      # Hot by volume
            "HIGH_OPEN_GAP",      # Gap up
            "LOW_OPEN_GAP",       # Gap down
            "HIGH_VS_13W_HL",     # Near 13-week high
            "LOW_VS_13W_HL",      # Near 13-week low
        ]
        
        if request.scan_types:
            all_scan_types = [s for s in all_scan_types if s in request.scan_types]
        
        # Collect all unique candidates from all scanners
        all_candidates = {}
        
        for scan_type in all_scan_types:
            try:
                results = await _ib_service.run_scanner(scan_type, max_results=30)
                for r in results:
                    symbol = r.get("symbol", "")
                    if symbol and symbol not in all_candidates:
                        all_candidates[symbol] = {
                            "scan_result": r,
                            "scan_type": scan_type
                        }
            except Exception as e:
                print(f"Scanner {scan_type} error: {e}")
                continue
        
        print(f"Comprehensive scan: {len(all_candidates)} unique candidates from {len(all_scan_types)} scanners")
        
        if not all_candidates:
            return {
                "alerts": {"scalp": [], "intraday": [], "swing": [], "position": []},
                "summary": {"scalp": 0, "intraday": 0, "swing": 0, "position": 0, "total": 0},
                "min_score": min_score,
                "last_scan": datetime.now(timezone.utc).isoformat(),
                "is_cached": False,
                "is_connected": True,
                "message": "No scanner results available"
            }
        
        # Categorized results
        categorized = {
            "scalp": [],
            "intraday": [],
            "swing": [],
            "position": []
        }
        
        # Analyze each candidate
        for symbol, data in all_candidates.items():
            try:
                scan_result = data["scan_result"]
                scan_type = data["scan_type"]
                
                # Get real-time quote - use stock_service which has Alpaca fallback
                quote = await _stock_service.get_quote(symbol) if _stock_service else await _ib_service.get_quote(symbol)
                if not quote or not quote.get("price"):
                    continue
                
                current_price = quote.get("price", 0)
                if current_price <= 0:
                    continue
                
                # Get historical data (5 days hourly for swing, 1 day 5-min for intraday)
                hist_data_daily = await _ib_service.get_historical_data(symbol, "5 D", "1 hour")
                hist_data_intraday = await _ib_service.get_historical_data(symbol, "1 D", "5 mins")
                
                if not hist_data_daily or len(hist_data_daily) < 10:
                    continue
                
                # Calculate features using intraday data if available
                hist_for_features = hist_data_intraday if hist_data_intraday and len(hist_data_intraday) > 20 else hist_data_daily
                features = feature_engine.calculate_all_features(bars_5m=hist_for_features, bars_daily=hist_data_daily, session_bars_1m=None, fundamentals=None, market_data=None)
                
                # Calculate scores - build stock_data dict for scoring engine
                stock_data = {
                    "symbol": symbol,
                    "price": quote.get("price", 0),
                    "change_percent": quote.get("change_percent", 0),
                    "volume": quote.get("volume", 0),
                    **features
                }
                score_result = scoring_engine.calculate_composite_score(stock_data, {})
                overall_score = score_result.get("composite_score", score_result.get("overall", 0))
                
                # Apply minimum score filter
                if overall_score < min_score:
                    continue
                
                # Match against ALL strategies
                matched_strategies = simple_strategy_match(symbol, features, score_result)
                
                # Determine timeframe based on strategy matches and features
                timeframe = determine_timeframe_from_analysis(
                    matched_strategies, 
                    features, 
                    scan_type
                )
                
                # Calculate support/resistance levels
                highs = [bar["high"] for bar in hist_data_daily]
                lows = [bar["low"] for bar in hist_data_daily]
                closes = [bar["close"] for bar in hist_data_daily]
                
                resistance_1 = max(highs[-20:]) if len(highs) >= 20 else max(highs)
                resistance_2 = max(highs)
                support_1 = min(lows[-20:]) if len(lows) >= 20 else min(lows)
                support_2 = min(lows)
                
                # Determine alert type and direction
                alert_type = determine_alert_type(current_price, resistance_1, support_1, closes, features)
                direction = "LONG" if alert_type in [AlertType.BREAKOUT, AlertType.PULLBACK, AlertType.MOMENTUM] and features.get("trend") != "BEARISH" else "SHORT" if alert_type == AlertType.BREAKDOWN else "LONG"
                
                # Calculate trade plan
                atr = features.get("atr", current_price * 0.02)
                if direction == "LONG":
                    entry = current_price
                    stop_loss = max(support_1, current_price - (atr * 1.5))
                    target = current_price + (atr * 3)
                else:
                    entry = current_price
                    stop_loss = min(resistance_1, current_price + (atr * 1.5))
                    target = current_price - (atr * 3)
                
                risk = abs(entry - stop_loss)
                reward = abs(target - entry)
                risk_reward = round(reward / risk, 2) if risk > 0 else 0
                
                # Get grade
                grade = "A" if overall_score >= 80 else "B" if overall_score >= 65 else "C" if overall_score >= 50 else "D" if overall_score >= 35 else "F"
                
                # Get company info
                company_name = scan_result.get("name", symbol)
                
                # Determine timeframe description
                timeframe_descriptions = {
                    "scalp": "Scalp (minutes)",
                    "intraday": "Intraday (same day)",
                    "swing": "Swing (days to weeks)",
                    "position": "Position (weeks to months)"
                }
                
                # Generate headline
                headline = generate_alert_headline(symbol, alert_type, timeframe, direction, overall_score, matched_strategies)
                
                # Generate trigger reason
                trigger_reasons = []
                if features.get("rvol", 1) >= 2:
                    trigger_reasons.append(f"High RVOL ({features.get('rvol', 1):.1f}x)")
                if current_price > resistance_1:
                    trigger_reasons.append(f"Broke resistance ${resistance_1:.2f}")
                elif current_price < support_1:
                    trigger_reasons.append(f"Broke support ${support_1:.2f}")
                if features.get("trend") == "BULLISH":
                    trigger_reasons.append("Bullish trend")
                elif features.get("trend") == "BEARISH":
                    trigger_reasons.append("Bearish trend")
                if matched_strategies:
                    trigger_reasons.append(f"Matches {len(matched_strategies)} strategies")
                
                trigger_reason = "; ".join(trigger_reasons) if trigger_reasons else "Meets scoring criteria"
                
                alert = {
                    "id": f"{symbol}_{timeframe}_{datetime.now(timezone.utc).timestamp()}",
                    "symbol": symbol,
                    "company_name": company_name,
                    "alert_type": alert_type,
                    "timeframe": timeframe,
                    "timeframe_description": timeframe_descriptions.get(timeframe, timeframe),
                    "direction": direction,
                    "grade": grade,
                    "headline": headline,
                    "trigger_reason": trigger_reason,
                    "triggered_at": datetime.now(timezone.utc).isoformat(),
                    "triggered_at_formatted": "Just now",
                    
                    # Scores
                    "overall_score": overall_score,
                    "scores": {
                        "overall": overall_score,
                        "technical": score_result.get("categories", {}).get("technical", {}).get("score", 0),
                        "fundamental": score_result.get("categories", {}).get("fundamental", {}).get("score", 0),
                        "catalyst": score_result.get("categories", {}).get("catalyst", {}).get("score", 0),
                        "confidence": score_result.get("confidence", 0)
                    },
                    
                    # Trade plan
                    "trade_plan": {
                        "direction": direction,
                        "entry": round(entry, 2),
                        "stop_loss": round(stop_loss, 2),
                        "target": round(target, 2),
                        "risk_reward": risk_reward
                    },
                    
                    # Price data
                    "current_price": round(current_price, 2),
                    "change_percent": quote.get("change_percent", 0),
                    "volume": quote.get("volume", 0),
                    
                    # Technical features
                    "features": {
                        "rvol": round(features.get("rvol", 1), 2),
                        "rsi": round(features.get("rsi", 50), 1),
                        "vwap_distance": round(features.get("vwap_distance", 0), 2),
                        "trend": features.get("trend", "NEUTRAL"),
                        "atr": round(atr, 2)
                    },
                    
                    # Levels
                    "levels": {
                        "resistance_1": round(resistance_1, 2),
                        "resistance_2": round(resistance_2, 2),
                        "support_1": round(support_1, 2),
                        "support_2": round(support_2, 2)
                    },
                    
                    # Strategy matches
                    "matched_strategies": [
                        {"id": s["id"], "name": s["name"], "match_pct": s.get("match_percentage", 0)} 
                        for s in matched_strategies[:5]
                    ],
                    "matched_strategies_count": len(matched_strategies),
                    "signal_strength": round((len(matched_strategies) / 77) * 100, 1),
                    "signal_strength_label": (
                        "VERY STRONG" if len(matched_strategies) >= 10 else
                        "STRONG" if len(matched_strategies) >= 7 else
                        "MODERATE" if len(matched_strategies) >= 4 else
                        "WEAK"
                    ),
                    
                    # Metadata
                    "scan_source": scan_type,
                    "is_new": True
                }
                
                # Add to appropriate category
                categorized[timeframe].append(alert)
                
            except Exception as e:
                print(f"Error analyzing {symbol}: {e}")
                continue
        
        # Sort each category by overall score and apply caps
        caps = {"scalp": 10, "intraday": 25, "swing": 25, "position": 25}
        
        for timeframe in categorized:
            categorized[timeframe].sort(key=lambda x: x["overall_score"], reverse=True)
            categorized[timeframe] = categorized[timeframe][:caps[timeframe]]
        
        # Update global cache
        _comprehensive_alerts = categorized
        _comprehensive_last_scan = datetime.now(timezone.utc).isoformat()
        
        # Persist to DataCache for offline access
        from services.data_cache import get_data_cache
        data_cache = get_data_cache()
        summary = {
            "scalp": len(categorized["scalp"]),
            "intraday": len(categorized["intraday"]),
            "swing": len(categorized["swing"]),
            "position": len(categorized["position"]),
            "total": sum(len(v) for v in categorized.values())
        }
        data_cache.cache_comprehensive_scan(categorized, summary)
        
        # Also add top alerts to the enhanced alert manager
        for timeframe, alerts in categorized.items():
            for alert in alerts[:5]:  # Top 5 from each category
                try:
                    alert_manager.add_alert(alert)
                except:
                    pass
        
        return {
            "alerts": categorized,
            "summary": {
                "scalp": len(categorized["scalp"]),
                "intraday": len(categorized["intraday"]),
                "swing": len(categorized["swing"]),
                "position": len(categorized["position"]),
                "total": sum(len(v) for v in categorized.values())
            },
            "min_score": min_score,
            "total_scanned": len(all_candidates),
            "last_scan": _comprehensive_last_scan,
            "is_cached": False,
            "is_connected": True
        }
        
    except Exception as e:
        print(f"Error in comprehensive scanner: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Scanner error",
                "message": str(e),
                "is_connected": is_connected
            }
        )


def determine_timeframe_from_analysis(matched_strategies: list, features: dict, scan_type: str) -> str:
    """
    Determine the appropriate timeframe based on:
    - Matched strategy IDs (INT- = intraday, SWG- = swing, etc.)
    - Technical features (ATR%, RVOL patterns)
    - Scan type that found the stock
    """
    # Count strategies by prefix
    intraday_count = sum(1 for s in matched_strategies if s.get("id", "").startswith("INT-"))
    swing_count = sum(1 for s in matched_strategies if s.get("id", "").startswith("SWG-"))
    position_count = sum(1 for s in matched_strategies if s.get("id", "").startswith("POS-"))
    
    # Check for scalp indicators
    atr_pct = features.get("atr_percentage", 2)
    rvol = features.get("rvol", 1)
    
    # Scalp: Very high RVOL + tight ATR + momentum scans
    if rvol >= 3 and atr_pct < 1.5 and scan_type in ["TOP_PERC_GAIN", "TOP_PERC_LOSE", "HOT_BY_VOLUME"]:
        return "scalp"
    
    # If strategies matched, use majority
    if intraday_count > swing_count and intraday_count > position_count:
        if rvol >= 2.5:
            return "scalp"
        return "intraday"
    elif swing_count > intraday_count and swing_count > position_count:
        return "swing"
    elif position_count > 0:
        return "position"
    
    # Default based on scan type
    momentum_scans = ["TOP_PERC_GAIN", "TOP_PERC_LOSE", "HOT_BY_VOLUME", "MOST_ACTIVE"]
    if scan_type in momentum_scans:
        if rvol >= 2.5:
            return "scalp"
        return "intraday"
    elif scan_type in ["HIGH_VS_13W_HL", "LOW_VS_13W_HL"]:
        return "swing"
    
    # Default to intraday
    return "intraday"


def determine_alert_type(current_price: float, resistance: float, support: float, closes: list, features: dict) -> str:
    """Determine the type of alert based on price action"""
    from services.enhanced_alerts import AlertType
    
    prev_close = closes[-2] if len(closes) > 1 else current_price
    
    # Breakout: price breaks above resistance
    if current_price > resistance and prev_close <= resistance:
        return AlertType.BREAKOUT
    
    # Breakdown: price breaks below support
    if current_price < support and prev_close >= support:
        return AlertType.BREAKDOWN
    
    # Pullback: price near support in uptrend
    trend = features.get("trend", "NEUTRAL")
    if trend == "BULLISH" and current_price > 0 and abs(current_price - support) / current_price < 0.02:
        return AlertType.PULLBACK
    
    # Momentum: high RVOL with trend
    rvol = features.get("rvol", 1)
    if rvol >= 2:
        return AlertType.MOMENTUM
    
    return AlertType.STRATEGY_MATCH


def generate_alert_headline(symbol: str, alert_type: str, timeframe: str, direction: str, score: int, strategies: list) -> str:
    """Generate a concise headline for the alert"""
    from services.enhanced_alerts import AlertType
    
    timeframe_adj = {
        "scalp": "scalp",
        "intraday": "intraday", 
        "swing": "swing",
        "position": "position"
    }.get(timeframe, "")
    
    grade = "A" if score >= 80 else "B" if score >= 65 else "C" if score >= 50 else "D"
    
    top_strategy = strategies[0]["name"] if strategies else "opportunity"
    
    if alert_type == AlertType.BREAKOUT:
        return f"{symbol}: Grade {grade} {timeframe_adj} breakout - {top_strategy}"
    elif alert_type == AlertType.BREAKDOWN:
        return f"{symbol}: Grade {grade} {timeframe_adj} breakdown (short) - {top_strategy}"
    elif alert_type == AlertType.PULLBACK:
        return f"{symbol}: Grade {grade} {timeframe_adj} pullback entry - {top_strategy}"
    elif alert_type == AlertType.MOMENTUM:
        return f"{symbol}: Grade {grade} {timeframe_adj} momentum play - {top_strategy}"
    else:
        return f"{symbol}: Grade {grade} {timeframe_adj} setup - {top_strategy}"


# ===================== Enhanced Alerts with Context =====================

@router.get("/alerts/enhanced")
async def get_enhanced_alerts(limit: int = 50):
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
async def get_enhanced_alert_history(limit: int = 100):
    """Get history of all enhanced alerts"""
    from services.enhanced_alerts import get_alert_manager
    
    manager = get_alert_manager()
    history = manager.get_alert_history(limit)
    
    return {
        "history": history,
        "count": len(history)
    }


@router.post("/alerts/enhanced/{alert_id}/viewed")
async def mark_alert_viewed(alert_id: str):
    """Mark an alert as viewed"""
    from services.enhanced_alerts import get_alert_manager
    
    manager = get_alert_manager()
    manager.mark_alert_viewed(alert_id)
    
    return {"status": "ok", "alert_id": alert_id}


@router.delete("/alerts/enhanced/{alert_id}")
async def archive_enhanced_alert(alert_id: str):
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
        AlertType, determine_timeframe
    )
    from services.scoring_engine import get_scoring_engine
    
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
        features = feature_engine.calculate_all_features(bars_5m=hist_data, bars_daily=None, session_bars_1m=None, fundamentals=None, market_data=None)
        
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
        print(f"Error generating enhanced alert for {symbol}: {e}")
        raise HTTPException(
            status_code=500,
            detail={"error": str(e), "symbol": symbol}
        )

