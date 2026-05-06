"""
Social Feed Router - API endpoints for Twitter/X social feed management and AI sentiment analysis.
All endpoints are sync def so FastAPI runs them in a thread pool.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/social-feed", tags=["social-feed"])

# Initialized from server.py
_service = None


def init_social_feed_router(service):
    global _service
    _service = service


class HandleInput(BaseModel):
    handle: str
    label: Optional[str] = ""
    category: Optional[str] = "trading"
    description: Optional[str] = ""


class SentimentInput(BaseModel):
    text: str
    handle: Optional[str] = ""


@router.get("/handles")
def get_handles():
    """Get all configured Twitter/X handles."""
    if not _service:
        raise HTTPException(500, "Social feed service not initialized")
    handles = _service.get_handles()
    return {"success": True, "handles": handles, "count": len(handles)}


@router.post("/handles")
def add_handle(input: HandleInput):
    """Add a new handle to follow."""
    if not _service:
        raise HTTPException(500, "Social feed service not initialized")
    result = _service.add_handle(input.handle, input.label, input.category, input.description)
    return result


@router.delete("/handles/{handle}")
def remove_handle(handle: str):
    """Remove a handle from the follow list."""
    if not _service:
        raise HTTPException(500, "Social feed service not initialized")
    result = _service.remove_handle(handle)
    return result


@router.post("/analyze")
def analyze_sentiment(input: SentimentInput):
    """Analyze sentiment of pasted tweet/post text using AI."""
    if not _service:
        raise HTTPException(500, "Social feed service not initialized")
    if not input.text.strip():
        raise HTTPException(400, "Text is required")
    analysis = _service.analyze_sentiment(input.text, input.handle)
    return {"success": True, "analysis": analysis}


@router.get("/analyses")
def get_recent_analyses(limit: int = 20):
    """Get recent sentiment analyses."""
    if not _service:
        raise HTTPException(500, "Social feed service not initialized")
    analyses = _service.get_recent_analyses(limit)
    return {"success": True, "analyses": analyses, "count": len(analyses)}
