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

