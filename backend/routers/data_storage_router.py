"""
Data Storage Router - API endpoints for data storage management
"""

from fastapi import APIRouter, HTTPException
from typing import Optional
import logging

from services.data_storage_manager import get_storage_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/data-storage", tags=["data-storage"])


@router.get("/stats")
def get_storage_stats():
    """Get statistics about all stored data collections"""
    try:
        manager = get_storage_manager()
        stats = manager.get_storage_stats()
        return stats
    except Exception as e:
        logger.error(f"Error getting storage stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/learning-summary")
def get_learning_summary():
    """Get summary of all data available for learning/training"""
    try:
        manager = get_storage_manager()
        summary = manager.get_learning_data_summary()
        return summary
    except Exception as e:
        logger.error(f"Error getting learning summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cleanup")
def cleanup_old_data(dry_run: bool = True):
    """
    Clean up data past retention period.
    
    - **dry_run**: If True, only report what would be deleted (default: True)
    """
    try:
        manager = get_storage_manager()
        result = manager.cleanup_old_data(dry_run=dry_run)
        return result
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/export/{source}")
def export_training_data(
    source: str,
    symbol: Optional[str] = None,
    limit: int = 10000
):
    """
    Export data for model training.
    
    - **source**: Data source (ib_historical, simulations, shadow_decisions)
    - **symbol**: Optional symbol filter
    - **limit**: Max records to return (default: 10000)
    """
    try:
        manager = get_storage_manager()
        result = manager.export_training_data(
            source=source,
            symbol=symbol,
            limit=limit
        )
        return result
    except Exception as e:
        logger.error(f"Error exporting data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/collections")
def list_collections():
    """List all managed collections with their descriptions"""
    try:
        from services.data_storage_manager import DataStorageManager
        
        collections = {}
        for name, config in DataStorageManager.COLLECTIONS.items():
            collections[name] = {
                "description": config["description"],
                "retention_days": config["retention_days"],
                "index_count": len(config["indexes"])
            }
            
        return {
            "success": True,
            "collections": collections,
            "count": len(collections)
        }
    except Exception as e:
        logger.error(f"Error listing collections: {e}")
        raise HTTPException(status_code=500, detail=str(e))
