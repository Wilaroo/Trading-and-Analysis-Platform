"""
Ollama Proxy WebSocket Handler
==============================
Receives connections from local Ollama proxy clients.
Routes Ollama requests through the connected proxy instead of ngrok.
"""

import asyncio
import json
import logging
from typing import Dict, Optional
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class OllamaProxyManager:
    """Manages connections from local Ollama proxy clients"""
    
    def __init__(self):
        self.proxy_connection: Optional[WebSocket] = None
        self.proxy_info: Dict = {}
        self.pending_requests: Dict[str, asyncio.Future] = {}
        self.request_counter = 0
        self._lock = asyncio.Lock()
    
    @property
    def is_connected(self) -> bool:
        return self.proxy_connection is not None
    
    @property
    def ollama_available(self) -> bool:
        return self.is_connected and self.proxy_info.get("ollama_status", {}).get("available", False)
    
    @property
    def available_models(self) -> list:
        return self.proxy_info.get("ollama_status", {}).get("models", [])
    
    async def register_proxy(self, websocket: WebSocket, info: dict):
        """Register a new proxy connection"""
        async with self._lock:
            # Close existing connection if any
            if self.proxy_connection:
                try:
                    await self.proxy_connection.close()
                except:
                    pass
            
            self.proxy_connection = websocket
            self.proxy_info = info
            logger.info(f"Ollama proxy registered: {info}")
    
    async def unregister_proxy(self, websocket: WebSocket):
        """Unregister a proxy connection"""
        async with self._lock:
            if self.proxy_connection == websocket:
                self.proxy_connection = None
                self.proxy_info = {}
                logger.info("Ollama proxy disconnected")
                
                # Cancel any pending requests
                for request_id, future in self.pending_requests.items():
                    if not future.done():
                        future.set_exception(Exception("Proxy disconnected"))
                self.pending_requests.clear()
    
    async def send_request(self, request_type: str, data: dict, timeout: float = 120.0) -> dict:
        """Send a request to the proxy and wait for response"""
        if not self.is_connected:
            return {"success": False, "error": "No proxy connected"}
        
        # Generate request ID
        self.request_counter += 1
        request_id = f"req_{self.request_counter}_{datetime.now().timestamp()}"
        
        # Create future for response
        future = asyncio.get_event_loop().create_future()
        self.pending_requests[request_id] = future
        
        try:
            # Send request
            message = {
                "type": request_type,
                "request_id": request_id,
                **data
            }
            await self.proxy_connection.send_text(json.dumps(message))
            
            # Wait for response with timeout
            response = await asyncio.wait_for(future, timeout=timeout)
            return response
            
        except asyncio.TimeoutError:
            return {"success": False, "error": "Request timed out"}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            self.pending_requests.pop(request_id, None)
    
    def handle_response(self, data: dict):
        """Handle a response from the proxy"""
        request_id = data.get("request_id")
        if request_id and request_id in self.pending_requests:
            future = self.pending_requests[request_id]
            if not future.done():
                future.set_result(data)
    
    async def check_ollama(self) -> dict:
        """Check Ollama status through the proxy"""
        if not self.is_connected:
            return {"available": False, "error": "No proxy connected"}
        
        result = await self.send_request("ollama_check", {}, timeout=10.0)
        if result.get("type") == "ollama_status":
            return {"available": result.get("available", False), "models": result.get("models", [])}
        return {"available": False, "error": result.get("error", "Unknown error")}
    
    async def chat(self, model: str, messages: list, options: dict = None) -> dict:
        """Send a chat request to Ollama through the proxy"""
        if not self.is_connected:
            return {"success": False, "error": "No proxy connected"}
        
        request = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": options or {}
        }
        
        result = await self.send_request("ollama_chat", {"request": request}, timeout=120.0)
        
        if result.get("success"):
            ollama_response = result.get("response", {})
            content = ollama_response.get("message", {}).get("content", "")
            return {"success": True, "content": content, "full_response": ollama_response}
        else:
            return {"success": False, "error": result.get("error", "Unknown error")}
    
    def get_status(self) -> dict:
        """Get current proxy status"""
        return {
            "connected": self.is_connected,
            "ollama_available": self.ollama_available,
            "models": self.available_models,
            "proxy_info": self.proxy_info,
            "pending_requests": len(self.pending_requests)
        }


# Global instance
ollama_proxy_manager = OllamaProxyManager()


async def handle_ollama_proxy_websocket(websocket: WebSocket):
    """WebSocket handler for Ollama proxy connections"""
    await websocket.accept()
    logger.info("Ollama proxy WebSocket connection accepted")
    
    try:
        async for message in websocket.iter_text():
            try:
                data = json.loads(message)
                msg_type = data.get("type", "")
                
                if msg_type == "register":
                    await ollama_proxy_manager.register_proxy(websocket, data)
                    await websocket.send_text(json.dumps({
                        "type": "registered",
                        "message": "Proxy registered successfully"
                    }))
                
                elif msg_type == "pong":
                    # Heartbeat response, ignore
                    pass
                
                elif msg_type in ["ollama_status", "ollama_response"]:
                    # Response to a request we sent
                    ollama_proxy_manager.handle_response(data)
                
                else:
                    logger.warning(f"Unknown message type from proxy: {msg_type}")
                    
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON from proxy: {e}")
                
    except WebSocketDisconnect:
        logger.info("Ollama proxy WebSocket disconnected")
    except Exception as e:
        logger.error(f"Ollama proxy WebSocket error: {e}")
    finally:
        await ollama_proxy_manager.unregister_proxy(websocket)
