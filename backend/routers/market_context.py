"""
Market Context Router - API endpoints for market context analysis
"""
from fastapi import APIRouter, HTTPException
from typing import List
from pydantic import BaseModel

router = APIRouter(prefix="/api/market-context", tags=["market-context"])

# Will be initialized from main server
market_context_service = None

def init_market_context_service(service):
    global market_context_service
    market_context_service = service


class SymbolsRequest(BaseModel):
    symbols: List[str]


@router.get("/{symbol}")
async def get_market_context(symbol: str):
    """
    Get market context analysis for a single symbol
    Returns: TRENDING, CONSOLIDATION, or MEAN_REVERSION with metrics
    """
    if not market_context_service:
        raise HTTPException(500, "Market context service not initialized")
    
    result = await market_context_service.analyze_symbol(symbol)
    return result


@router.post("/batch")
async def get_batch_market_context(request: SymbolsRequest):
    """
    Get market context analysis for multiple symbols
    """
    if not market_context_service:
        raise HTTPException(500, "Market context service not initialized")
    
    if len(request.symbols) > 50:
        raise HTTPException(400, "Maximum 50 symbols per batch")
    
    results = await market_context_service.analyze_batch(request.symbols)
    summary = market_context_service.get_context_summary(results)
    
    return {
        "results": results,
        "summary": summary
    }


@router.get("")
async def get_market_overview():
    """
    Get overall market context/overview for SPY, QQQ, VIX
    """
    if not market_context_service:
        raise HTTPException(500, "Market context service not initialized")
    
    try:
        # Analyze key market indicators
        results = await market_context_service.analyze_batch(["SPY", "QQQ"])
        summary = market_context_service.get_context_summary(results)
        
        # results is a dict like {"SPY": {...}, "QQQ": {...}}
        spy_data = results.get("SPY", {})
        qqq_data = results.get("QQQ", {})
        
        # Determine overall market regime
        spy_context = spy_data.get("market_context", "UNKNOWN")
        qqq_context = qqq_data.get("market_context", "UNKNOWN")
        
        if spy_context == qqq_context:
            regime = spy_context.replace("_", " ").title()
        elif "TRENDING" in spy_context or "TRENDING" in qqq_context:
            regime = "Trending"
        elif "CONSOLIDATION" in spy_context or "CONSOLIDATION" in qqq_context:
            regime = "Range"
        else:
            regime = "Mixed"
        
        return {
            "regime": regime,
            "spy": {
                "symbol": "SPY",
                "price": spy_data.get("price", 0),
                "change_percent": spy_data.get("change_percent", 0),
                "context": spy_context,
                "rvol": spy_data.get("rvol", 0)
            },
            "qqq": {
                "symbol": "QQQ",
                "price": qqq_data.get("price", 0),
                "change_percent": qqq_data.get("change_percent", 0),
                "context": qqq_context,
                "rvol": qqq_data.get("rvol", 0)
            },
            "vix": {
                "price": summary.get("market_breadth", {}).get("vix", 0) if isinstance(summary, dict) else 0
            },
            "summary": summary
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        # Return default values on error
        return {
            "regime": "Unknown",
            "spy": {"symbol": "SPY", "price": 0, "change_percent": 0},
            "qqq": {"symbol": "QQQ", "price": 0, "change_percent": 0},
            "vix": {"price": 0},
            "error": str(e)
        }


@router.get("/watchlist/analysis")
async def get_watchlist_context(db=None):
    """
    Get market context analysis for all watchlist symbols
    """
    if not market_context_service:
        raise HTTPException(500, "Market context service not initialized")
    
    # This will be injected with actual watchlist data
    # For now, use common symbols
    from pymongo import MongoClient
    import os
    
    try:
        mongo_client = MongoClient(os.environ.get("MONGO_URL"))
        db = mongo_client[os.environ.get("DB_NAME", "tradecommand")]
        watchlist = list(db["watchlists"].find({}, {"_id": 0, "symbol": 1}))
        symbols = [w["symbol"] for w in watchlist]
        
        if not symbols:
            symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "META", "NVDA", "AMD"]
    except Exception as e:
        symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "META", "NVDA", "AMD"]
    
    results = await market_context_service.analyze_batch(symbols)
    summary = market_context_service.get_context_summary(results)
    
    return {
        "results": results,
        "summary": summary,
        "symbols_analyzed": symbols
    }


@router.get("/strategies/{context}")
async def get_strategies_for_context(context: str):
    """
    Get recommended strategies for a specific market context
    """
    context = context.upper()
    
    strategies = {
        "TRENDING": {
            "description": "Clear directional movement with high volume",
            "identification": [
                "High Relative Volume (RVOL ≥ 1.5)",
                "Clear price direction (bullish or bearish)",
                "Rising ATR (increasing volatility)"
            ],
            "trade_styles": [
                {
                    "name": "Breakout Confirmation",
                    "strategies": ["INT-02", "INT-03", "INT-15"],
                    "description": "Enter after price confirms breakout of key level"
                },
                {
                    "name": "Pullback Continuation",
                    "strategies": ["INT-01", "INT-05", "INT-06"],
                    "description": "Enter on pullbacks in established trend"
                },
                {
                    "name": "Momentum Trading",
                    "strategies": ["INT-04", "INT-14", "INT-16"],
                    "description": "Ride momentum moves with news/volume"
                }
            ],
            "sub_types": {
                "AGGRESSIVE": "High volatility with large candlesticks and high volume",
                "PASSIVE": "Low volatility with gradual, controlled movement"
            }
        },
        "CONSOLIDATION": {
            "description": "Prices move within defined range, often after large moves",
            "identification": [
                "Low volume (RVOL < 1.0)",
                "Declining ATR",
                "Clear support and resistance levels",
                "False breakouts common"
            ],
            "trade_styles": [
                {
                    "name": "Range Trading",
                    "strategies": ["INT-13", "INT-12"],
                    "description": "Buy support, sell resistance within range"
                },
                {
                    "name": "Scalping",
                    "strategies": ["INT-09"],
                    "description": "Small profits on micro-moves"
                },
                {
                    "name": "Rubber Band Setup",
                    "strategies": ["INT-17"],
                    "description": "Wait for range break with confirmation"
                }
            ]
        },
        "MEAN_REVERSION": {
            "description": "Price overextended and returning to balance point",
            "identification": [
                "Large gap into/above resistance or support",
                "Price >2 standard deviations from mean",
                "Exhaustion candles with high volume"
            ],
            "trade_styles": [
                {
                    "name": "VWAP Reversion",
                    "strategies": ["INT-07", "INT-06"],
                    "description": "Fade extended moves back to VWAP"
                },
                {
                    "name": "Exhaustion Reversal",
                    "strategies": ["INT-08", "INT-11"],
                    "description": "Catch reversals at exhaustion points"
                },
                {
                    "name": "Key Level Reversal",
                    "strategies": ["INT-11", "INT-12"],
                    "description": "Reversal trades at major S/R levels"
                }
            ],
            "sub_types": {
                "AGGRESSIVE": "High volatility with sharp, rapid price deviations",
                "PASSIVE": "Slow, gradual price deviations and returns"
            }
        }
    }
    
    if context not in strategies:
        raise HTTPException(400, f"Invalid context. Use: TRENDING, CONSOLIDATION, MEAN_REVERSION")
    
    return strategies[context]


@router.get("/recommendations/{symbol}")
async def get_smart_recommendations(symbol: str, include_secondary: bool = True, max_risk: str = "High"):
    """
    Get smart strategy recommendations for a symbol based on its market context
    """
    if not market_context_service:
        raise HTTPException(500, "Market context service not initialized")
    
    from services.strategy_recommendations import get_strategy_recommendation_service
    
    # Get market context
    context_data = await market_context_service.analyze_symbol(symbol)
    market_context = context_data.get("market_context", "")
    sub_type = context_data.get("sub_type")
    
    if not market_context:
        raise HTTPException(400, "Could not determine market context for symbol")
    
    # Get recommendations
    strategy_service = get_strategy_recommendation_service()
    recommendations = strategy_service.get_recommended_strategies(
        market_context, 
        sub_type, 
        include_secondary, 
        max_risk
    )
    
    return {
        "symbol": symbol,
        "market_context": market_context,
        "sub_type": sub_type,
        "confidence": context_data.get("confidence", 0),
        "metrics": context_data.get("metrics", {}),
        "recommendations": recommendations,
        "summary": f"For {symbol} in {market_context} market, focus on {', '.join(recommendations['trade_styles'][:2])}"
    }


@router.get("/matrix")
async def get_context_strategy_matrix():
    """
    Get a matrix showing which strategies work best for each market context
    """
    from services.strategy_recommendations import get_strategy_recommendation_service
    
    strategy_service = get_strategy_recommendation_service()
    matrix = strategy_service.get_context_strategy_matrix()
    
    return {
        "matrix": matrix,
        "description": "Shows recommended strategy counts and top strategies for each market context"
    }



# ==================== ADVANCED MARKET INDICATORS ====================

# Market indicators service instance
_market_indicators_service = None

def init_market_indicators_service(alpaca_service=None, ib_service=None):
    """Initialize the market indicators service"""
    global _market_indicators_service
    from services.market_indicators import get_market_indicators_service
    _market_indicators_service = get_market_indicators_service(alpaca_service, ib_service)
    return _market_indicators_service


@router.get("/indicators/vold")
async def get_vold_ratio():
    """
    Get VOLD (Volume Advance/Decline) Ratio for trend day detection.
    
    VOLD measures whether market volume is skewed toward advancing or declining stocks.
    - VOLD >= 2.618: Strong trend day (bullish)
    - VOLD <= -2.618: Strong trend day (bearish)
    - Between: Range/chop day
    
    Use this to determine if momentum strategies or mean reversion strategies are favored.
    """
    global _market_indicators_service
    
    if not _market_indicators_service:
        from services.market_indicators import get_market_indicators_service
        _market_indicators_service = get_market_indicators_service()
    
    try:
        vold_data = await _market_indicators_service.calculate_vold_ratio()
        return vold_data
    except Exception as e:
        return {
            "error": str(e),
            "overall": {"is_trend_day": False, "market_bias": "NEUTRAL"}
        }


@router.get("/indicators/regime")
async def get_market_regime():
    """
    Get full market regime classification.
    
    Classifies market into one of 4 regimes:
    - AGGRESSIVE_TRENDING: High strength + high momentum
    - PASSIVE_TRENDING: High strength + low momentum
    - VOLATILE_RANGE: Low strength + high volatility
    - QUIET_CONSOLIDATION: Low strength + low volatility
    
    Returns favored setups, avoid setups, and position sizing guidance.
    """
    global _market_indicators_service
    
    if not _market_indicators_service:
        from services.market_indicators import get_market_indicators_service
        _market_indicators_service = get_market_indicators_service()
    
    try:
        analysis = await _market_indicators_service.get_full_market_analysis()
        return analysis
    except Exception as e:
        return {
            "error": str(e),
            "regime": {"regime": "UNKNOWN"},
            "trading_guidance": {"is_trend_day": False}
        }


@router.get("/indicators/extension/{symbol}")
async def get_stock_extension(symbol: str):
    """
    Get 5 ATR over-extension analysis for a specific stock.
    
    Calculates bands from 5-day high/low extended by 5 ATRs.
    - Price above high_band: Over-extended to upside (caution on longs)
    - Price below low_band: Over-extended to downside (caution on shorts)
    
    Also includes volume threshold analysis.
    """
    global _market_indicators_service
    
    if not _market_indicators_service:
        from services.market_indicators import get_market_indicators_service
        _market_indicators_service = get_market_indicators_service()
    
    try:
        # Get daily bars for the symbol
        from services.stock_data import get_stock_data_service
        stock_service = get_stock_data_service()
        
        daily_bars = await stock_service.get_historical_bars(symbol.upper(), "1D", 50)
        
        if not daily_bars:
            return {"error": f"No data available for {symbol}"}
        
        # Convert to expected format
        bars = [
            {
                "open": bar.get("open", bar.get("o", 0)),
                "high": bar.get("high", bar.get("h", 0)),
                "low": bar.get("low", bar.get("l", 0)),
                "close": bar.get("close", bar.get("c", 0)),
                "volume": bar.get("volume", bar.get("v", 0))
            }
            for bar in daily_bars
        ]
        
        result = _market_indicators_service.analyze_stock_extension(
            symbol.upper(), bars
        )
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e), "symbol": symbol}


@router.get("/indicators/volume-threshold/{symbol}")
async def get_volume_threshold(symbol: str):
    """
    Get volume threshold analysis for a specific stock.
    
    Uses standard deviation to determine if current volume is significant.
    - SIGNIFICANT: Volume >= Average + 2*StdDev
    - LOW: Volume < Average
    - NORMAL: Volume between average and threshold
    
    This helps identify potential catalyst or institutional activity.
    """
    global _market_indicators_service
    
    if not _market_indicators_service:
        from services.market_indicators import get_market_indicators_service
        _market_indicators_service = get_market_indicators_service()
    
    try:
        from services.stock_data import get_stock_data_service
        stock_service = get_stock_data_service()
        
        # Get intraday bars for volume analysis
        intraday_bars = await stock_service.get_historical_bars(symbol.upper(), "5Min", 100)
        
        if not intraday_bars:
            return {"error": f"No data available for {symbol}"}
        
        volume_history = [bar.get("volume", bar.get("v", 0)) for bar in intraday_bars]
        current_volume = volume_history[-1] if volume_history else 0
        
        result = _market_indicators_service.calculate_volume_threshold(
            volume_history[:-1], current_volume
        )
        result["symbol"] = symbol.upper()
        return result
    except Exception as e:
        return {"error": str(e), "symbol": symbol}

