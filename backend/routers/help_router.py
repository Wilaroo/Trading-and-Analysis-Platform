"""
Help Router
===========

Exposes the in-app glossary as a public read-only API so:
  - The frontend chat assistant can quote definitions verbatim
  - External tools / a future help bot can answer "what is X?" by
    consulting the same source of truth the UI uses
  - Tests can validate that every UI badge has a documented entry

All routes are mounted under `/api/help`.
"""
import logging

from fastapi import APIRouter, HTTPException, Query

from services.glossary_service import (
    find_terms,
    get_term,
    load_glossary,
    reload_glossary,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/help", tags=["help"])


@router.get("/terms")
async def list_terms(
    q: str | None = Query(None, description="Optional search query"),
    limit: int = Query(50, ge=1, le=200),
):
    """List glossary entries. With `?q=…` performs a tolerant match
    against term, id, shortDef, and tags."""
    if q:
        return {"success": True, "query": q, "entries": find_terms(q, limit=limit)}
    data = load_glossary()
    return {
        "success": True,
        "categories": data.get("categories", []),
        "entries": data.get("entries", [])[:limit],
        "total": len(data.get("entries", [])),
    }


@router.get("/terms/{term_id}")
async def fetch_term(term_id: str):
    entry = get_term(term_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Unknown glossary term: {term_id}")
    return {"success": True, "entry": entry}


@router.post("/reload")
async def reload_terms():
    """Force a re-parse of the JS glossary file (after a doc edit)."""
    data = reload_glossary()
    return {
        "success": True,
        "categories": len(data.get("categories", [])),
        "entries": len(data.get("entries", [])),
    }
