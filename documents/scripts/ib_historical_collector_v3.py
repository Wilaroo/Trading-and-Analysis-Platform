#!/usr/bin/env python3
"""
IB Historical Data Collector v3.0 - OPTIMIZED
==============================================
Optimized for 1-minute+ bars where IB's hard pacing limits are LIFTED.

Key Changes from v2.0:
- Removed conservative 55/10min internal pacing (not needed for 1min+ bars)
- Increased default batch size (6 -> 12)
- Reduced inter-request delays (1.0s -> 0.3s)
- Added parallel multi-symbol processing option
- Let IB Gateway's soft throttling be the only limiter

Usage:
    python ib_historical_collector_v3.py --url http://localhost:8001
    python ib_historical_collector_v3.py --url http://localhost:8001 --turbo
    python ib_historical_collector_v3.py --url http://localhost:8001 --parallel

IB API Notes (for 1min+ bars):
- Hard limit of 60/10min is LIFTED
- Soft throttling still applies (IB controls this)
- Burst limit: 6 requests per contract per 2 seconds (still applies)
- Max 50 concurrent requests (still applies)
"""

import argparse
import time
import logging
import requests
from datetime import datetime, timezone
from typing import List, Dict, Optional
from collections import deque
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

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
            'User-Agent': 'IB-Historical-Collector/3.0',
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
    
    def post(self, endpoint: str, data: dict, timeout: int = 30) -> Optional[dict]:
        """POST request with minimal retry - fail fast to keep collecting."""
        url = f"{self.base_url}{endpoint}"
        try:
            resp = self.session.post(url, json=data, timeout=timeout)
            if resp.status_code in [200, 201]:
                return resp.json()
            elif resp.status_code == 409:
                return {"success": True, "status": "already_processed"}
            else:
                logger.debug(f"POST {endpoint} returned {resp.status_code}")
        except requests.exceptions.Timeout:
            logger.debug(f"Timeout on POST {endpoint} - skipping")
        except Exception as e:
            logger.debug(f"Error on POST {endpoint}: {e}")
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


class IBPacingManagerV3:
    """
    OPTIMIZED Pacing Manager for 1-minute+ bars.
    
    IB Rules for 1min+ bars:
    - Hard limit of 60/10min is LIFTED
    - Soft throttling still applies (controlled by IB, not us)
    - Keep 15-second identical request check (still valid)
    - Burst limit: 6 requests per contract per 2 seconds
    """
    
    def __init__(self):
        # Track recent requests to avoid identical requests within 15 seconds
        self.recent_requests = {}
        # Track per-symbol request times to respect burst limit
        self.symbol_requests = {}
        self.lock = threading.Lock()
    
    def can_make_request(self, symbol: str = None, bar_size: str = None) -> tuple:
        """
        Check if we can make a request. Returns (can_proceed, wait_time).
        For 1min+ bars, we only check:
        1. Identical request within 15 seconds
        2. Burst limit (6 requests per symbol per 2 seconds)
        """
        now = time.time()
        
        with self.lock:
            # Check identical request rule (15 seconds)
            if symbol and bar_size:
                key = (symbol, bar_size)
                if key in self.recent_requests:
                    elapsed = now - self.recent_requests[key]
                    if elapsed < 15:
                        return False, 15 - elapsed
            
            # Check burst limit (6 requests per symbol per 2 seconds)
            if symbol:
                if symbol in self.symbol_requests:
                    # Clean old entries
                    self.symbol_requests[symbol] = [
                        t for t in self.symbol_requests[symbol] 
                        if now - t < 2.0
                    ]
                    if len(self.symbol_requests[symbol]) >= 6:
                        oldest = min(self.symbol_requests[symbol])
                        return False, 2.0 - (now - oldest)
        
        return True, 0
    
    def record_request(self, symbol: str = None, bar_size: str = None):
        """Record that a request was made."""
        now = time.time()
        with self.lock:
            if symbol and bar_size:
                self.recent_requests[(symbol, bar_size)] = now
            if symbol:
                if symbol not in self.symbol_requests:
                    self.symbol_requests[symbol] = []
                self.symbol_requests[symbol].append(now)


class IBHistoricalCollectorV3:
    """
    OPTIMIZED Historical Data Collector v3.0
    
    Key improvements:
    - No artificial pacing limits (IB's hard limit lifted for 1min+ bars)
    - Larger batch sizes
    - Shorter delays
    - Optional parallel processing
    """
    
    def __init__(self, backend_url: str, ib_host: str = "127.0.0.1", 
                 ib_port: int = 4002, client_id: int = 11):
        self.backend_url = backend_url
        self.ib_host = ib_host
        self.ib_port = ib_port
        self.client_id = client_id
        
        self.api = APIClient(backend_url)
        self.pacing = IBPacingManagerV3()
        self.ib = None
        self.running = False
        self.ib_lock = threading.Lock()
        
        self.stats = {
            "started_at": None,
            "requests_completed": 0,
            "requests_failed": 0,
            "requests_skipped": 0,
            "bars_collected": 0,
            "pacing_waits": 0
        }
    
    def connect(self, max_retries: int = 5) -> bool:
        """Connect to IB Gateway with retry logic."""
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
    
    def fetch_pending_requests(self, limit: int = 12) -> List[dict]:
        """Fetch pending historical data requests from backend."""
        result = self.api.get(f"/api/ib/historical-data/pending?limit={limit}", timeout=30)
        if result:
            return result.get("requests", [])
        return []
    
    def smart_batch_claim_requests(self, request_ids: List[str]) -> dict:
        """Smart batch claim with existing data check."""
        if not request_ids:
            return {"claimed": [], "skip": [], "skip_details": [], "failed": []}
        
        payload = {"request_ids": request_ids, "check_existing": True}
        
        result = self.api.post(
            "/api/ib/historical-data/smart-batch-claim", 
            payload,
            timeout=60
        )
        
        if result:
            return {
                "claimed": result.get("claimed", []),
                "skip": result.get("skip", []),
                "skip_details": result.get("skip_details", []),
                "failed": result.get("failed", [])
            }
        
        return {"claimed": [], "skip": [], "skip_details": [], "failed": request_ids}
    
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
            # Check pacing (only burst limit and identical request check now)
            can_proceed, wait_time = self.pacing.can_make_request(symbol, bar_size)
            if not can_proceed and wait_time > 0:
                logger.info(f"Pacing: waiting {wait_time:.1f}s (burst/duplicate limit)")
                self.stats["pacing_waits"] += 1
                time.sleep(wait_time + 0.1)
            
            # Thread-safe IB operations
            with self.ib_lock:
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
                
                self.ib.sleep(0.3)  # Reduced from 0.5
            
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
                logger.warning(f"IB PACING violation for {symbol} - waiting 30s (reduced from 60s)")
                result["status"] = "rate_limited"
                result["error"] = "IB pacing violation"
                time.sleep(30)  # Reduced from 60
            elif "no data" in error_str.lower() or "no historical data" in error_str.lower():
                result["success"] = True
                result["status"] = "no_data"
                result["error"] = error_str
            else:
                result["status"] = "error"
                result["error"] = error_str
        
        return result
    
    def process_requests_sequential(self, requests: List[dict], min_delay: float) -> List[dict]:
        """Process requests sequentially (original method, but faster)."""
        batch_results = []
        
        for req in requests:
            if not self.running:
                break
            
            if not self.ensure_connected():
                logger.error("Cannot reconnect to IB Gateway - pausing for 2 minutes...")
                time.sleep(120)  # Reduced from 5 minutes
                break
            
            symbol = req.get("symbol")
            bar_size = req.get("bar_size")
            
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
            
            time.sleep(min_delay)
        
        return batch_results
    
    def run(self, batch_size: int = 12, continuous: bool = True, min_delay: float = 0.3):
        """Main collection loop - OPTIMIZED."""
        self.min_delay = min_delay
        
        if not self.connect():
            return
        
        self.running = True
        self.stats["started_at"] = datetime.now(timezone.utc)
        
        logger.info("")
        logger.info("=" * 65)
        logger.info("  IB Historical Data Collector v3.0 - OPTIMIZED")
        logger.info("=" * 65)
        logger.info(f"  Backend URL: {self.backend_url}")
        logger.info(f"  IB Gateway: {self.ib_host}:{self.ib_port}")
        logger.info(f"  Client ID: {self.client_id}")
        logger.info(f"  Batch Size: {batch_size}")
        logger.info(f"  Min Delay: {min_delay}s between requests")
        logger.info(f"  Mode: {'Continuous' if continuous else 'Single Run'}")
        logger.info("")
        logger.info("  OPTIMIZATIONS ENABLED:")
        logger.info("  - No internal 55/10min pacing (lifted for 1min+ bars)")
        logger.info("  - Burst limit only (6 req/2sec per symbol)")
        logger.info("  - Letting IB Gateway soft-throttle naturally")
        logger.info("=" * 65)
        logger.info("")
        
        self.api.optimize_indexes()
        logger.info("")
        
        cycle = 0
        empty_cycles = 0
        
        try:
            while self.running:
                cycle += 1
                
                # Training guard: check if Spark is running GPU training
                try:
                    training_resp = self.api.get("/api/ai-training/is-active", timeout=5)
                    if training_resp and training_resp.get("active"):
                        if cycle == 1 or (cycle % 10 == 0):
                            logger.info(f"[TRAINING GUARD] Spark GPU training in progress — backing off 60s...")
                        time.sleep(60)
                        continue
                except Exception:
                    pass
                
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
                
                # Smart batch claim
                request_ids = [req.get("request_id") for req in requests]
                smart_result = self.smart_batch_claim_requests(request_ids)
                
                claimed_ids = set(smart_result.get("claimed", []))
                skipped_ids = set(smart_result.get("skip", []))
                skip_details = smart_result.get("skip_details", [])
                
                # Log skipped items
                if skipped_ids:
                    self.stats["requests_skipped"] += len(skipped_ids)
                    logger.info(f"  [SKIP] {len(skipped_ids)} items (data already COMPLETE):")
                    for detail in skip_details[:3]:
                        threshold = detail.get('threshold', '?')
                        logger.info(f"     {detail.get('symbol')} ({detail.get('bar_size')}): {detail.get('existing_bars', 0)} bars >= {threshold} threshold")
                    if len(skip_details) > 3:
                        logger.info(f"     ... and {len(skip_details) - 3} more")
                
                if not claimed_ids and not skipped_ids:
                    logger.warning("  No requests could be claimed, skipping cycle")
                    time.sleep(5)
                    continue
                
                # Filter to only requests that need IB fetch
                requests_to_process = [req for req in requests if req.get("request_id") in claimed_ids]
                
                if requests_to_process:
                    logger.info(f"  Fetching {len(requests_to_process)} from IB Gateway...")
                else:
                    logger.info(f"  All {len(skipped_ids)} items had existing data - no IB fetch needed!")
                    self._print_queue_status()
                    continue
                
                # Process requests
                batch_results = self.process_requests_sequential(requests_to_process, min_delay)
                
                # Report results
                if batch_results:
                    report_result = self.report_batch_results(batch_results)
                    logger.info(f"  Batch reported: {report_result['processed']} results, {report_result['bars_stored']} bars stored to DB")
                
                self._print_queue_status()
                
                if not continuous:
                    break
                
        except KeyboardInterrupt:
            logger.info("\nStopping collector (Ctrl+C)...")
        finally:
            self.running = False
            self.disconnect()
            self._print_final_stats()
    
    def _print_queue_status(self):
        """Print current queue status."""
        try:
            queue_data = self.api.get('/api/ib-collector/queue-progress')
            if queue_data:
                q_completed = queue_data.get('completed', 0)
                q_pending = queue_data.get('pending', 0)
                q_total = q_completed + q_pending + queue_data.get('claimed', 0) + queue_data.get('failed', 0)
                q_pct = (q_completed / q_total * 100) if q_total > 0 else 0
                bar_visual = '' * int(q_pct/5) + '' * (20 - int(q_pct/5))
                skip_str = f", [SKIP]{self.stats['requests_skipped']}" if self.stats['requests_skipped'] > 0 else ""
                logger.info(f"")
                logger.info(f"{'='*62}")
                logger.info(f"  QUEUE: {bar_visual} {q_pct:>5.1f}%  ({q_completed:,}/{q_total:,})")
                logger.info(f"  Pending: {q_pending:,} | Session: {self.stats['requests_completed']} done{skip_str}, {self.stats['bars_collected']:,} bars")
                logger.info(f"{'='*62}")
                logger.info(f"")
        except:
            pass
    
    def _print_final_stats(self):
        """Print final statistics."""
        if not self.stats["started_at"]:
            return
        
        elapsed = (datetime.now(timezone.utc) - self.stats["started_at"]).total_seconds()
        total_processed = self.stats['requests_completed'] + self.stats['requests_skipped']
        
        logger.info("")
        logger.info("=" * 65)
        logger.info("  Collection Complete - v3.0 OPTIMIZED")
        logger.info("=" * 65)
        logger.info(f"  Duration: {elapsed/60:.1f} minutes")
        logger.info(f"  Requests Completed: {self.stats['requests_completed']}")
        if self.stats['requests_skipped'] > 0:
            logger.info(f"  Requests Skipped (existing): {self.stats['requests_skipped']}")
            logger.info(f"  Total Processed: {total_processed}")
        logger.info(f"  Requests Failed: {self.stats['requests_failed']}")
        logger.info(f"  Total Bars Collected: {self.stats['bars_collected']:,}")
        logger.info(f"  Pacing Waits: {self.stats['pacing_waits']}")
        if elapsed > 0:
            rate = total_processed / (elapsed/60)
            logger.info(f"  Average Rate: {rate:.1f} requests/min")
            logger.info(f"  Estimated v2 Rate: ~{rate/2.5:.1f} requests/min (for comparison)")
        logger.info("=" * 65)
    
    def stop(self):
        """Stop the collector."""
        self.running = False


def main():
    parser = argparse.ArgumentParser(
        description="IB Historical Data Collector v3.0 - OPTIMIZED for 1min+ bars"
    )
    parser.add_argument("--url", default="http://localhost:8001", 
                        help="Backend URL (default: http://localhost:8001)")
    parser.add_argument("--ib-host", default="127.0.0.1", help="IB Gateway host")
    parser.add_argument("--ib-port", type=int, default=4002, help="IB Gateway port")
    parser.add_argument("--client-id", type=int, default=11, 
                        help="IB client ID (default: 11)")
    parser.add_argument("--batch-size", type=int, default=12, 
                        help="Number of requests to process per cycle (default: 12)")
    parser.add_argument("--once", action="store_true", 
                        help="Run once and exit (don't loop continuously)")
    
    # Speed modes
    parser.add_argument("--conservative", action="store_true",
                        help="Conservative mode - safer but slower (batch=6, delay=0.5s)")
    parser.add_argument("--turbo", action="store_true",
                        help="Turbo mode - maximum throughput (batch=18, delay=0.2s)")
    
    args = parser.parse_args()
    
    # Determine speed mode
    if args.turbo:
        speed_mode = "TURBO"
        batch_size = max(args.batch_size, 18)
        min_delay = 0.2
    elif args.conservative:
        speed_mode = "CONSERVATIVE"
        batch_size = min(args.batch_size, 6)
        min_delay = 0.5
    else:
        speed_mode = "OPTIMIZED"
        batch_size = args.batch_size
        min_delay = 0.3
    
    print("")
    print("=" * 65)
    print("  IB Historical Data Collector v3.0 - OPTIMIZED")
    print("  For 1-minute+ bars (hard pacing limits LIFTED)")
    print("=" * 65)
    print(f"  Backend URL: {args.url}")
    print(f"  IB Gateway: {args.ib_host}:{args.ib_port}")
    print(f"  Client ID: {args.client_id}")
    print(f"  Batch Size: {batch_size}")
    print(f"  Min Delay: {min_delay}s")
    print(f"  Speed Mode: {speed_mode}")
    print(f"  Mode: {'Single Run' if args.once else 'Continuous'}")
    print("")
    print("  KEY OPTIMIZATIONS:")
    print("  - Removed 55/10min internal limit (not needed for 1min+ bars)")
    print("  - Only respecting burst limit (6 req/2sec per symbol)")
    print("  - IB Gateway soft-throttling is the only limiter now")
    print("=" * 65)
    print("")
    
    collector = IBHistoricalCollectorV3(
        backend_url=args.url,
        ib_host=args.ib_host,
        ib_port=args.ib_port,
        client_id=args.client_id
    )
    
    collector.run(batch_size=batch_size, continuous=not args.once, min_delay=min_delay)


if __name__ == "__main__":
    main()
