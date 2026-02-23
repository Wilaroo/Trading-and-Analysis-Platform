"""
Configuration router for managing app settings like Ollama URL.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config", tags=["config"])


class OllamaConfig(BaseModel):
    url: str


class ConfigResponse(BaseModel):
    ollama_url: str
    ollama_model: str
    ollama_connected: bool = False


@router.get("", response_model=ConfigResponse)
async def get_config():
    """Get current configuration values - fast response, no connection test."""
    ollama_url = os.environ.get("OLLAMA_URL", "")
    ollama_model = os.environ.get("OLLAMA_MODEL", "deepseek-r1:8b")
    
    # Don't test connection on GET - let the user test manually
    return ConfigResponse(
        ollama_url=ollama_url,
        ollama_model=ollama_model,
        ollama_connected=False  # Will be tested via /test endpoint
    )


@router.get("/test-connection")
async def test_ollama_connection():
    """Test connection to Ollama - separate endpoint for explicit testing."""
    ollama_url = os.environ.get("OLLAMA_URL", "")
    
    if not ollama_url:
        return {"connected": False, "error": "No Ollama URL configured"}
    
    import httpx
    try:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "TradeCommand/1.0",
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{ollama_url}/api/tags", headers=headers)
            if response.status_code == 200:
                data = response.json()
                models = [m.get("name", "unknown") for m in data.get("models", [])]
                return {"connected": True, "models": models}
            elif response.status_code == 403:
                return {"connected": False, "error": "403 Forbidden - Cloudflare may be blocking. Try restarting tunnel."}
            else:
                return {"connected": False, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"connected": False, "error": str(e)}


@router.post("/ollama-url")
async def update_ollama_url(config: OllamaConfig):
    """Update the Ollama URL at runtime."""
    new_url = config.url.strip().rstrip('/')
    
    # Validate URL format
    if not new_url.startswith(('http://', 'https://')):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
    
    # Test connection to the new URL
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{new_url}/api/tags")
            if response.status_code != 200:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Could not connect to Ollama at {new_url}. Status: {response.status_code}"
                )
    except httpx.TimeoutException:
        raise HTTPException(status_code=400, detail=f"Connection to {new_url} timed out")
    except httpx.RequestError as e:
        raise HTTPException(status_code=400, detail=f"Could not connect to {new_url}: {str(e)}")
    
    # Update the environment variable
    os.environ["OLLAMA_URL"] = new_url
    
    # Also update the .env file for persistence across restarts
    env_path = "/app/backend/.env"
    try:
        with open(env_path, 'r') as f:
            lines = f.readlines()
        
        updated = False
        for i, line in enumerate(lines):
            if line.startswith('OLLAMA_URL='):
                lines[i] = f'OLLAMA_URL={new_url}\n'
                updated = True
                break
        
        if not updated:
            lines.append(f'OLLAMA_URL={new_url}\n')
        
        with open(env_path, 'w') as f:
            f.writelines(lines)
        
        logger.info(f"Updated OLLAMA_URL to {new_url}")
    except Exception as e:
        logger.error(f"Failed to update .env file: {e}")
        # Still return success since runtime env was updated
    
    return {"success": True, "message": f"Ollama URL updated to {new_url}", "url": new_url}
