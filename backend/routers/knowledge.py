"""
Knowledge Base API Router
Endpoints for managing the trading knowledge base.
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from services.knowledge_service import get_knowledge_service

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class KnowledgeEntry(BaseModel):
    """Schema for creating/updating knowledge entries"""
    title: str = Field(..., min_length=1, max_length=200, description="Entry title")
    content: str = Field(..., min_length=1, description="Full content")
    type: str = Field(default="note", description="Entry type: strategy, pattern, insight, rule, note, indicator, checklist")
    category: str = Field(default="general", description="Category: entry, exit, risk_management, etc.")
    tags: List[str] = Field(default=[], description="Tags for filtering")
    source: str = Field(default="user", description="Source: user, backtest, observation, research")
    confidence: int = Field(default=80, ge=0, le=100, description="Confidence level 0-100")
    metadata: Dict[str, Any] = Field(default={}, description="Additional structured data")


class KnowledgeUpdate(BaseModel):
    """Schema for partial updates"""
    title: Optional[str] = None
    content: Optional[str] = None
    type: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    source: Optional[str] = None
    confidence: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


@router.post("")
async def add_knowledge(entry: KnowledgeEntry):
    """
    Add a new knowledge entry.
    
    Types: strategy, pattern, insight, rule, note, indicator, checklist
    Categories: entry, exit, risk_management, position_sizing, market_condition, 
                technical, fundamental, sentiment, premarket, intraday, swing, general
    """
    service = get_knowledge_service()
    result = service.add(
        title=entry.title,
        content=entry.content,
        type=entry.type,
        category=entry.category,
        tags=entry.tags,
        source=entry.source,
        confidence=entry.confidence,
        metadata=entry.metadata
    )
    return {"success": True, "entry": result}


@router.get("")
async def search_knowledge(
    q: Optional[str] = Query(None, description="Text search query"),
    type: Optional[str] = Query(None, description="Filter by type"),
    category: Optional[str] = Query(None, description="Filter by category"),
    tags: Optional[str] = Query(None, description="Comma-separated tags"),
    limit: int = Query(50, ge=1, le=200, description="Max results")
):
    """
    Search the knowledge base.
    
    Examples:
    - /api/knowledge?q=momentum - Full text search
    - /api/knowledge?type=strategy - Get all strategies
    - /api/knowledge?category=entry - Get all entry-related knowledge
    - /api/knowledge?tags=breakout,volume - Filter by tags
    """
    service = get_knowledge_service()
    
    tag_list = None
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    
    results = service.search(
        query=q,
        type=type,
        category=category,
        tags=tag_list,
        limit=limit
    )
    
    return {
        "count": len(results),
        "results": results
    }


@router.get("/stats")
async def get_stats():
    """Get knowledge base statistics"""
    service = get_knowledge_service()
    return service.get_stats()


@router.get("/types")
async def get_types():
    """Get available types and categories"""
    service = get_knowledge_service()
    return {
        "types": service.TYPES,
        "categories": service.CATEGORIES
    }


@router.get("/{entry_id}")
async def get_knowledge(entry_id: str):
    """Get a specific knowledge entry by ID"""
    service = get_knowledge_service()
    entry = service.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


@router.put("/{entry_id}")
async def update_knowledge(entry_id: str, updates: KnowledgeUpdate):
    """Update a knowledge entry"""
    service = get_knowledge_service()
    
    # Convert to dict and remove None values
    update_dict = {k: v for k, v in updates.dict().items() if v is not None}
    
    if not update_dict:
        raise HTTPException(status_code=400, detail="No updates provided")
    
    result = service.update(entry_id, update_dict)
    if not result:
        raise HTTPException(status_code=404, detail="Entry not found or update failed")
    
    return {"success": True, "entry": result}


@router.delete("/{entry_id}")
async def delete_knowledge(entry_id: str, hard: bool = Query(False, description="Permanently delete")):
    """
    Delete a knowledge entry.
    By default, soft-deletes (marks as inactive). Use hard=true for permanent deletion.
    """
    service = get_knowledge_service()
    
    if hard:
        success = service.hard_delete(entry_id)
    else:
        success = service.delete(entry_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Entry not found or delete failed")
    
    return {"success": True, "deleted": entry_id}


@router.get("/export/all")
async def export_knowledge():
    """Export all knowledge entries for backup"""
    service = get_knowledge_service()
    entries = service.export_all()
    return {
        "count": len(entries),
        "entries": entries
    }


@router.post("/import")
async def import_knowledge(data: Dict[str, Any]):
    """
    Import knowledge entries from backup.
    Expects: {"entries": [...]}
    """
    service = get_knowledge_service()
    entries = data.get("entries", [])
    
    if not entries:
        raise HTTPException(status_code=400, detail="No entries provided")
    
    count = service.import_entries(entries)
    return {"success": True, "imported": count}
