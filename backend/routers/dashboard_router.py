"""
Dashboard Router - Dashboard init and stats endpoints
Extracted from server.py for modularity.
"""
from fastapi import APIRouter
from datetime import datetime, timezone
from typing import Dict, List, Optional
import asyncio

router = APIRouter(tags=["Dashboard"])

# Module-level service references (injected via init)
_get_portfolio = None
_get_alerts = None
_get_watchlist = None
_strategy_service = None
_get_ib_service = None
_get_smart_watchlist = None
_background_scanner = None
_assistant_service = None
_alerts_col = None
_fetch_multiple_quotes = None
_score_stock_for_strategies = None
_get_all_strategies_cached = None
_scans_col = None
_wave_scanner = None
_index_universe = None


def init_dashboard_router(
    get_portfolio,
    get_watchlist,
    strategy_service,
    get_ib_service,
    get_smart_watchlist,
    background_scanner,
    assistant_service,
    alerts_col,
    fetch_multiple_quotes,
    score_stock_for_strategies,
    get_all_strategies_cached,
    scans_col,
    wave_scanner,
    index_universe,
):
    global _get_portfolio, _get_watchlist, _strategy_service
    global _get_ib_service
    global _get_smart_watchlist
    global _background_scanner, _assistant_service, _alerts_col
    global _fetch_multiple_quotes, _score_stock_for_strategies
    global _get_all_strategies_cached, _scans_col, _wave_scanner, _index_universe

    _get_portfolio = get_portfolio
    _get_watchlist = get_watchlist
    _strategy_service = strategy_service
    _get_ib_service = get_ib_service
    _get_smart_watchlist = get_smart_watchlist
    _background_scanner = background_scanner
    _assistant_service = assistant_service
    _alerts_col = alerts_col
    _fetch_multiple_quotes = fetch_multiple_quotes
    _score_stock_for_strategies = score_stock_for_strategies
    _get_all_strategies_cached = get_all_strategies_cached
    _scans_col = scans_col
    _wave_scanner = wave_scanner
    _index_universe = index_universe


# ===================== DASHBOARD =====================

@router.get("/api/dashboard/stats")
async def get_dashboard_stats():
    """Get dashboard statistics"""
    portfolio = await _get_portfolio()
    alerts_data = await get_alerts(unread_only=True)
    watchlist = await _get_watchlist()

    return {
        "portfolio_value": portfolio["summary"]["total_value"],
        "portfolio_change": portfolio["summary"]["total_gain_loss_percent"],
        "unread_alerts": alerts_data["unread_count"],
        "watchlist_count": watchlist["count"],
        "strategies_count": _strategy_service.get_strategy_count(),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/api/dashboard/init")
async def get_dashboard_init():
    """
    Batch endpoint for initial dashboard data load.
    Returns multiple data sources in one request to reduce API calls on startup.
    """
    try:
        ib_status = _get_ib_service().get_connection_status()

        is_busy, busy_op = _get_ib_service().is_busy()
        ib_status["is_busy"] = is_busy
        ib_status["busy_operation"] = busy_op

        from routers.system_router import system_monitor
        system_health = await system_monitor()

        alerts_data = await get_alerts()

        smart_watchlist_items = _get_smart_watchlist()

        scanner_status = {
            "active": _background_scanner._running if _background_scanner else False,
            "alerts_count": len(_background_scanner._live_alerts) if _background_scanner else 0,
        }

        return {
            "ib_status": ib_status,
            "system_health": system_health,
            "alerts": alerts_data,
            "smart_watchlist": [item.to_dict() for item in smart_watchlist_items[:20]],
            "scanner_status": scanner_status,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        return {
            "error": str(e),
            "ib_status": {"connected": False},
            "system_health": {"overall_status": "error"},
            "alerts": {"alerts": [], "unread_count": 0},
            "smart_watchlist": [],
            "scanner_status": {"active": False},
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


# ===================== ALERTS (basic CRUD) =====================

@router.get("/api/alerts")
async def get_alerts(unread_only: bool = False):
    """Get all alerts"""
    query = {"read": False} if unread_only else {}
    alerts = await asyncio.to_thread(lambda: list(_alerts_col.find(query, {"_id": 0}).sort("timestamp", -1).limit(50)))
    unread_count = await asyncio.to_thread(_alerts_col.count_documents, {"read": False})
    return {"alerts": alerts, "unread_count": unread_count}


@router.post("/api/alerts/generate")
async def generate_alerts():
    """Generate alerts based on strategy criteria"""
    symbols = ["AAPL", "MSFT", "GOOGL", "NVDA", "TSLA", "AMD", "META", "AMZN"]
    quotes = await _fetch_multiple_quotes(symbols)

    new_alerts = []
    all_strategies = _get_all_strategies_cached()
    for quote in quotes:
        score_data = await _score_stock_for_strategies(quote["symbol"], quote)

        if score_data["score"] >= 60:
            for strategy_id in score_data["matched_strategies"][:2]:
                strategy = next((s for s in all_strategies if s["id"] == strategy_id), None)
                if strategy:
                    alert = {
                        "symbol": quote["symbol"],
                        "strategy_id": strategy_id,
                        "strategy_name": strategy["name"],
                        "message": f"{quote['symbol']} matches {strategy['name']} criteria",
                        "criteria_met": strategy["criteria"][:3],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "read": False,
                        "score": score_data["score"],
                        "change_percent": quote["change_percent"]
                    }
                    alert_doc = alert.copy()
                    await asyncio.to_thread(_alerts_col.insert_one, alert_doc)
                    new_alerts.append(alert)

    return {"alerts_generated": len(new_alerts), "alerts": new_alerts}


@router.delete("/api/alerts/clear")
async def clear_alerts():
    """Clear all alerts"""
    result = await asyncio.to_thread(_alerts_col.delete_many, {})
    return {"deleted": result.deleted_count}


# ===================== SCANNER =====================

@router.post("/api/scanner/scan")
async def run_scanner(
    symbols: List[str],
    category: Optional[str] = None,
    min_score: int = 50,
    include_fundamentals: bool = False
):
    """
    Scan symbols against all 50 strategy criteria.
    Uses detailed criteria matching for Intraday, Swing, and Investment strategies.
    """
    from services.stock_data import get_stock_service

    quotes = await _fetch_multiple_quotes([s.upper() for s in symbols])

    results = []
    for quote in quotes:
        fundamentals = None
        if include_fundamentals or (category and category.lower() == "investment"):
            try:
                stock_svc = get_stock_service()
                fundamentals = await stock_svc.fetch_fundamentals(quote["symbol"])
            except Exception:
                fundamentals = None

        score_data = await _score_stock_for_strategies(
            quote["symbol"],
            quote,
            fundamentals=fundamentals,
            category_filter=category.lower() if category else None
        )

        if score_data["score"] >= min_score:
            results.append({
                **score_data,
                "quote": quote,
                "has_fundamentals": fundamentals is not None
            })

    results.sort(key=lambda x: x["score"], reverse=True)

    scan_doc = {
        "symbols": symbols,
        "category": category,
        "min_score": min_score,
        "results_count": len(results),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await asyncio.to_thread(_scans_col.insert_one, scan_doc)

    return {
        "results": results[:20],
        "total_scanned": len(symbols),
        "category_filter": category,
        "min_score_filter": min_score,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/api/scanner/presets")
async def get_scanner_presets():
    """Get predefined scanner presets"""
    presets = [
        {"name": "Momentum Movers", "symbols": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "AMD", "NFLX", "CRM"], "min_score": 40},
        {"name": "Tech Leaders", "symbols": ["AAPL", "MSFT", "GOOGL", "META", "NVDA", "AMD", "INTC", "AVGO", "QCOM", "ADBE"], "min_score": 30},
        {"name": "High Beta", "symbols": ["TSLA", "NVDA", "AMD", "COIN", "MSTR", "SQ", "SHOP", "ROKU", "SNAP", "PLTR"], "min_score": 40},
        {"name": "Dividend Aristocrats", "symbols": ["JNJ", "PG", "KO", "PEP", "MMM", "ABT", "WMT", "TGT", "MCD", "HD"], "min_score": 20},
    ]
    return {"presets": presets}


# ===================== WAVE SCANNER =====================

@router.get("/api/wave-scanner/batch")
async def get_wave_scanner_batch():
    """
    Get the next batch of symbols to scan
    Returns tiered symbols: Tier1 (watchlist), Tier2 (high RVOL), Tier3 (universe wave)
    """
    batch = await _wave_scanner.get_scan_batch()
    return batch


@router.get("/api/wave-scanner/stats")
async def get_wave_scanner_stats():
    """Get wave scanner statistics"""
    return _wave_scanner.get_stats()


@router.get("/api/wave-scanner/config")
async def get_wave_scanner_config():
    """Get wave scanner configuration"""
    return _wave_scanner.get_scan_config()


# ===================== INDEX UNIVERSE =====================

@router.get("/api/universe/stats")
async def get_universe_stats():
    """Get index universe statistics"""
    return _index_universe.get_stats()


@router.get("/api/universe/symbols/{index_type}")
async def get_index_symbols(index_type: str):
    """
    Get symbols for a specific index
    Valid types: sp500, nasdaq100, russell2000, etf
    """
    from fastapi import HTTPException
    from services.index_universe import IndexType

    try:
        idx_type = IndexType(index_type.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid index type. Valid: sp500, nasdaq100, russell2000, etf"
        )

    symbols = _index_universe.get_index_symbols(idx_type)
    return {
        "index": index_type,
        "count": len(symbols),
        "symbols": symbols
    }
