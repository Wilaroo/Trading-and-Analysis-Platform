import asyncio, json, subprocess, sys, logging, time, random
from datetime import datetime
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)
try:
    import httpx
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx"])
    import httpx

CLOUD_URL = "https://pipeline-control.preview.emergentagent.com"
OLLAMA_URL = "http://localhost:11434"

class OllamaProxyHTTP:
    def __init__(self):
        self.session_id = f"proxy_{int(time.time())}_{random.randint(1000000, 9999999)}"
        self.backoff = 5  # Initial backoff in seconds
        self.max_backoff = 60  # Max backoff
        self.rate_limited_until = 0  # Timestamp when rate limit expires
        
    async def check_ollama(self):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f"{OLLAMA_URL}/api/tags")
                if r.status_code == 200:
                    return {"available": True, "models": [m['name'] for m in r.json().get('models', [])]}
        except Exception as e:
            logger.error(f"Ollama check failed: {e}")
        return {"available": False, "models": []}
    
    async def call_ollama(self, request):
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                r = await client.post(f"{OLLAMA_URL}/api/chat", json=request)
                if r.status_code == 200:
                    return {"success": True, "response": r.json()}
                else:
                    return {"success": False, "error": f"Ollama returned {r.status_code}: {r.text[:100]}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def register(self):
        # Check if we're rate limited
        if time.time() < self.rate_limited_until:
            wait_time = int(self.rate_limited_until - time.time())
            logger.warning(f"Rate limited, waiting {wait_time}s...")
            return False
            
        try:
            status = await self.check_ollama()
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    f"{CLOUD_URL}/api/ollama-proxy/register", 
                    json={
                        "session_id": self.session_id, 
                        "ollama_status": status, 
                        "timestamp": datetime.now().isoformat()
                    }
                )
                if r.status_code == 200:
                    logger.info(f"REGISTERED! Session: {self.session_id[:20]}... Models: {status['models']}")
                    self.backoff = 5  # Reset backoff on success
                    return True
                elif r.status_code == 429:
                    # Rate limited - apply exponential backoff
                    self.rate_limited_until = time.time() + self.backoff
                    logger.warning(f"Rate limited (429). Waiting {self.backoff}s before retry...")
                    self.backoff = min(self.backoff * 2, self.max_backoff)
                    return False
                else:
                    logger.error(f"Registration failed: {r.status_code} - {r.text[:100]}")
        except httpx.ReadTimeout:
            logger.error("Registration timeout - server too slow")
        except httpx.ConnectError:
            logger.error("Registration failed - cannot connect to cloud")
        except Exception as e:
            logger.error(f"Registration error: {type(e).__name__}: {e}")
        return False
    
    async def poll(self):
        # Check if we're rate limited
        if time.time() < self.rate_limited_until:
            return []
            
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.get(
                    f"{CLOUD_URL}/api/ollama-proxy/poll", 
                    params={"session_id": self.session_id}
                )
                if r.status_code == 200:
                    self.backoff = 5  # Reset backoff on success
                    return r.json().get("requests", [])
                elif r.status_code == 429:
                    # Rate limited
                    self.rate_limited_until = time.time() + self.backoff
                    logger.warning(f"Poll rate limited. Waiting {self.backoff}s...")
                    self.backoff = min(self.backoff * 1.5, self.max_backoff)
                elif r.status_code == 403:
                    # Session expired or invalid - re-register
                    logger.warning("Session invalid (403). Re-registering...")
                    self.rate_limited_until = time.time() + 5
                    await self.register()
        except httpx.ReadTimeout:
            pass  # Normal timeout, just retry
        except Exception as e:
            logger.debug(f"Poll error: {e}")
        return []
    
    async def respond(self, rid, result):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                await client.post(
                    f"{CLOUD_URL}/api/ollama-proxy/response", 
                    json={
                        "session_id": self.session_id, 
                        "request_id": rid, 
                        "result": result
                    }
                )
        except Exception as e:
            logger.error(f"Response error: {e}")
    
    async def heartbeat(self):
        while True:
            # Check if we're rate limited
            if time.time() < self.rate_limited_until:
                await asyncio.sleep(5)
                continue
                
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.post(
                        f"{CLOUD_URL}/api/ollama-proxy/heartbeat", 
                        json={
                            "session_id": self.session_id, 
                            "ollama_status": await self.check_ollama()
                        }
                    )
                    if r.status_code == 429:
                        self.rate_limited_until = time.time() + 15
                        logger.debug("Heartbeat rate limited")
            except:
                pass
            await asyncio.sleep(15)  # Increased from 10s to 15s
    
    async def run(self):
        # Registration with exponential backoff
        attempt = 0
        while True:
            attempt += 1
            if await self.register():
                break
            wait_time = min(5 * attempt, 30)  # Max 30 second wait
            logger.info(f"Retrying registration in {wait_time}s... (attempt {attempt})")
            await asyncio.sleep(wait_time)
        
        asyncio.create_task(self.heartbeat())
        logger.info("READY - Waiting for AI requests...")
        
        while True:
            for req in await self.poll():
                rid = req.get("request_id")
                logger.info(f">>> Processing: {rid}")
                result = await self.call_ollama(req.get("request", {}))
                logger.info(f"<<< Done: {rid} {'OK' if result.get('success') else 'FAILED'}")
                await self.respond(rid, result)
            await asyncio.sleep(5)  # Increased from 3s to 5s for stability

async def main():
    print("=" * 50)
    print("  OLLAMA PROXY (Stable HTTP)")
    print("=" * 50)
    print(f"  Cloud: {CLOUD_URL}")
    print("  Keep this window open!")
    print("=" * 50)
    await OllamaProxyHTTP().run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
