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
                        # Skip fully-closed positions (IB keeps zero-qty rows briefly post-flatten)
                        if not shares:
                            continue
                        avg_cost = pos.get("avg_cost", 0) or pos.get("avgCost", 0)
                        
                        current_price = pos.get("market_price", 0) or pos.get("marketPrice", 0)
                        if not current_price and symbol in quotes:
                            q = quotes[symbol]
                            current_price = q.get("last") or q.get("close") or 0
                        
                        # Prefer IB's authoritative unrealized PnL; only fall back to computed
                        # values when we actually have a live quote. This prevents the
                        # "gain_loss = 0 - cost_basis = -$1.2M" display bug that fires
                        # during the brief window after restart when marketPrice is still 0.
                        unrealized_pnl = pos.get("unrealized_pnl", 0) or pos.get("unrealizedPNL", 0)
                        quote_ready = bool(current_price)
                        
                        if quote_ready:
                            market_value = shares * current_price
                            cost_basis = shares * avg_cost if avg_cost else 0
                            gain_loss = market_value - cost_basis
                            gain_loss_pct = (gain_loss / cost_basis * 100) if cost_basis else 0
                            if unrealized_pnl == 0 and gain_loss != 0:
                                unrealized_pnl = gain_loss
                        else:
                            # Quote not yet populated. Use IB's marketValue if present,
                            # otherwise show cost basis to avoid spurious negative PnL.
                            cost_basis = shares * avg_cost if avg_cost else 0
                            market_value = pos.get("market_value", 0) or pos.get("marketValue", 0) or cost_basis
                            gain_loss = unrealized_pnl  # trust IB's number (may be 0)
                            gain_loss_pct = (gain_loss / cost_basis * 100) if cost_basis else 0
                            current_price = avg_cost  # display placeholder
                        
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
                            "quote_ready": quote_ready,
                            "source": "ib_gateway"
                        })
                        
                        total_value += market_value
                        total_cost += cost_basis
                    
                    total_gain = total_value - total_cost
                    total_gain_pct = (total_gain / total_cost * 100) if total_cost else 0
                    quotes_ready = all(p["quote_ready"] for p in positions) if positions else True
                    
                    return {
                        "positions": positions,
                        "summary": {
                            "total_value": round(total_value, 2),
                            "total_cost": round(total_cost, 2),
                            "total_gain_loss": round(total_gain, 2),
                            "total_gain_loss_percent": round(total_gain_pct, 2),
                            "quotes_ready": quotes_ready
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


_last_flatten_ts = {"ts": 0}
_FLATTEN_COOLDOWN_SEC = 120  # Prevents accidental double-flatten that causes sign-flip shorts


@router.post("/portfolio/flatten-paper")
async def flatten_paper_positions(confirm: str = ""):
    """
    Close every open IB paper-account position by queueing market orders.
    Guard rails:
      1. requires confirm='FLATTEN' to fire
      2. only paper accounts (IB paper account codes start with 'D')
      3. 120s cooldown — blocks a second flatten while the first is still filling
         (prevents the sign-flip/short bug where a second pass sold again past zero)
      4. pre-flight cancel of any duplicate open flatten orders for the same symbol
    """
    import time
    if confirm != "FLATTEN":
        raise HTTPException(status_code=400, detail="Pass confirm=FLATTEN to execute")
    
    now = time.time()
    elapsed = now - _last_flatten_ts["ts"]
    if elapsed < _FLATTEN_COOLDOWN_SEC:
        raise HTTPException(
            status_code=429,
            detail=f"Cooldown active — wait {int(_FLATTEN_COOLDOWN_SEC - elapsed)}s before re-flattening"
        )
    
    try:
        from routers.ib import get_pushed_positions, queue_order, is_pusher_connected
        from services.order_queue_service import get_order_queue_service
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"IB router unavailable: {e}")
    
    if not is_pusher_connected():
        raise HTTPException(status_code=503, detail="IB pusher not connected; cannot flatten")
    
    positions = get_pushed_positions()
    if not positions:
        return {"success": True, "message": "No open positions to flatten", "orders": []}
    
    # Paper-account safety: IB paper account codes start with 'D' (e.g. DUN615665).
    paper_accounts = {p.get("account", "") for p in positions if p.get("account")}
    non_paper = [a for a in paper_accounts if a and not a.startswith("D")]
    if non_paper:
        raise HTTPException(
            status_code=403,
            detail=f"Refusing to flatten — non-paper accounts detected: {non_paper}"
        )
    
    # Pre-flight: cancel any pending/claimed flatten_* orders already in the queue.
    # This is what triggered the double-execution last time — leftover orders from a
    # previous flatten were re-polled by the pusher after the main backend restarted.
    cancelled_stale = 0
    try:
        svc = get_order_queue_service()
        col = svc._collection  # noqa: SLF001 - intentional internal access
        result = col.update_many(
            {
                "status": {"$in": ["pending", "claimed"]},
                "trade_id": {"$regex": "^flatten_"},
            },
            {"$set": {"status": "cancelled", "error": "Superseded by new flatten call"}},
        )
        cancelled_stale = result.modified_count
    except Exception as e:
        logger.warning(f"Pre-flight stale-order cleanup failed: {e}")
    
    queued = []
    errors = []
    for pos in positions:
        symbol = pos.get("symbol")
        qty = pos.get("position", 0) or pos.get("qty", 0)
        if not symbol or not qty:
            continue
        action = "SELL" if qty > 0 else "BUY"
        try:
            order_id = queue_order({
                "symbol": symbol.upper(),
                "action": action,
                "quantity": abs(int(qty)),
                "order_type": "MKT",
                "limit_price": None,
                "stop_price": None,
                "time_in_force": "DAY",
                "trade_id": f"flatten_{symbol}_{int(datetime.now(timezone.utc).timestamp())}"
            })
            queued.append({"symbol": symbol, "action": action, "quantity": abs(int(qty)), "order_id": order_id})
        except Exception as e:
            errors.append({"symbol": symbol, "error": str(e)})
    
    _last_flatten_ts["ts"] = now
    
    return {
        "success": True,
        "message": f"Queued {len(queued)} flatten order(s)",
        "orders": queued,
        "errors": errors,
        "cancelled_stale_orders": cancelled_stale,
        "cooldown_sec": _FLATTEN_COOLDOWN_SEC,
        "account": next(iter(paper_accounts), None)
    }
