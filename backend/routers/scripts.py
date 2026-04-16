"""
Scripts Router - Serves local scripts for auto-update functionality.
This allows StartTrading.bat to download the latest scripts from the cloud.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
import os
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scripts", tags=["Scripts"])

# Mapping of script names to their locations
SCRIPT_PATHS = {
    "ib_data_pusher.py": [
        "/app/documents/scripts/ib_data_pusher.py",  # Preferred - user-facing
        "/app/scripts/ib_data_pusher.py",            # Fallback
    ],
    "ollama_http.py": [
        "/app/documents/scripts/ollama_http.py",     # Preferred - user-facing
        "/app/scripts/ollama_http.py",               # Fallback
    ],
    "StartTrading.bat": [
        "/app/documents/StartTrading.bat",
        "/app/scripts/StartTrading.bat",
    ],
    "NightlyAuto.bat": [
        "/app/documents/NightlyAuto.bat",
        "/app/scripts/NightlyAuto.bat",
    ],
    "WeekendAuto.bat": [
        "/app/documents/WeekendAuto.bat",
        "/app/scripts/WeekendAuto.bat",
    ],
}


@router.get("/{script_name}")
def get_script(script_name: str):
    """
    Download a script by name.
    Used by StartTrading.bat for auto-updates.
    """
    if script_name not in SCRIPT_PATHS:
        raise HTTPException(
            status_code=404, 
            detail=f"Script not found: {script_name}. Available: {list(SCRIPT_PATHS.keys())}"
        )
    
    # Try each path in order
    for path in SCRIPT_PATHS[script_name]:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                logger.info(f"Serving script {script_name} from {path}")
                return PlainTextResponse(content, media_type="text/plain")
            except Exception as e:
                logger.error(f"Error reading {path}: {e}")
                continue
    
    raise HTTPException(
        status_code=404,
        detail=f"Script file not found on disk: {script_name}"
    )


@router.get("/")
def list_scripts():
    """List available scripts for download."""
    available = {}
    for name, paths in SCRIPT_PATHS.items():
        for path in paths:
            if os.path.exists(path):
                available[name] = {
                    "path": path,
                    "size": os.path.getsize(path),
                    "modified": os.path.getmtime(path)
                }
                break
        else:
            available[name] = {"status": "not_found"}
    
    return {"scripts": available}
