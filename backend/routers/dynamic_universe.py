"""Dynamic Universe API — v19.34.211.

Read + manual-rebuild endpoints for the Dynamic Universe Builder
(today's priority-ranked scan universe: liquid core + IB movers +
catalysts + held, regime-tilted).
"""
from fastapi import APIRouter, HTTPException, Query

from services.dynamic_universe_builder import get_dynamic_universe_builder

router = APIRouter(prefix="/api/dynamic-universe", tags=["Dynamic Universe"])

_db = None


def init_dynamic_universe_router(db):
    global _db
    _db = db
    get_dynamic_universe_builder(db).set_db(db)


@router.get("")
async def get_dynamic_universe(date: str = Query(None, description="ET date YYYY-MM-DD; defaults to today")):
    """Return today's (or a given date's) dynamic universe doc."""
    builder = get_dynamic_universe_builder(_db)
    doc = builder.get_doc(date)
    if not doc:
        return {"exists": False, "date": date, "symbols": [], "priority_symbols": []}
    doc.pop("_id", None)
    return {"exists": True, **doc}


@router.get("/priority")
async def get_priority_symbols(limit: int = Query(40, ge=1, le=200)):
    """Return just the top priority symbols (Tier-1 / front-load list)."""
    builder = get_dynamic_universe_builder(_db)
    return {
        "priority_symbols": builder.get_priority_symbols(limit),
        "fresh": builder.is_fresh(),
    }


@router.post("/rebuild")
async def rebuild_dynamic_universe(force: bool = Query(True)):
    """Force an immediate rebuild (operator / debug)."""
    builder = get_dynamic_universe_builder(_db)
    if _db is None:
        raise HTTPException(status_code=503, detail="DB not initialised")
    try:
        doc = await builder.build(force=force)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"build failed: {e}")
    doc.pop("_id", None)
    return {"ok": True, **doc}
