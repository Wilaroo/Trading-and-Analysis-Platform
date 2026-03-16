#!/usr/bin/env python3
"""
Ollama Local AI Proxy (HTTP Polling Version)
============================================
Uses HTTP long-polling instead of WebSocket for better compatibility.
Polls the cloud for pending requests, processes them with local Ollama, returns results.
"""

import asyncio
import json
import argparse
import subprocess
import sys
import logging
import time
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)

try:
    import httpx
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx"])
    import httpx


class OllamaProxyHTTP:
    def __init__(self, cloud_url: str, ollama_url: str = "http://localhost:11434"):
        self.cloud_url = cloud_url.rstrip('/')
        self.ollama_url = ollama_url
        self.session_id = f"proxy_{int(time.time())}_{id(self)}"
        self.connected = False
        self.poll_interval = 1.0  # Poll every 1 second
        
    async def check_ollama(self) -> dict:
        """Check if local Ollama is running"""
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
            async with httpx.AsyncClient(timeout=180.0) as client:
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
    
    async def register(self) -> bool:
        """Register this proxy with the cloud"""
        try:
            ollama_status = await self.check_ollama()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.cloud_url}/api/ollama-proxy/register",
                    json={
                        "session_id": self.session_id,
                        "ollama_status": ollama_status,
                        "timestamp": datetime.now().isoformat()
                    }
                )
                if response.status_code == 200:
                    self.connected = True
                    logger.info(f"Registered with cloud! Models: {ollama_status['models']}")
                    return True
                else:
                    logger.error(f"Registration failed: {response.status_code}")
        except Exception as e:
            logger.error(f"Registration error: {e}")
        return False
    
    async def poll_for_requests(self) -> list:
        """Poll the cloud for pending Ollama requests"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.cloud_url}/api/ollama-proxy/poll",
                    params={"session_id": self.session_id}
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get("requests", [])
        except httpx.TimeoutException:
            pass  # Long poll timeout is normal
        except Exception as e:
            logger.error(f"Poll error: {e}")
        return []
    
    async def submit_response(self, request_id: str, result: dict) -> bool:
        """Submit a response back to the cloud"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.cloud_url}/api/ollama-proxy/response",
                    json={
                        "session_id": self.session_id,
                        "request_id": request_id,
                        "result": result
                    }
                )
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Response submit error: {e}")
        return False
    
    async def heartbeat(self):
        """Send periodic heartbeats"""
        while True:
            try:
                ollama_status = await self.check_ollama()
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(
                        f"{self.cloud_url}/api/ollama-proxy/heartbeat",
                        json={
                            "session_id": self.session_id,
                            "ollama_status": ollama_status
                        }
                    )
            except Exception as e:
                logger.debug(f"Heartbeat error: {e}")
            await asyncio.sleep(15)
    
    async def run(self):
        """Main run loop"""
        # Register with cloud
        while not await self.register():
            logger.info("Retrying registration in 5 seconds...")
            await asyncio.sleep(5)
        
        # Start heartbeat task
        asyncio.create_task(self.heartbeat())
        
        logger.info("Polling for requests...")
        
        # Main poll loop
        while True:
            try:
                requests = await self.poll_for_requests()
                
                for req in requests:
                    request_id = req.get("request_id")
                    ollama_request = req.get("request", {})
                    
                    logger.info(f"Processing request {request_id}: model={ollama_request.get('model', 'unknown')}")
                    
                    # Call local Ollama
                    result = await self.call_ollama(ollama_request)
                    
                    if result.get("success"):
                        content = result.get("response", {}).get("message", {}).get("content", "")
                        logger.info(f"Request {request_id} completed ({len(content)} chars)")
                    else:
                        logger.warning(f"Request {request_id} failed: {result.get('error')}")
                    
                    # Submit response
                    await self.submit_response(request_id, result)
                
                # Brief pause between polls
                await asyncio.sleep(self.poll_interval)
                
            except Exception as e:
                logger.error(f"Poll loop error: {e}")
                await asyncio.sleep(5)


def detect_gpu():
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return [{"name": p[0].strip(), "vram_mb": int(p[1].strip())} 
                    for line in result.stdout.strip().split('\n') 
                    for p in [line.split(', ')] if len(p) >= 2]
    except:
        pass
    return []


async def main():
    # Default cloud URL - update this if it changes
    DEFAULT_CLOUD_URL = "https://dual-stream-chat-1.preview.emergentagent.com"
    
    parser = argparse.ArgumentParser(description="Ollama Local AI Proxy (HTTP)")
    parser.add_argument("--cloud-url", default=DEFAULT_CLOUD_URL, help="Cloud backend URL")
    parser.add_argument("--ollama-url", default="http://localhost:11434", help="Local Ollama URL")
    args = parser.parse_args()
    
    print("=" * 55)
    print("  Ollama Local AI Proxy (HTTP Polling)")
    print("=" * 55)
    print(f"  Cloud URL: {args.cloud_url}")
    print(f"  Ollama URL: {args.ollama_url}")
    
    for gpu in detect_gpu():
        print(f"  GPU: {gpu['name']} ({gpu['vram_mb']} MB)")
    
    print("=" * 55)
    print("  Press Ctrl+C to stop")
    print("=" * 55)
    
    proxy = OllamaProxyHTTP(args.cloud_url, args.ollama_url)
    await proxy.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProxy stopped.")
