"""
Portfolio Router - Position management endpoints
Extracted from server.py for modularity
"""
from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone
import asyncio
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Portfolio"])

# Dependencies injected via init
_portfolios_col = None
_fetch_multiple_quotes = None


def init_portfolio_router(db, fetch_multiple_quotes):
    global _portfolios_col, _fetch_multiple_quotes
    _portfolios_col = db["portfolios"]
    _fetch_multiple_quotes = fetch_multiple_quotes


@router.get("/portfolio")
async def get_portfolio(source: str = "auto"):
    """Get portfolio positions. source: 'ib', 'manual', or 'auto' (tries IB first)"""
    # Try IB pushed data first
    if source in ["auto", "ib"]:
        try:
            from routers.ib import get_pushed_positions, is_pusher_connected, get_pushed_quotes
            
            if is_pusher_connected():
                ib_positions = get_pushed_positions()
                if ib_positions:
                    positions = []
                    total_value = 0
                    total_cost = 0
                    quotes = get_pushed_quotes()
                    
                    for pos in ib_positions:
                        symbol = pos.get("symbol", "")
                        shares = pos.get("position", 0) or pos.get("qty", 0)
                        avg_cost = pos.get("avg_cost", 0) or pos.get("avgCost", 0)
                        
                        current_price = pos.get("market_price", 0) or pos.get("marketPrice", 0)
                        if not current_price and symbol in quotes:
                            q = quotes[symbol]
                            current_price = q.get("last") or q.get("close") or avg_cost
                        
                        market_value = shares * current_price if current_price else 0
                        cost_basis = shares * avg_cost if avg_cost else 0
                        gain_loss = market_value - cost_basis
                        gain_loss_pct = (gain_loss / cost_basis * 100) if cost_basis else 0
                        
                        unrealized_pnl = pos.get("unrealized_pnl", 0) or pos.get("unrealizedPNL", 0)
                        if unrealized_pnl == 0 and gain_loss != 0:
                            unrealized_pnl = gain_loss
                        
                        positions.append({
                            "symbol": symbol,
                            "shares": shares,
                            "avg_cost": round(avg_cost, 4),
                            "current_price": round(current_price, 2),
                            "market_value": round(market_value, 2),
                            "gain_loss": round(gain_loss, 2),
                            "gain_loss_percent": round(gain_loss_pct, 2),
                            "unrealized_pnl": round(unrealized_pnl, 2),
                            "realized_pnl": round(pos.get("realized_pnl", 0) or pos.get("realizedPNL", 0), 2),
                            "source": "ib_gateway"
                        })
                        
                        total_value += market_value
                        total_cost += cost_basis
                    
                    total_gain = total_value - total_cost
                    total_gain_pct = (total_gain / total_cost * 100) if total_cost else 0
                    
                    return {
                        "positions": positions,
                        "summary": {
                            "total_value": round(total_value, 2),
                            "total_cost": round(total_cost, 2),
                            "total_gain_loss": round(total_gain, 2),
                            "total_gain_loss_percent": round(total_gain_pct, 2)
                        },
                        "source": "ib_gateway",
                        "account": "DUN615665"
                    }
        except Exception as e:
            logger.debug(f"IB portfolio fetch failed, falling back to manual: {e}")
    
    # Fallback to manual MongoDB positions
    positions = await asyncio.to_thread(lambda: list(_portfolios_col.find({}, {"_id": 0})))
    
    if positions:
        symbols = [p["symbol"] for p in positions]
        quotes = await _fetch_multiple_quotes(symbols)
        quote_map = {q["symbol"]: q for q in quotes}
        
        total_value = 0
        total_cost = 0
        
        for pos in positions:
            quote = quote_map.get(pos["symbol"], {})
            current_price = quote.get("price", pos.get("avg_cost", 0))
            shares = pos.get("shares", 0)
            avg_cost = pos.get("avg_cost", 0)
            
            market_value = shares * current_price
            cost_basis = shares * avg_cost
            gain_loss = market_value - cost_basis
            gain_loss_pct = (gain_loss / cost_basis * 100) if cost_basis else 0
            
            pos["current_price"] = current_price
            pos["market_value"] = round(market_value, 2)
            pos["gain_loss"] = round(gain_loss, 2)
            pos["gain_loss_percent"] = round(gain_loss_pct, 2)
            pos["change_today"] = quote.get("change_percent", 0)
            
            total_value += market_value
            total_cost += cost_basis
        
        total_gain = total_value - total_cost
        total_gain_pct = (total_gain / total_cost * 100) if total_cost else 0
        
        return {
            "positions": positions,
            "summary": {
                "total_value": round(total_value, 2),
                "total_cost": round(total_cost, 2),
                "total_gain_loss": round(total_gain, 2),
                "total_gain_loss_percent": round(total_gain_pct, 2)
            },
            "source": "manual"
        }
    
    return {"positions": [], "summary": {"total_value": 0, "total_cost": 0, "total_gain_loss": 0, "total_gain_loss_percent": 0}, "source": "none"}


@router.post("/portfolio/add")
async def add_position(data: dict):
    """Add position to portfolio"""
    symbol = data.get("symbol", "").upper()
    shares = data.get("shares")
    avg_cost = data.get("avg_cost")
    
    if not symbol or shares is None or avg_cost is None:
        raise HTTPException(status_code=400, detail="symbol, shares, and avg_cost are required")
    
    position = {
        "symbol": symbol,
        "shares": float(shares),
        "avg_cost": float(avg_cost),
        "added_at": datetime.now(timezone.utc).isoformat()
    }
    
    await asyncio.to_thread(
        _portfolios_col.update_one,
        {"symbol": symbol},
        {"$set": position},
        True  # upsert
    )
    
    return {"message": "Position added", "position": position}


@router.delete("/portfolio/{symbol}")
async def remove_position(symbol: str):
    """Remove position from portfolio"""
    result = await asyncio.to_thread(_portfolios_col.delete_one, {"symbol": symbol.upper()})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Position not found")
    return {"message": "Position removed"}
