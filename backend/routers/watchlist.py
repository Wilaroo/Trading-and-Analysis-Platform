"""
Watchlist Router - Standard and Smart Watchlist endpoints
Extracted from server.py for modularity
"""
from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone
import asyncio
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Watchlist"])

# Dependencies injected via init
_watchlists_col = None
_smart_watchlist = None
_fetch_multiple_quotes = None
_score_stock_for_strategies = None
_generate_ai_analysis = None


def init_watchlist_router(db, smart_watchlist, fetch_multiple_quotes, score_stock_for_strategies, generate_ai_analysis):
    global _watchlists_col, _smart_watchlist, _fetch_multiple_quotes, _score_stock_for_strategies, _generate_ai_analysis
    _watchlists_col = db["watchlists"]
    _smart_watchlist = smart_watchlist
    _fetch_multiple_quotes = fetch_multiple_quotes
    _score_stock_for_strategies = score_stock_for_strategies
    _generate_ai_analysis = generate_ai_analysis


# ===================== STANDARD WATCHLIST =====================

@router.get("/watchlist")
async def get_watchlist():
    """Get current watchlist"""
    watchlist = await asyncio.to_thread(lambda: list(_watchlists_col.find({}, {"_id": 0}).sort("score", -1).limit(10)))
    return {"watchlist": watchlist, "count": len(watchlist)}


@router.post("/watchlist/generate")
async def generate_morning_watchlist():
    """Generate AI-powered morning watchlist"""
    symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "AMD", "NFLX", "CRM", 
               "SPY", "QQQ", "BA", "DIS", "V", "MA", "JPM", "GS", "XOM", "CVX"]
    
    quotes = await _fetch_multiple_quotes(symbols)
    
    scored_stocks = []
    for quote in quotes:
        score_data = await _score_stock_for_strategies(quote["symbol"], quote)
        scored_stocks.append({
            **score_data,
            "price": quote["price"],
            "change_percent": quote["change_percent"]
        })
    
    scored_stocks.sort(key=lambda x: x["score"], reverse=True)
    top_10 = scored_stocks[:10]
    
    def _sync_save_watchlist():
        _watchlists_col.delete_many({})
        for item in top_10:
            item["created_at"] = datetime.now(timezone.utc).isoformat()
            doc = item.copy()
            _watchlists_col.insert_one(doc)
    await asyncio.to_thread(_sync_save_watchlist)
    
    symbols_str = ", ".join([s["symbol"] for s in top_10[:5]])
    ai_insight = await _generate_ai_analysis(
        f"Provide a brief 2-3 sentence trading insight for today's top watchlist: {symbols_str}. "
        f"Top mover: {top_10[0]['symbol']} with score {top_10[0]['score']}."
    )
    
    clean_watchlist = []
    for item in top_10:
        clean_item = {k: v for k, v in item.items() if k != '_id'}
        clean_watchlist.append(clean_item)
    
    return {
        "watchlist": clean_watchlist,
        "ai_insight": ai_insight,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }


@router.post("/watchlist/add")
async def add_to_watchlist(data: dict):
    """Add a symbol to watchlist manually"""
    symbol = data.get("symbol", "").upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol is required")
    
    existing = await asyncio.to_thread(_watchlists_col.find_one, {"symbol": symbol})
    if existing:
        return {"message": f"{symbol} already in watchlist", "symbol": symbol}
    
    doc = {
        "symbol": symbol,
        "score": 50,
        "matched_strategies": [],
        "added_at": datetime.now(timezone.utc).isoformat(),
        "manual": True
    }
    
    await asyncio.to_thread(_watchlists_col.insert_one, doc)
    return {"message": f"{symbol} added to watchlist", "symbol": symbol}


@router.delete("/watchlist/{symbol}")
async def remove_from_watchlist(symbol: str):
    """Remove a symbol from watchlist"""
    result = await asyncio.to_thread(_watchlists_col.delete_one, {"symbol": symbol.upper()})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail=f"{symbol} not found in watchlist")
    return {"message": f"{symbol} removed from watchlist", "symbol": symbol.upper()}


# ===================== SMART WATCHLIST =====================

@router.get("/smart-watchlist")
def get_smart_watchlist_api():
    """Get the smart watchlist (hybrid auto + manual)"""
    return _smart_watchlist.to_api_response()


@router.post("/smart-watchlist/add")
def add_to_smart_watchlist(data: dict):
    """Manually add a symbol to smart watchlist"""
    symbol = data.get("symbol", "").upper()
    notes = data.get("notes", "")
    
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol is required")
    
    result = _smart_watchlist.add_manual(symbol, notes)
    return result


@router.delete("/smart-watchlist/{symbol}")
def remove_from_smart_watchlist(symbol: str):
    """Manually remove a symbol from smart watchlist"""
    result = _smart_watchlist.remove_manual(symbol.upper())
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


@router.get("/smart-watchlist/stats")
def get_smart_watchlist_stats():
    """Get smart watchlist statistics"""
    return _smart_watchlist.get_stats()
