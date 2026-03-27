"""
Short Interest Data API Router
================================
Endpoints for short interest data from IB and FINRA.
"""

import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/short-data", tags=["Short Interest Data"])


class IBShortDataItem(BaseModel):
    symbol: str
    shortable_shares: int = 0
    shortable_level: float = 0
    timestamp: Optional[str] = None


class IBShortDataPush(BaseModel):
    data: List[IBShortDataItem]


class FINRAFetchRequest(BaseModel):
    symbols: Optional[List[str]] = None
    settlement_date: Optional[str] = None
    force: bool = False


def _get_service():
    from server import db as mongo_db
    if mongo_db is None:
        raise HTTPException(status_code=503, detail="Database not connected")
    from services.short_interest_service import ShortInterestService
    return ShortInterestService(mongo_db)


@router.post("/ib/push")
async def push_ib_short_data(payload: IBShortDataPush):
    """
    Receive IB shortable shares data from the local IB data pusher.
    Called by the pusher script on the user's local machine.
    """
    svc = _get_service()
    data = [item.dict() for item in payload.data]
    result = await svc.store_ib_short_data(data)
    return {"success": True, **result}


@router.post("/finra/fetch")
async def fetch_finra_data(request: FINRAFetchRequest):
    """
    Fetch and store short interest data from FINRA's free API.
    Auto-discovers latest settlement date. Skips if already populated (use force=true to re-fetch).
    Runs as background task for full fetches.
    """
    svc = _get_service()

    # Small targeted requests run inline
    if request.symbols and len(request.symbols) <= 10:
        result = await svc.fetch_finra_short_interest(
            symbols=request.symbols,
            settlement_date=request.settlement_date,
            force=request.force,
        )
        return result

    # Full fetches run in background
    import asyncio
    loop = asyncio.get_event_loop()
    loop.create_task(svc.fetch_finra_short_interest(
        symbols=request.symbols,
        settlement_date=request.settlement_date,
        force=request.force,
    ))
    return {
        "success": True,
        "message": "FINRA fetch started in background. Check /api/short-data/summary for progress.",
    }


@router.get("/symbol/{symbol}")
async def get_symbol_short_data(symbol: str):
    """
    Get combined short data (IB + FINRA) for a specific symbol.
    """
    svc = _get_service()
    result = await svc.get_short_data_for_symbol(symbol)
    return {"success": True, **result}


@router.get("/bulk")
async def get_bulk_short_data(symbols: Optional[str] = None, limit: int = 100):
    """
    Get short data for multiple symbols.
    Pass comma-separated symbols or leave empty for top results.
    """
    svc = _get_service()
    symbol_list = [s.strip().upper() for s in symbols.split(",")] if symbols else None
    results = await svc.get_short_data_bulk(symbols=symbol_list, limit=limit)
    return {"success": True, "count": len(results), "data": results}


@router.get("/summary")
async def get_short_data_summary():
    """
    Get a summary of available short data.
    """
    svc = _get_service()
    db = svc.db

    ib_count = int(db["ib_short_data"].count_documents({}))
    finra_count = int(db["finra_short_interest"].count_documents({}))

    # Get latest FINRA settlement date
    latest_date = None
    try:
        latest_finra_cursor = db["finra_short_interest"].find(
            {}, {"_id": 0, "settlement_date": 1}
        ).sort("settlement_date", -1).limit(1)
        latest_list = list(latest_finra_cursor)
        latest_date = str(latest_list[0]["settlement_date"]) if latest_list else None
    except Exception:
        pass

    # Get unique FINRA symbols count
    try:
        finra_symbols = int(len(db["finra_short_interest"].distinct("symbol")))
    except Exception:
        finra_symbols = 0

    # Hard to borrow count
    htb_count = int(db["ib_short_data"].count_documents({"shortable_level": {"$lte": 1.5}}))

    return {
        "success": True,
        "ib_symbols": ib_count,
        "finra_records": finra_count,
        "finra_unique_symbols": finra_symbols,
        "latest_settlement_date": latest_date,
        "hard_to_borrow_count": htb_count,
    }
