"""
Trade Snapshots Router - API endpoints for chart snapshots with AI annotations.
All endpoints are sync def so FastAPI runs them in a thread pool,
avoiding event loop saturation from IB Gateway retries.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from typing import Optional
import base64

router = APIRouter(prefix="/api/trades/snapshots", tags=["trade-snapshots"])

# Initialized from server.py
snapshot_service = None


def init_snapshot_service(service):
    global snapshot_service
    snapshot_service = service


@router.get("/{trade_id}")
def get_snapshot(trade_id: str, source: str = "bot"):
    """Get existing snapshot for a trade (returns metadata + base64 chart)."""
    if not snapshot_service:
        raise HTTPException(500, "Snapshot service not initialized")

    snap = snapshot_service.get_snapshot(trade_id, source)
    if not snap:
        return {"success": False, "error": "No snapshot found", "snapshot": None}

    return {"success": True, "snapshot": snap}


@router.get("/{trade_id}/image")
def get_snapshot_image(trade_id: str, source: str = "bot"):
    """Get just the chart image as a PNG file."""
    if not snapshot_service:
        raise HTTPException(500, "Snapshot service not initialized")

    snap = snapshot_service.get_snapshot(trade_id, source)
    if not snap or not snap.get("chart_image"):
        raise HTTPException(404, "No snapshot image found")

    image_bytes = base64.b64decode(snap["chart_image"])
    return Response(content=image_bytes, media_type="image/png")


@router.post("/{trade_id}/generate")
def generate_snapshot(trade_id: str, source: str = "bot"):
    """Generate (or regenerate) a snapshot for a specific trade. Runs sync to avoid event loop blocking."""
    if not snapshot_service:
        raise HTTPException(500, "Snapshot service not initialized")

    result = snapshot_service.generate_snapshot_sync(trade_id, source)
    return result


@router.post("/batch")
def batch_generate(limit: int = 50):
    """Generate snapshots for closed trades that don't have one yet. Runs sync."""
    if not snapshot_service:
        raise HTTPException(500, "Snapshot service not initialized")

    result = snapshot_service.batch_generate_sync(limit=limit)
    return {"success": True, **result}


@router.get("")
def list_snapshots(source: Optional[str] = None, limit: int = 50):
    """List existing snapshots (metadata only, no chart images)."""
    if not snapshot_service:
        raise HTTPException(500, "Snapshot service not initialized")

    query = {}
    if source:
        query["source"] = source

    snapshots = list(snapshot_service.snapshots_col.find(
        query,
        {"_id": 0, "chart_image": 0}  # Exclude heavy image data
    ).sort("generated_at", -1).limit(limit))

    return {"success": True, "snapshots": snapshots, "count": len(snapshots)}
