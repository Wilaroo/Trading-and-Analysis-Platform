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
def get_config():
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
    """Test connection to Ollama - checks HTTP proxy first, then direct connection."""
    
    # First check if HTTP proxy is connected via the proxy status endpoint
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Check our own proxy status
            response = await client.get("http://localhost:8001/api/ollama-proxy/status")
            if response.status_code == 200:
                data = response.json()
                if data.get("any_connected"):
                    # Get models from HTTP proxy sessions
                    http_sessions = data.get("http", {}).get("sessions", [])
                    if http_sessions:
                        models = http_sessions[0].get("models", [])
                        return {
                            "connected": True, 
                            "models": models,
                            "method": "http_proxy",
                            "message": "Connected via HTTP proxy (local Ollama)"
                        }
                    # Or from WebSocket
                    ws_status = data.get("websocket", {})
                    if ws_status.get("connected"):
                        models = ws_status.get("models", [])
                        return {
                            "connected": True,
                            "models": models,
                            "method": "websocket_proxy"
                        }
    except Exception as e:
        pass  # Fall through to direct connection check
    
    # Fallback: check direct connection via ngrok/tunnel (old method)
    ollama_url = os.environ.get("OLLAMA_URL", "")
    
    if not ollama_url:
        return {"connected": False, "error": "No Ollama connection - run ollama_http.py locally"}
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{ollama_url}/api/tags")
            if response.status_code == 200:
                data = response.json()
                models = [m.get("name", "unknown") for m in data.get("models", [])]
                return {"connected": True, "models": models, "method": "direct"}
            elif response.status_code == 403:
                return {"connected": False, "error": "403 Forbidden - Check ngrok/tunnel settings"}
            else:
                return {"connected": False, "error": f"HTTP {response.status_code}"}
    except httpx.TimeoutException:
        return {"connected": False, "error": "Connection timed out - run ollama_http.py locally"}
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


class OllamaModelConfig(BaseModel):
    model: str


@router.post("/ollama-model")
def update_ollama_model(config: OllamaModelConfig):
    """Update the Ollama model at runtime."""
    new_model = config.model.strip()
    
    # List of supported models
    supported_models = ["qwen2.5:3b", "qwen2.5:7b", "llama3:8b", "deepseek-r1:8b", "mistral:7b"]
    
    if new_model not in supported_models:
        # Allow it anyway but warn
        logger.warning(f"Model {new_model} is not in standard list, proceeding anyway")
    
    # Update the environment variable
    os.environ["OLLAMA_MODEL"] = new_model
    
    # Also update the .env file for persistence across restarts
    env_path = "/app/backend/.env"
    try:
        with open(env_path, 'r') as f:
            lines = f.readlines()
        
        updated = False
        for i, line in enumerate(lines):
            if line.startswith('OLLAMA_MODEL='):
                lines[i] = f'OLLAMA_MODEL={new_model}\n'
                updated = True
                break
        
        if not updated:
            lines.append(f'OLLAMA_MODEL={new_model}\n')
        
        with open(env_path, 'w') as f:
            f.writelines(lines)
        
        logger.info(f"Updated OLLAMA_MODEL to {new_model}")
    except Exception as e:
        logger.error(f"Failed to update .env file: {e}")
        # Still return success since runtime env was updated
    
    return {"success": True, "message": f"Ollama model updated to {new_model}", "model": new_model}
