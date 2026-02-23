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
    """Get current configuration values."""
    ollama_url = os.environ.get("OLLAMA_URL", "")
    ollama_model = os.environ.get("OLLAMA_MODEL", "deepseek-r1:8b")
    
    # Test connection to Ollama
    ollama_connected = False
    if ollama_url:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{ollama_url}/api/tags")
                ollama_connected = response.status_code == 200
        except Exception as e:
            logger.warning(f"Ollama connection test failed: {e}")
            ollama_connected = False
    
    return ConfigResponse(
        ollama_url=ollama_url,
        ollama_model=ollama_model,
        ollama_connected=ollama_connected
    )


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
