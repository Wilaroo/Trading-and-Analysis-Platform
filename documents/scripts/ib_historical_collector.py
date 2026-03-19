#!/usr/bin/env python3
"""
IB Historical Data Collector
============================
Dedicated script for collecting historical data from IB Gateway.
Runs separately from the trading pusher with a different client ID.

Usage:
    python ib_historical_collector.py --url http://localhost:8001

Features:
    - Connects to IB Gateway with client_id=11 (separate from trading pusher)
    - Fetches pending requests from queue (fill-gaps populates the queue)
    - Respects IB pacing rules (60 requests per 10 min)
    - Handles rate limiting gracefully
    - Auto-reconnects on connection loss
    - Can run alongside ib_data_pusher.py without conflicts
"""

import argparse
import time
import logging
import requests
from datetime import datetime, timezone
from typing import List, Dict, Optional
from collections import deque

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


class APIClient:
    """Simple API client with retry logic for backend communication."""
    
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'IB-Historical-Collector/2.0',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })
    
    def get(self, endpoint: str, timeout: int = 30) -> Optional[dict]:
        """GET request with retry logic."""
        url = f"{self.base_url}{endpoint}"
        for attempt in range(3):
            try:
                resp = self.session.get(url, timeout=timeout)
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 404:
                    return None
                else:
                    logger.warning(f"GET {endpoint} returned {resp.status_code}")
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout on GET {endpoint} (attempt {attempt + 1}/3)")
                time.sleep(2 ** attempt)
            except Exception as e:
                logger.error(f"Error on GET {endpoint}: {e}")
                time.sleep(2 ** attempt)
        return None
    
    def post(self, endpoint: str, data: dict, timeout: int = 15) -> Optional[dict]:
        """POST request with retry logic."""
        url = f"{self.base_url}{endpoint}"
        for attempt in range(2):
            try:
                resp = self.session.post(url, json=data, timeout=timeout)
                if resp.status_code in [200, 201]:
                    return resp.json()
                elif resp.status_code == 409:
                    return {"success": True, "status": "already_processed"}
                else:
                    logger.warning(f"POST {endpoint} returned {resp.status_code}")
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout on POST {endpoint} (attempt {attempt + 1}/2)")
                time.sleep(2 ** attempt)
            except Exception as e:
                logger.error(f"Error on POST {endpoint}: {e}")
                time.sleep(1)
        return None
    
    def optimize_indexes(self) -> bool:
        """Call the index optimization endpoint on startup."""
        logger.info("Optimizing MongoDB indexes for best performance...")
        result = self.post("/api/ib/historical-data/optimize-indexes", {}, timeout=60)
        if result and result.get("success"):
            created = result.get("indexes_created", [])
            verified = result.get("indexes_verified", [])
            logger.info(f"  Indexes created: {len(created)}, verified: {len(verified)}")
            return True
        else:
            logger.warning("  Could not optimize indexes (non-critical)")
            return False


class IBPacingManager:
    """
    Manages IB API pacing to stay within rate limits.
    
    IB Rules:
    - Max 60 historical data requests per 10 minutes
    - No identical requests within 15 seconds
    - Pacing violations result in temporary blocks
    """
    
    def __init__(self, max_requests: int = 55, window_seconds: int = 600):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.request_times = deque()
        self.recent_requests = {}
    
    def can_make_request(self, symbol: str = None, bar_size: str = None) -> bool:
        """Check if we can make a request without violating pacing."""
        now = time.time()
        
        while self.request_times and self.request_times[0] < now - self.window_seconds:
            self.request_times.popleft()
        
        if len(self.request_times) >= self.max_requests:
            return False
        
        if symbol and bar_size:
            key = (symbol, bar_size)
            if key in self.recent_requests:
                if now - self.recent_requests[key] < 15:
                    return False
        
        return True
    
    def record_request(self, symbol: str = None, bar_size: str = None):
        """Record that a request was made."""
        now = time.time()
        self.request_times.append(now)
        if symbol and bar_size:
            self.recent_requests[(symbol, bar_size)] = now
    
    def wait_time(self) -> float:
        """How long to wait before next request is allowed."""
        if not self.request_times:
            return 0
        
        now = time.time()
        oldest = self.request_times[0]
        wait = (oldest + self.window_seconds) - now
        return max(0, wait)
    
    def requests_remaining(self) -> int:
        """How many requests remaining in current window."""
        now = time.time()
        while self.request_times and self.request_times[0] < now - self.window_seconds:
            self.request_times.popleft()
        return self.max_requests - len(self.request_times)


class IBHistoricalCollector:
    """
    Dedicated historical data collector for IB Gateway.
    """
    
    def __init__(self, backend_url: str, ib_host: str = "127.0.0.1", 
                 ib_port: int = 4002, client_id: int = 11):
        self.backend_url = backend_url
        self.ib_host = ib_host
        self.ib_port = ib_port
        self.client_id = client_id
        
        self.api = APIClient(backend_url)
        self.pacing = IBPacingManager()
        self.ib = None
        self.running = False
        
        self.stats = {
            "started_at": None,
            "requests_completed": 0,
            "requests_failed": 0,
            "bars_collected": 0,
            "pacing_waits": 0
        }
    
    def connect(self, max_retries: int = 5) -> bool:
        """Connect to IB Gateway with retry logic for overnight resilience."""
        from ib_insync import IB
        
        for attempt in range(max_retries):
            try:
                if self.ib and self.ib.isConnected():
                    return True
                    
                self.ib = IB()
                
                logger.info(f"Connecting to IB Gateway at {self.ib_host}:{self.ib_port} (client_id={self.client_id})...")
                self.ib.connect(self.ib_host, self.ib_port, clientId=self.client_id)
                
                logger.info("Connected to IB Gateway!")
                logger.info(f"  Accounts: {self.ib.managedAccounts()}")
                return True
                
            except Exception as e:
                logger.error(f"Failed to connect to IB Gateway (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    wait_time = min(30 * (attempt + 1), 120)
                    logger.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
        
        return False
    
    def ensure_connected(self) -> bool:
        """Ensure IB Gateway connection is active, reconnect if needed."""
        if self.ib and self.ib.isConnected():
            return True
        
        logger.warning("IB Gateway connection lost - attempting to reconnect...")
        return self.connect(max_retries=10)
    
    def disconnect(self):
        """Disconnect from IB Gateway."""
        if self.ib and self.ib.isConnected():
            self.ib.disconnect()
            logger.info("Disconnected from IB Gateway")
    
    def fetch_pending_requests(self, limit: int = 10) -> List[dict]:
        """Fetch pending historical data requests from backend."""
        result = self.api.get(f"/api/ib/historical-data/pending?limit={limit}", timeout=15)
        if result:
            return result.get("requests", [])
        return []
    
    def claim_request(self, request_id: str) -> bool:
        """Claim a request to prevent duplicate processing."""
        result = self.api.post(f"/api/ib/historical-data/claim/{request_id}", {}, timeout=10)
        return result is not None
    
    def report_result(self, result: dict) -> bool:
        """Report collection result to backend (single result)."""
        resp = self.api.post("/api/ib/historical-data/result", result, timeout=30)
        return resp is not None
    
    def report_batch_results(self, results: List[dict]) -> dict:
        """Report multiple collection results in a single call."""
        if not results:
            return {"processed": 0, "bars_stored": 0}
        
        resp = self.api.post("/api/ib/historical-data/batch-result", {"results": results}, timeout=60)
        if resp:
            return {
                "processed": resp.get("processed", len(results)),
                "bars_stored": resp.get("bars_stored", 0)
            }
        return {"processed": 0, "bars_stored": 0}
    
    def fetch_historical_data(self, request: dict) -> dict:
        """Fetch historical data from IB for a single request."""
        from ib_insync import Stock
        
        request_id = request.get("request_id")
        symbol = request.get("symbol")
        bar_size = request.get("bar_size", "1 day")
        duration = request.get("duration", "1 Y")
        
        result = {
            "request_id": request_id,
            "symbol": symbol,
            "bar_size": bar_size,
            "duration": duration,
            "success": False,
            "status": "error",
            "data": [],
            "bar_count": 0,
            "error": None
        }
        
        try:
            if not self.pacing.can_make_request(symbol, bar_size):
                wait = self.pacing.wait_time()
                if wait > 0:
                    logger.info(f"Pacing: waiting {wait:.1f}s ({self.pacing.requests_remaining()} requests remaining)")
                    self.stats["pacing_waits"] += 1
                    time.sleep(wait + 1)
            
            contract = Stock(symbol, "SMART", "USD")
            try:
                self.ib.qualifyContracts(contract)
            except Exception as e:
                result["success"] = True
                result["status"] = "no_data"
                result["error"] = f"Symbol not available: {e}"
                return result
            
            self.pacing.record_request(symbol, bar_size)
            
            bars = self.ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow="TRADES",
                useRTH=True
            )
            
            self.ib.sleep(0.5)
            
            bar_data = []
            for bar in bars:
                bar_data.append({
                    "date": bar.date.isoformat() if hasattr(bar.date, 'isoformat') else str(bar.date),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume
                })
            
            result["success"] = True
            result["status"] = "success" if bar_data else "no_data"
            result["data"] = bar_data
            result["bar_count"] = len(bar_data)
            
            self.stats["bars_collected"] += len(bar_data)
            
        except Exception as e:
            error_str = str(e)
            
            if "pacing" in error_str.lower():
                logger.warning(f"IB PACING violation for {symbol} - waiting 60s")
                result["status"] = "rate_limited"
                result["error"] = "IB pacing violation"
                time.sleep(60)
            elif "no data" in error_str.lower() or "no historical data" in error_str.lower():
                result["success"] = True
                result["status"] = "no_data"
                result["error"] = error_str
            else:
                result["status"] = "error"
                result["error"] = error_str
        
        return result
    
    def run(self, batch_size: int = 5, continuous: bool = True, min_delay: float = 1.0):
        """Main collection loop."""
        self.min_delay = min_delay
        
        if not self.connect():
            return
        
        self.running = True
        self.stats["started_at"] = datetime.now(timezone.utc)
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("  IB Historical Data Collector v2.0")
        logger.info("=" * 60)
        logger.info(f"  Backend URL: {self.backend_url}")
        logger.info(f"  IB Gateway: {self.ib_host}:{self.ib_port}")
        logger.info(f"  Client ID: {self.client_id}")
        logger.info(f"  Batch Size: {batch_size}")
        logger.info(f"  Mode: {'Continuous' if continuous else 'Single Run'}")
        logger.info(f"  Min Delay: {min_delay}s between requests")
        logger.info(f"  Pacing: Max {self.pacing.max_requests} requests per 10 min")
        logger.info("=" * 60)
        logger.info("")
        
        self.api.optimize_indexes()
        logger.info("")
        
        cycle = 0
        empty_cycles = 0
        
        try:
            while self.running:
                cycle += 1
                
                requests = self.fetch_pending_requests(batch_size)
                
                if not requests:
                    empty_cycles += 1
                    if not continuous:
                        logger.info("No pending requests. Exiting.")
                        break
                    
                    if empty_cycles >= 3:
                        logger.info("Queue empty. Waiting 60s before checking again...")
                        time.sleep(60)
                        empty_cycles = 0
                    else:
                        time.sleep(10)
                    continue
                
                empty_cycles = 0
                logger.info(f"[Cycle {cycle}] Processing {len(requests)} requests...")
                
                batch_results = []
                
                for req in requests:
                    if not self.running:
                        break
                    
                    if not self.ensure_connected():
                        logger.error("Cannot reconnect to IB Gateway - pausing for 5 minutes...")
                        time.sleep(300)
                        break
                    
                    request_id = req.get("request_id")
                    symbol = req.get("symbol")
                    bar_size = req.get("bar_size")
                    
                    if not self.claim_request(request_id):
                        logger.debug(f"  {symbol} ({bar_size}): Already claimed, skipping")
                        continue
                    
                    result = self.fetch_historical_data(req)
                    batch_results.append(result)
                    
                    if result["status"] == "success":
                        self.stats["requests_completed"] += 1
                        logger.info(f"  {symbol} ({bar_size}): {result['bar_count']} bars")
                    elif result["status"] == "no_data":
                        self.stats["requests_completed"] += 1
                        logger.info(f"  {symbol} ({bar_size}): No data available")
                    else:
                        self.stats["requests_failed"] += 1
                        logger.warning(f"  {symbol} ({bar_size}): {result['status']} - {result.get('error', 'Unknown error')}")
                    
                    time.sleep(self.min_delay)
                
                if batch_results:
                    report_result = self.report_batch_results(batch_results)
                    logger.info(f"  Batch reported: {report_result['processed']} results, {report_result['bars_stored']} bars stored to DB")
                
                elapsed = (datetime.now(timezone.utc) - self.stats["started_at"]).total_seconds() / 60
                rate = self.stats["requests_completed"] / elapsed if elapsed > 0 else 0
                
                try:
                    queue_data = self.api.get('/api/ib-collector/queue-progress')
                    if queue_data:
                        q_completed = queue_data.get('completed', 0)
                        q_pending = queue_data.get('pending', 0)
                        q_total = q_completed + q_pending + queue_data.get('claimed', 0) + queue_data.get('failed', 0)
                        q_pct = (q_completed / q_total * 100) if q_total > 0 else 0
                        bar_visual = '█' * int(q_pct/5) + '░' * (20 - int(q_pct/5))
                        logger.info(f"")
                        logger.info(f"╔{'═'*58}╗")
                        logger.info(f"║  QUEUE: {bar_visual} {q_pct:>5.1f}%  ({q_completed:,}/{q_total:,})  ║")
                        logger.info(f"║  Pending: {q_pending:,} | This Session: {self.stats['requests_completed']} done, {self.stats['bars_collected']:,} bars  ║")
                        logger.info(f"╚{'═'*58}╝")
                        logger.info(f"")
                except:
                    logger.info(f"[Stats] Completed: {self.stats['requests_completed']}, "
                               f"Failed: {self.stats['requests_failed']}, "
                               f"Bars: {self.stats['bars_collected']:,}, "
                               f"Rate: {rate:.1f}/min")
                
                if not continuous:
                    break
                
        except KeyboardInterrupt:
            logger.info("\nStopping collector (Ctrl+C)...")
        finally:
            self.running = False
            self.disconnect()
            self._print_final_stats()
    
    def _print_final_stats(self):
        """Print final statistics."""
        if not self.stats["started_at"]:
            return
        
        elapsed = (datetime.now(timezone.utc) - self.stats["started_at"]).total_seconds()
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("  Collection Complete")
        logger.info("=" * 60)
        logger.info(f"  Duration: {elapsed/60:.1f} minutes")
        logger.info(f"  Requests Completed: {self.stats['requests_completed']}")
        logger.info(f"  Requests Failed: {self.stats['requests_failed']}")
        logger.info(f"  Total Bars Collected: {self.stats['bars_collected']:,}")
        logger.info(f"  Pacing Waits: {self.stats['pacing_waits']}")
        if elapsed > 0:
            logger.info(f"  Average Rate: {self.stats['requests_completed'] / (elapsed/60):.1f} requests/min")
        logger.info("=" * 60)
    
    def stop(self):
        """Stop the collector."""
        self.running = False


def main():
    parser = argparse.ArgumentParser(
        description="IB Historical Data Collector v2.0 - Fills gaps in historical data"
    )
    parser.add_argument("--url", default="http://localhost:8001", 
                        help="Backend URL (default: http://localhost:8001)")
    parser.add_argument("--cloud-url", dest="url", help="Alias for --url (backward compatibility)")
    parser.add_argument("--ib-host", default="127.0.0.1", help="IB Gateway host")
    parser.add_argument("--ib-port", type=int, default=4002, help="IB Gateway port")
    parser.add_argument("--client-id", type=int, default=11, 
                        help="IB client ID (default: 11, different from trading pusher)")
    parser.add_argument("--batch-size", type=int, default=3, 
                        help="Number of requests to process per cycle (default: 3)")
    parser.add_argument("--once", action="store_true", 
                        help="Run once and exit (don't loop continuously)")
    parser.add_argument("--slow", action="store_true",
                        help="Slow mode - longer delays for unstable connections")
    parser.add_argument("--fast", action="store_true",
                        help="Fast mode - maximize throughput")
    parser.add_argument("--turbo", action="store_true",
                        help="Turbo mode - aggressive collection (may hit pacing limits)")
    
    args = parser.parse_args()
    
    # Determine speed mode and settings
    if args.turbo:
        speed_mode = "TURBO"
        batch_size = max(args.batch_size, 10)
        pacing_requests = 58
        min_delay = 0.3
    elif args.fast:
        speed_mode = "FAST"
        batch_size = max(args.batch_size, 8)
        pacing_requests = 55
        min_delay = 0.5
    elif args.slow:
        speed_mode = "SLOW"
        batch_size = min(args.batch_size, 2)
        pacing_requests = 50
        min_delay = 2.0
    else:
        speed_mode = "NORMAL"
        batch_size = args.batch_size
        pacing_requests = 55
        min_delay = 1.0
    
    print("=" * 60)
    print("  IB Historical Data Collector v2.0")
    print("  Collects intraday data for 500K+ ADV symbols")
    print("=" * 60)
    print(f"  Backend URL: {args.url}")
    print(f"  IB Gateway: {args.ib_host}:{args.ib_port}")
    print(f"  Client ID: {args.client_id}")
    print(f"  Batch Size: {batch_size}")
    print(f"  Mode: {'Single Run' if args.once else 'Continuous'}")
    print(f"  Speed: {speed_mode}")
    if speed_mode in ["FAST", "TURBO"]:
        print(f"  ⚡ Optimized for dedicated collection - max throughput")
    print("")
    print("  NOTE: Run fill-gaps first to queue the missing data")
    print("        This collector processes whatever is in the queue")
    print("=" * 60)
    
    collector = IBHistoricalCollector(
        backend_url=args.url,
        ib_host=args.ib_host,
        ib_port=args.ib_port,
        client_id=args.client_id
    )
    
    collector.pacing.max_requests = pacing_requests
    
    collector.run(batch_size=batch_size, continuous=not args.once, min_delay=min_delay)


if __name__ == "__main__":
    main()
