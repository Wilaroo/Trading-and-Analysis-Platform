"""
Market Data Router - Quotes, fundamentals, VST, insider, COT, news endpoints
Extracted from server.py for modularity
"""
from fastapi import APIRouter, HTTPException
from typing import List
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Market Data"])

# Dependencies injected via init
_get_stock_service = None
_fetch_quote = None
_fetch_multiple_quotes = None
_fetch_fundamentals = None
_get_full_vst_analysis = None
_fetch_historical_data = None
_fetch_insider_trades = None
_get_unusual_insider_activity = None
_fetch_cot_data = None
_get_cot_summary = None
_fetch_market_news = None


def init_market_data_router(
    get_stock_service,
    fetch_quote,
    fetch_multiple_quotes,
    fetch_fundamentals,
    get_full_vst_analysis,
    fetch_historical_data,
    fetch_insider_trades,
    get_unusual_insider_activity,
    fetch_cot_data,
    get_cot_summary,
    fetch_market_news
):
    global _get_stock_service, _fetch_quote, _fetch_multiple_quotes, _fetch_fundamentals
    global _get_full_vst_analysis, _fetch_historical_data, _fetch_insider_trades
    global _get_unusual_insider_activity, _fetch_cot_data, _get_cot_summary, _fetch_market_news
    _get_stock_service = get_stock_service
    _fetch_quote = fetch_quote
    _fetch_multiple_quotes = fetch_multiple_quotes
    _fetch_fundamentals = fetch_fundamentals
    _get_full_vst_analysis = get_full_vst_analysis
    _fetch_historical_data = fetch_historical_data
    _fetch_insider_trades = fetch_insider_trades
    _get_unusual_insider_activity = get_unusual_insider_activity
    _fetch_cot_data = fetch_cot_data
    _get_cot_summary = get_cot_summary
    _fetch_market_news = fetch_market_news


# ===================== DATA SERVICES =====================

@router.get("/data-services/status")
async def get_data_services_status():
    """Get detailed status of all market data services (Alpaca, Finnhub, yfinance, etc.)"""
    stock_svc = _get_stock_service()
    return await stock_svc.get_service_status()


@router.get("/data-services/health")
async def check_data_services_health():
    """Perform health check on all data services - tests actual connectivity"""
    stock_svc = _get_stock_service()
    return await stock_svc.health_check()


# ===================== QUOTES =====================

@router.get("/quotes/{symbol}")
async def get_quote(symbol: str):
    """Get real-time quote for a single symbol"""
    quote = await _fetch_quote(symbol.upper())
    if not quote:
        raise HTTPException(status_code=404, detail="Symbol not found")
    return quote


@router.post("/quotes/batch")
async def get_batch_quotes(symbols: List[str]):
    """Get quotes for multiple symbols"""
    quotes = await _fetch_multiple_quotes([s.upper() for s in symbols])
    return {"quotes": quotes, "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/market/overview")
async def get_market_overview():
    """Get market overview with major indices and movers"""
    indices = ["SPY", "QQQ", "DIA", "IWM", "VIX"]
    movers = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "AMD"]
    
    index_quotes = await _fetch_multiple_quotes(indices)
    mover_quotes = await _fetch_multiple_quotes(movers)
    
    sorted_movers = sorted(mover_quotes, key=lambda x: abs(x.get("change_percent", 0)), reverse=True)
    
    return {
        "indices": index_quotes,
        "top_movers": sorted_movers[:5],
        "gainers": [m for m in sorted_movers if m.get("change_percent", 0) > 0][:3],
        "losers": [m for m in sorted_movers if m.get("change_percent", 0) < 0][:3],
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# ===================== FUNDAMENTALS =====================

@router.get("/fundamentals/{symbol}")
async def get_fundamentals(symbol: str):
    """Get fundamental data for a symbol"""
    data = await _fetch_fundamentals(symbol.upper())
    return data


@router.get("/vst/{symbol}")
async def get_vst_scores(symbol: str):
    """Get VST (Value, Safety, Timing) scores for a symbol"""
    analysis = await _get_full_vst_analysis(symbol.upper())
    return analysis


@router.post("/vst/batch")
async def get_vst_batch(symbols: List[str]):
    """Get VST scores for multiple symbols"""
    results = []
    for symbol in symbols[:20]:
        try:
            analysis = await _get_full_vst_analysis(symbol.upper())
            results.append(analysis)
        except Exception as e:
            logger.warning(f"VST error for {symbol}: {e}")
            results.append({"symbol": symbol.upper(), "error": str(e)})
    return {"results": results, "count": len(results)}


@router.get("/historical/{symbol}")
async def get_historical(symbol: str, period: str = "1y"):
    """Get historical price data"""
    data = await _fetch_historical_data(symbol.upper(), period)
    return {"symbol": symbol.upper(), "data": data, "period": period}


# ===================== INSIDER TRADING =====================
# NOTE: /insider/unusual must be defined BEFORE /insider/{symbol} to avoid route conflict

@router.get("/insider/unusual")
async def get_unusual_insider():
    """Get stocks with unusual insider activity"""
    activity = await _get_unusual_insider_activity()
    unusual = [a for a in activity if a.get("is_unusual", False)]
    return {
        "unusual_activity": unusual,
        "all_activity": activity,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/insider/{symbol}")
async def get_insider_trades(symbol: str):
    """Get insider trading data for a symbol"""
    trades = await _fetch_insider_trades(symbol.upper())
    
    total_buys = sum(t["value"] for t in trades if t["transaction_type"] == "Buy")
    total_sells = sum(t["value"] for t in trades if t["transaction_type"] == "Sell")
    
    return {
        "symbol": symbol.upper(),
        "trades": trades,
        "summary": {
            "total_buys": round(total_buys, 2),
            "total_sells": round(total_sells, 2),
            "net_activity": round(total_buys - total_sells, 2),
            "buy_count": len([t for t in trades if t["transaction_type"] == "Buy"]),
            "sell_count": len([t for t in trades if t["transaction_type"] == "Sell"]),
            "signal": "BULLISH" if total_buys > total_sells else "BEARISH"
        },
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# ===================== COT DATA =====================

@router.get("/cot/summary")
async def get_cot_summary_endpoint():
    """Get COT summary for major markets"""
    summary = await _get_cot_summary()
    return summary


@router.get("/cot/{market}")
async def get_cot(market: str):
    """Get COT data for a specific market"""
    data = await _fetch_cot_data(market.upper())
    return {
        "market": market.upper(),
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# ===================== NEWS =====================

@router.get("/news")
async def get_news(limit: int = 10):
    """Get latest market news"""
    news = await _fetch_market_news()
    return {"news": news[:limit], "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/news/{symbol}")
async def get_symbol_news(symbol: str):
    """Get news for specific symbol"""
    all_news = await _fetch_market_news()
    symbol_news = [n for n in all_news if symbol.upper() in n.get("related_symbols", [])]
    return {"news": symbol_news, "symbol": symbol.upper()}
