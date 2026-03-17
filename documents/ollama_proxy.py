#!/usr/bin/env python3
"""
Ollama Local AI Proxy
=====================
Connects to Emergent cloud backend via WebSocket (outbound connection).
Receives Ollama requests, calls local Ollama, returns responses.

No ngrok needed - this initiates the connection outbound.

Usage:
    python ollama_proxy.py --cloud-url https://pipeline-control.preview.emergentagent.com
"""

import asyncio
import json
import argparse
import subprocess
import sys
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Try to import required packages
try:
    import websockets
    import httpx
except ImportError:
    logger.error("Missing dependencies. Installing...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets", "httpx"])
    import websockets
    import httpx


class OllamaProxy:
    def __init__(self, cloud_url: str, ollama_url: str = "http://localhost:11434"):
        self.cloud_url = cloud_url.rstrip('/')
        self.ollama_url = ollama_url
        self.ws = None
        self.connected = False
        self.reconnect_delay = 5
        self.max_reconnect_delay = 60
        
    async def check_ollama(self) -> dict:
        """Check if local Ollama is running and get model info"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.ollama_url}/api/tags")
                if response.status_code == 200:
                    data = response.json()
                    models = [m['name'] for m in data.get('models', [])]
                    return {"available": True, "models": models}
        except Exception as e:
            logger.error(f"Ollama check failed: {e}")
        return {"available": False, "models": []}
    
    async def call_ollama(self, request: dict) -> dict:
        """Call local Ollama with the given request"""
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.ollama_url}/api/chat",
                    json=request,
                    headers={"Content-Type": "application/json"}
                )
                if response.status_code == 200:
                    return {"success": True, "response": response.json()}
                else:
                    return {"success": False, "error": f"Ollama returned {response.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def handle_message(self, message: str) -> str:
        """Handle incoming WebSocket message"""
        try:
            data = json.loads(message)
            msg_type = data.get("type", "")
            
            if msg_type == "ping":
                return json.dumps({"type": "pong", "timestamp": datetime.now().isoformat()})
            
            elif msg_type == "ollama_check":
                result = await self.check_ollama()
                return json.dumps({"type": "ollama_status", **result})
            
            elif msg_type == "ollama_chat":
                request = data.get("request", {})
                logger.info(f"Processing Ollama request: model={request.get('model', 'unknown')}")
                result = await self.call_ollama(request)
                if result["success"]:
                    logger.info("Ollama request completed successfully")
                else:
                    logger.warning(f"Ollama request failed: {result.get('error')}")
                return json.dumps({"type": "ollama_response", "request_id": data.get("request_id"), **result})
            
            else:
                return json.dumps({"type": "error", "error": f"Unknown message type: {msg_type}"})
                
        except Exception as e:
            logger.error(f"Error handling message: {e}")
            return json.dumps({"type": "error", "error": str(e)})
    
    async def connect(self):
        """Connect to cloud backend WebSocket"""
        ws_url = self.cloud_url.replace("https://", "wss://").replace("http://", "ws://")
        ws_url = f"{ws_url}/api/ws/ollama-proxy"
        
        while True:
            try:
                logger.info(f"Connecting to {ws_url}...")
                
                # Try different websockets API versions for compatibility
                try:
                    # Newer websockets (11.x+)
                    ws = await websockets.connect(
                        ws_url,
                        additional_headers={"X-Proxy-Type": "ollama"},
                        ping_interval=30,
                        ping_timeout=10
                    )
                except TypeError:
                    try:
                        # Older websockets (10.x)
                        ws = await websockets.connect(
                            ws_url,
                            extra_headers={"X-Proxy-Type": "ollama"},
                            ping_interval=30,
                            ping_timeout=10
                        )
                    except TypeError:
                        # Even older or different API - no custom headers
                        ws = await websockets.connect(
                            ws_url,
                            ping_interval=30,
                            ping_timeout=10
                        )
                
                async with ws:
                    self.ws = ws
                    self.connected = True
                    self.reconnect_delay = 5  # Reset on successful connection
                    
                    # Check local Ollama
                    ollama_status = await self.check_ollama()
                    if ollama_status["available"]:
                        logger.info(f"Connected! Local Ollama models: {ollama_status['models']}")
                    else:
                        logger.warning("Connected but local Ollama is not running!")
                    
                    # Send registration message
                    await ws.send(json.dumps({
                        "type": "register",
                        "proxy_type": "ollama",
                        "ollama_status": ollama_status,
                        "timestamp": datetime.now().isoformat()
                    }))
                    
                    # Listen for messages
                    async for message in ws:
                        response = await self.handle_message(message)
                        await ws.send(response)
                        
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"Connection closed: {e}")
            except Exception as e:
                logger.error(f"Connection error: {e}")
            
            self.connected = False
            logger.info(f"Reconnecting in {self.reconnect_delay} seconds...")
            await asyncio.sleep(self.reconnect_delay)
            self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)


def detect_gpu_vram():
    """Detect GPU and available VRAM"""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            gpus = []
            for line in lines:
                parts = line.split(', ')
                if len(parts) >= 2:
                    gpus.append({
                        "name": parts[0].strip(),
                        "vram_mb": int(parts[1].strip())
                    })
            return gpus
    except Exception as e:
        logger.warning(f"Could not detect GPU: {e}")
    return []


def get_recommended_model(vram_mb: int) -> str:
    """Get recommended Ollama model based on VRAM"""
    if vram_mb >= 8000:
        return "qwen2.5:14b"  # 8GB+ VRAM
    elif vram_mb >= 6000:
        return "qwen2.5:7b"   # 6-8GB VRAM
    elif vram_mb >= 4000:
        return "qwen2.5:7b"   # 4-6GB VRAM (will use CPU offload)
    elif vram_mb >= 2000:
        return "qwen2.5:3b"   # 2-4GB VRAM
    else:
        return "qwen2.5:1.5b" # <2GB VRAM


async def main():
    parser = argparse.ArgumentParser(description="Ollama Local AI Proxy")
    parser.add_argument("--cloud-url", required=True, help="Cloud backend URL")
    parser.add_argument("--ollama-url", default="http://localhost:11434", help="Local Ollama URL")
    parser.add_argument("--detect-gpu", action="store_true", help="Detect GPU and show recommended model")
    args = parser.parse_args()
    
    # GPU detection
    if args.detect_gpu:
        gpus = detect_gpu_vram()
        if gpus:
            for gpu in gpus:
                model = get_recommended_model(gpu["vram_mb"])
                print(f"GPU: {gpu['name']}")
                print(f"VRAM: {gpu['vram_mb']} MB")
                print(f"Recommended Model: {model}")
        else:
            print("No GPU detected, recommend: qwen2.5:3b (CPU mode)")
        return
    
    print("=" * 60)
    print("  Ollama Local AI Proxy")
    print("=" * 60)
    print(f"  Cloud URL: {args.cloud_url}")
    print(f"  Ollama URL: {args.ollama_url}")
    
    # Show GPU info
    gpus = detect_gpu_vram()
    if gpus:
        for gpu in gpus:
            print(f"  GPU: {gpu['name']} ({gpu['vram_mb']} MB)")
            print(f"  Recommended Model: {get_recommended_model(gpu['vram_mb'])}")
    
    print("=" * 60)
    print("  Press Ctrl+C to stop")
    print("=" * 60)
    
    proxy = OllamaProxy(args.cloud_url, args.ollama_url)
    await proxy.connect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProxy stopped.")
