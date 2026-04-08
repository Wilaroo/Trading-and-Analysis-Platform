#!/usr/bin/env python3
"""
IB Historical Data Collector v4.0 - PARALLEL SYMBOL FETCHING
=============================================================
Fetches multiple symbols simultaneously for maximum throughput.

Key Features:
- Parallel symbol fetching (2-3 symbols at once)
- Each symbol's timeframes processed together
- Respects IB burst limits (6 req/2sec per symbol)
- Smart claim mechanism prevents duplicate work

Usage:
    python ib_historical_collector_v4.py --url http://localhost:8001 --client-id 88
    python ib_historical_collector_v4.py --url http://localhost:8001 --client-id 88 --parallel 3
"""

import argparse
import time
import logging
import requests
from datetime import datetime, timezone
from typing import List, Dict, Optional
from collections import defaultdict
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
    """Thread-safe API client for backend communication."""
    
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.lock = threading.Lock()
    
    def _get_session(self):
        """Get a new session for each request (thread-safe)."""
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'IB-Historical-Collector/4.0-Parallel',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })
        return session
    
    def get(self, endpoint: str, timeout: int = 30) -> Optional[dict]:
        url = f"{self.base_url}{endpoint}"
        session = self._get_session()
        for attempt in range(3):
            try:
                resp = session.get(url, timeout=timeout)
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 404:
                    return None
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout on GET {endpoint} (attempt {attempt + 1}/3)")
                time.sleep(2 ** attempt)
            except Exception as e:
                logger.error(f"Error on GET {endpoint}: {e}")
                time.sleep(2 ** attempt)
            finally:
                session.close()
        return None
    
    def post(self, endpoint: str, data: dict, timeout: int = 30) -> Optional[dict]:
        url = f"{self.base_url}{endpoint}"
        session = self._get_session()
        try:
            resp = session.post(url, json=data, timeout=timeout)
            if resp.status_code in [200, 201]:
                return resp.json()
            elif resp.status_code == 409:
                return {"success": True, "status": "already_processed"}
        except requests.exceptions.Timeout:
            logger.debug(f"Timeout on POST {endpoint}")
        except Exception as e:
            logger.debug(f"Error on POST {endpoint}: {e}")
        finally:
            session.close()
        return None
    
    def optimize_indexes(self) -> bool:
        logger.info("Optimizing MongoDB indexes...")
        result = self.post("/api/ib/historical-data/optimize-indexes", {}, timeout=60)
        if result and result.get("success"):
            logger.info(f"  Indexes optimized")
            return True
        return False


class IBHistoricalCollectorV4:
    """
    PARALLEL Historical Data Collector v4.0
    
    Fetches multiple symbols simultaneously for maximum throughput.
    """
    
    def __init__(self, backend_url: str, ib_host: str = "127.0.0.1", 
                 ib_port: int = 4002, client_id: int = 11, parallel_symbols: int = 2):
        self.backend_url = backend_url
        self.ib_host = ib_host
        self.ib_port = ib_port
        self.client_id = client_id
        self.parallel_symbols = parallel_symbols
        
        self.api = APIClient(backend_url)
        self.ib = None
        self.ib_lock = threading.Lock()
        self.running = False
        
        self.stats = {
            "started_at": None,
            "requests_completed": 0,
            "requests_failed": 0,
            "requests_skipped": 0,
            "bars_collected": 0,
            "ib_soft_throttles": 0,
            "symbols_processed": 0
        }
        self.stats_lock = threading.Lock()
    
    def connect(self, max_retries: int = 5) -> bool:
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
                logger.error(f"Failed to connect (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    wait_time = min(30 * (attempt + 1), 120)
                    logger.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
        
        return False
    
    def ensure_connected(self) -> bool:
        with self.ib_lock:
            if self.ib and self.ib.isConnected():
                return True
        logger.warning("IB Gateway connection lost - reconnecting...")
        return self.connect(max_retries=10)
    
    def disconnect(self):
        if self.ib and self.ib.isConnected():
            self.ib.disconnect()
            logger.info("Disconnected from IB Gateway")
    
    def fetch_pending_requests(self, limit: int = 18) -> List[dict]:
        result = self.api.get(f"/api/ib/historical-data/pending?limit={limit}", timeout=30)
        if result:
            return result.get("requests", [])
        return []
    
    def smart_batch_claim_requests(self, request_ids: List[str]) -> dict:
        if not request_ids:
            return {"claimed": [], "skip": [], "skip_details": [], "failed": []}
        
        result = self.api.post(
            "/api/ib/historical-data/smart-batch-claim", 
            {"request_ids": request_ids, "check_existing": True},
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
        if not results:
            return {"processed": 0, "bars_stored": 0}
        
        resp = self.api.post("/api/ib/historical-data/batch-result", {"results": results}, timeout=60)
        if resp:
            return {
                "processed": resp.get("processed", len(results)),
                "bars_stored": resp.get("bars_stored", 0)
            }
        return {"processed": 0, "bars_stored": 0}
    
    def fetch_single_request(self, request: dict) -> dict:
        """Fetch historical data for a single request (thread-safe)."""
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
            with self.ib_lock:
                contract = Stock(symbol, "SMART", "USD")
                try:
                    self.ib.qualifyContracts(contract)
                except Exception as e:
                    result["success"] = True
                    result["status"] = "no_data"
                    result["error"] = f"Symbol not available: {e}"
                    return result
                
                bars = self.ib.reqHistoricalData(
                    contract,
                    endDateTime="",
                    durationStr=duration,
                    barSizeSetting=bar_size,
                    whatToShow="TRADES",
                    useRTH=True
                )
                
                self.ib.sleep(0.2)
            
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
            
            with self.stats_lock:
                self.stats["bars_collected"] += len(bar_data)
            
        except Exception as e:
            error_str = str(e)
            
            if "pacing" in error_str.lower():
                logger.warning(f"  IB soft throttle for {symbol} ({bar_size})")
                with self.stats_lock:
                    self.stats["ib_soft_throttles"] += 1
                result["status"] = "rate_limited"
                result["error"] = "IB soft throttle"
                time.sleep(5)
            elif "no data" in error_str.lower() or "no historical data" in error_str.lower():
                result["success"] = True
                result["status"] = "no_data"
                result["error"] = error_str
            else:
                result["status"] = "error"
                result["error"] = error_str
        
        return result
    
    def fetch_symbol_timeframes(self, symbol: str, requests: List[dict]) -> List[dict]:
        """Fetch all timeframes for a single symbol."""
        results = []
        
        for req in requests:
            if not self.running:
                break
            
            result = self.fetch_single_request(req)
            results.append(result)
            
            bar_size = req.get("bar_size", "?")
            if result["status"] == "success":
                with self.stats_lock:
                    self.stats["requests_completed"] += 1
                logger.info(f"    {symbol} ({bar_size}): {result['bar_count']} bars")
            elif result["status"] == "no_data":
                with self.stats_lock:
                    self.stats["requests_completed"] += 1
                logger.info(f"    {symbol} ({bar_size}): No data")
            else:
                with self.stats_lock:
                    self.stats["requests_failed"] += 1
                logger.warning(f"    {symbol} ({bar_size}): {result['status']}")
            
            time.sleep(0.2)  # Small delay between timeframes
        
        return results
    
    def process_symbols_parallel(self, requests_by_symbol: Dict[str, List[dict]]) -> List[dict]:
        """Process multiple symbols in parallel using ThreadPoolExecutor."""
        all_results = []
        symbols = list(requests_by_symbol.keys())
        
        logger.info(f"  Fetching {len(symbols)} symbols in parallel: {', '.join(symbols)}")
        
        with ThreadPoolExecutor(max_workers=self.parallel_symbols) as executor:
            futures = {}
            for symbol, reqs in requests_by_symbol.items():
                future = executor.submit(self.fetch_symbol_timeframes, symbol, reqs)
                futures[future] = symbol
            
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    results = future.result()
                    all_results.extend(results)
                    with self.stats_lock:
                        self.stats["symbols_processed"] += 1
                except Exception as e:
                    logger.error(f"  Error processing {symbol}: {e}")
        
        return all_results
    
    def run(self, batch_size: int = 18, continuous: bool = True, min_delay: float = 0.3):
        if not self.connect():
            return
        
        self.running = True
        self.stats["started_at"] = datetime.now(timezone.utc)
        
        logger.info("")
        logger.info("=" * 70)
        logger.info("  IB Historical Data Collector v4.0 - PARALLEL SYMBOL FETCHING")
        logger.info("=" * 70)
        logger.info(f"  Backend URL: {self.backend_url}")
        logger.info(f"  IB Gateway: {self.ib_host}:{self.ib_port}")
        logger.info(f"  Client ID: {self.client_id}")
        logger.info(f"  Batch Size: {batch_size}")
        logger.info(f"  Parallel Symbols: {self.parallel_symbols}")
        logger.info(f"  Min Delay: {min_delay}s")
        logger.info("")
        logger.info("  KEY FEATURES:")
        logger.info(f"  [x] Parallel symbol fetching ({self.parallel_symbols} symbols at once)")
        logger.info("  [x] No internal pacing limits (1min+ bars)")
        logger.info("  [x] Thread-safe IB Gateway access")
        logger.info("=" * 70)
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
                
                # Fetch more requests to fill parallel slots
                requests_batch = self.fetch_pending_requests(batch_size)
                
                if not requests_batch:
                    empty_cycles += 1
                    if not continuous:
                        logger.info("No pending requests. Exiting.")
                        break
                    
                    if empty_cycles >= 3:
                        logger.info("Queue empty. Waiting 60s...")
                        time.sleep(60)
                        empty_cycles = 0
                    else:
                        time.sleep(10)
                    continue
                
                empty_cycles = 0
                logger.info(f"[Cycle {cycle}] Processing {len(requests_batch)} requests...")
                
                # Smart batch claim
                request_ids = [req.get("request_id") for req in requests_batch]
                smart_result = self.smart_batch_claim_requests(request_ids)
                
                claimed_ids = set(smart_result.get("claimed", []))
                skipped_ids = set(smart_result.get("skip", []))
                skip_details = smart_result.get("skip_details", [])
                
                if skipped_ids:
                    with self.stats_lock:
                        self.stats["requests_skipped"] += len(skipped_ids)
                    logger.info(f"  [SKIP] {len(skipped_ids)} items already complete")
                
                if not claimed_ids and not skipped_ids:
                    logger.warning("  No requests claimed, skipping")
                    time.sleep(5)
                    continue
                
                # Group requests by symbol for parallel processing
                requests_to_process = [req for req in requests_batch if req.get("request_id") in claimed_ids]
                
                if not requests_to_process:
                    logger.info(f"  All items had existing data!")
                    self._print_queue_status()
                    continue
                
                # Group by symbol
                requests_by_symbol = defaultdict(list)
                for req in requests_to_process:
                    requests_by_symbol[req.get("symbol")].append(req)
                
                # Process symbols in parallel
                batch_results = self.process_symbols_parallel(dict(requests_by_symbol))
                
                # Report results
                if batch_results:
                    report = self.report_batch_results(batch_results)
                    logger.info(f"  Batch: {report['processed']} results, {report['bars_stored']} bars to DB")
                
                self._print_queue_status()
                
                time.sleep(min_delay)
                
                if not continuous:
                    break
                
        except KeyboardInterrupt:
            logger.info("\nStopping (Ctrl+C)...")
        finally:
            self.running = False
            self.disconnect()
            self._print_final_stats()
    
    def _print_queue_status(self):
        try:
            q = self.api.get('/api/ib-collector/queue-progress')
            if q:
                done = q.get('completed', 0)
                pending = q.get('pending', 0)
                total = done + pending + q.get('claimed', 0) + q.get('failed', 0)
                pct = (done / total * 100) if total > 0 else 0
                bar = '█' * int(pct/5) + '░' * (20 - int(pct/5))
                
                with self.stats_lock:
                    skip = self.stats['requests_skipped']
                    throttle = self.stats['ib_soft_throttles']
                    symbols = self.stats['symbols_processed']
                
                skip_str = f", ⚡{skip}" if skip > 0 else ""
                throttle_str = f", 🐢{throttle}" if throttle > 0 else ""
                
                logger.info(f"")
                logger.info(f"╔{'═'*68}╗")
                logger.info(f"║  QUEUE: {bar} {pct:>5.1f}%  ({done:,}/{total:,})  ║")
                logger.info(f"║  Pending: {pending:,} | Symbols: {symbols} | Session: {self.stats['requests_completed']}{skip_str}{throttle_str}, {self.stats['bars_collected']:,} bars  ║")
                logger.info(f"╚{'═'*68}╝")
                logger.info(f"")
        except:
            pass
    
    def _print_final_stats(self):
        if not self.stats["started_at"]:
            return
        
        elapsed = (datetime.now(timezone.utc) - self.stats["started_at"]).total_seconds()
        total = self.stats['requests_completed'] + self.stats['requests_skipped']
        
        logger.info("")
        logger.info("=" * 70)
        logger.info("  Collection Complete - v4.0 PARALLEL")
        logger.info("=" * 70)
        logger.info(f"  Duration: {elapsed/60:.1f} minutes")
        logger.info(f"  Symbols Processed: {self.stats['symbols_processed']}")
        logger.info(f"  Requests Completed: {self.stats['requests_completed']}")
        logger.info(f"  Requests Skipped: {self.stats['requests_skipped']}")
        logger.info(f"  Requests Failed: {self.stats['requests_failed']}")
        logger.info(f"  Bars Collected: {self.stats['bars_collected']:,}")
        logger.info(f"  IB Soft Throttles: {self.stats['ib_soft_throttles']}")
        if elapsed > 0:
            logger.info(f"  Rate: {total / (elapsed/60):.1f} req/min")
            logger.info(f"  Symbols/min: {self.stats['symbols_processed'] / (elapsed/60):.1f}")
        logger.info("=" * 70)
    
    def stop(self):
        self.running = False


def main():
    parser = argparse.ArgumentParser(description="IB Historical Collector v4.0 - PARALLEL")
    parser.add_argument("--url", default="http://localhost:8001", help="Backend URL")
    parser.add_argument("--ib-host", default="127.0.0.1", help="IB Gateway host")
    parser.add_argument("--ib-port", type=int, default=4002, help="IB Gateway port")
    parser.add_argument("--client-id", type=int, default=11, help="IB client ID")
    parser.add_argument("--batch-size", type=int, default=18, help="Batch size (default: 18)")
    parser.add_argument("--parallel", type=int, default=2, help="Parallel symbols (default: 2)")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--turbo", action="store_true", help="Turbo mode (3 parallel, batch=24)")
    
    args = parser.parse_args()
    
    if args.turbo:
        parallel = 3
        batch_size = 24
        mode = "TURBO"
    else:
        parallel = args.parallel
        batch_size = args.batch_size
        mode = "PARALLEL"
    
    print(f"\n{'='*70}")
    print(f"  IB Historical Collector v4.0 - {mode}")
    print(f"  Parallel Symbols: {parallel}")
    print(f"  Batch Size: {batch_size}")
    print(f"  Fetches {parallel} symbols simultaneously!")
    print(f"{'='*70}\n")
    
    collector = IBHistoricalCollectorV4(
        backend_url=args.url,
        ib_host=args.ib_host,
        ib_port=args.ib_port,
        client_id=args.client_id,
        parallel_symbols=parallel
    )
    
    collector.run(batch_size=batch_size, continuous=not args.once, min_delay=0.3)


if __name__ == "__main__":
    main()
