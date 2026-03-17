import asyncio, json, subprocess, sys, logging, time
from datetime import datetime
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)
try:
    import httpx
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx"])
    import httpx
CLOUD_URL = "https://trading-coverage.preview.emergentagent.com"
OLLAMA_URL = "http://localhost:11434"
class OllamaProxyHTTP:
    def __init__(self):
        self.session_id = f"proxy_{int(time.time())}_{id(self)}"
    async def check_ollama(self):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
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
        except Exception as e:
            return {"success": False, "error": str(e)}
        return {"success": False, "error": "Failed"}
    async def register(self):
        try:
            status = await self.check_ollama()
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(f"{CLOUD_URL}/api/ollama-proxy/register", json={"session_id": self.session_id, "ollama_status": status, "timestamp": datetime.now().isoformat()})
                if r.status_code == 200:
                    logger.info(f"REGISTERED! Models: {status['models']}")
                    return True
        except Exception as e:
            logger.error(f"Registration error: {e}")
        return False
    async def poll(self):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.get(f"{CLOUD_URL}/api/ollama-proxy/poll", params={"session_id": self.session_id})
                if r.status_code == 200:
                    return r.json().get("requests", [])
        except:
            pass
        return []
    async def respond(self, rid, result):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(f"{CLOUD_URL}/api/ollama-proxy/response", json={"session_id": self.session_id, "request_id": rid, "result": result})
        except:
            pass
    async def heartbeat(self):
        while True:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(f"{CLOUD_URL}/api/ollama-proxy/heartbeat", json={"session_id": self.session_id, "ollama_status": await self.check_ollama()})
            except:
                pass
            await asyncio.sleep(10)
    async def run(self):
        while not await self.register():
            await asyncio.sleep(5)
        asyncio.create_task(self.heartbeat())
        logger.info("READY - Waiting for AI requests...")
        while True:
            for req in await self.poll():
                rid = req.get("request_id")
                logger.info(f">>> Processing: {rid}")
                result = await self.call_ollama(req.get("request", {}))
                logger.info(f"<<< Done: {rid} {'OK' if result.get('success') else 'FAILED'}")
                await self.respond(rid, result)
            await asyncio.sleep(1)
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
