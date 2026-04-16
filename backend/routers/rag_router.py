"""
RAG API Router - Retrieval-Augmented Generation Endpoints

Provides API access to:
- Context retrieval for AI prompts
- Similar trade search
- Sync management
- RAG statistics
"""

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from services.rag import get_rag_service

router = APIRouter(prefix="/api/rag", tags=["rag"])


class RetrieveContextRequest(BaseModel):
    query: str
    context: Optional[Dict[str, Any]] = None
    n_results: int = 5
    collections: Optional[List[str]] = None


class AugmentPromptRequest(BaseModel):
    user_message: str
    current_context: Optional[Dict[str, Any]] = None


class SimilarTradesRequest(BaseModel):
    symbol: Optional[str] = None
    setup_type: Optional[str] = None
    market_regime: Optional[str] = None
    n_results: int = 10


@router.get("/stats")
def get_rag_stats():
    """Get RAG service statistics"""
    service = get_rag_service()
    return {
        "success": True,
        "stats": service.get_stats()
    }


@router.get("/needs-sync")
def check_needs_sync():
    """Check if RAG data needs to be synced from MongoDB"""
    service = get_rag_service()
    return {
        "success": True,
        "needs_sync": service.needs_sync()
    }


@router.post("/sync")
async def sync_from_mongodb(
    background_tasks: BackgroundTasks,
    force: bool = Query(default=False, description="Force sync even if recently synced")
):
    """
    Sync data from MongoDB to ChromaDB vector store.
    
    This should be called:
    - On startup (auto-triggered)
    - When switching machines
    - After significant data changes
    
    Runs in background if not forced.
    """
    service = get_rag_service()
    
    if force:
        # Run sync synchronously
        result = await service.sync_from_mongodb(force=True)
        return {
            "success": True,
            "result": result
        }
    else:
        # Run in background
        background_tasks.add_task(service.sync_from_mongodb, False)
        return {
            "success": True,
            "message": "Sync started in background"
        }


@router.post("/retrieve")
async def retrieve_context(request: RetrieveContextRequest):
    """
    Retrieve relevant context for an AI prompt.
    
    Returns similar trades, playbooks, and insights based on the query.
    """
    service = get_rag_service()
    
    result = await service.retrieve_context(
        query=request.query,
        context=request.context,
        n_results=request.n_results,
        collections=request.collections
    )
    
    return {
        "success": True,
        "retrieval": result
    }


@router.post("/augment-prompt")
async def augment_prompt(request: AugmentPromptRequest):
    """
    Augment a user message with relevant trading context.
    
    Use this before sending a message to the AI to inject personalized context.
    """
    service = get_rag_service()
    
    augmented = await service.augment_prompt(
        user_message=request.user_message,
        current_context=request.current_context
    )
    
    return {
        "success": True,
        "original_message": request.user_message,
        "augmented_prompt": augmented,
        "was_augmented": augmented != request.user_message
    }


@router.post("/similar-trades")
async def find_similar_trades(request: SimilarTradesRequest):
    """
    Find historical trades similar to the current context.
    
    Useful for:
    - Pre-trade analysis ("How have I done with this setup before?")
    - Pattern recognition
    - Performance analysis
    """
    service = get_rag_service()
    
    results = await service.get_similar_trades(
        symbol=request.symbol,
        setup_type=request.setup_type,
        market_regime=request.market_regime,
        n_results=request.n_results
    )
    
    return {
        "success": True,
        "similar_trades": results,
        "count": len(results)
    }


@router.get("/collections")
def get_collections():
    """Get information about RAG collections"""
    from services.rag.vector_store import VectorStoreService
    
    return {
        "success": True,
        "collections": VectorStoreService.COLLECTIONS
    }


@router.get("/embedding-stats")
def get_embedding_stats():
    """Get embedding service statistics (cache hits, model info)"""
    from services.rag.embedding_service import get_embedding_service
    
    service = get_embedding_service()
    return {
        "success": True,
        "stats": service.get_stats()
    }


@router.post("/clear-cache")
def clear_embedding_cache():
    """Clear the embedding cache (useful for memory management)"""
    from services.rag.embedding_service import get_embedding_service
    
    service = get_embedding_service()
    service.clear_cache()
    
    return {
        "success": True,
        "message": "Embedding cache cleared"
    }


@router.delete("/reset")
def reset_vector_store():
    """
    Reset all RAG data (clear ChromaDB collections).
    
    WARNING: This will delete all indexed data. Use with caution.
    """
    from services.rag.vector_store import get_vector_store_service
    
    service = get_vector_store_service()
    service.reset_all()
    
    return {
        "success": True,
        "message": "Vector store reset. Run /sync to rebuild from MongoDB."
    }
