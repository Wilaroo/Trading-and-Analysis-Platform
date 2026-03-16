"""
Weekend Batch Automation Script
================================

This script runs after StartTrading.bat to automatically trigger
batch operations like data collection, model training, and simulations.

Usage:
    python weekend_batch.py --cloud-url https://dual-stream-chat-1.preview.emergentagent.com
    python weekend_batch.py --cloud-url https://... --mode weekend
    python weekend_batch.py --cloud-url https://... --mode nightly
    python weekend_batch.py --cloud-url https://... --mode auto

Modes:
    auto     - Detect based on day/time (default)
    weekend  - Full batch: Smart Collection + Training + Simulations
    nightly  - Quick refresh: Smart Collection only
    manual   - Just print what would run, don't execute

The script will:
1. Wait for IB Data Pusher to be connected
2. Trigger Smart Collection (ADV-filtered stocks only)
3. Monitor progress until complete
4. Trigger model retraining with new data
5. Run simulation backtests
6. Log everything to weekend_batch.log
"""

import argparse
import json
import logging
import time
import requests
from datetime import datetime
import sys
import os

# Configure logging
log_dir = os.path.dirname(os.path.abspath(__file__))
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(os.path.join(log_dir, 'weekend_batch.log')),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("WeekendBatch")


class WeekendBatchRunner:
    """Orchestrates weekend/nightly batch operations."""
    
    def __init__(self, cloud_url: str):
        self.cloud_url = cloud_url.rstrip('/')
        self.api_base = f"{self.cloud_url}/api"
        
    def detect_mode(self) -> str:
        """Auto-detect mode based on day and time."""
        now = datetime.now()
        day = now.weekday()  # 0=Monday, 5=Saturday, 6=Sunday
        hour = now.hour
        
        # Weekend: Saturday or Sunday
        if day in [5, 6]:
            logger.info(f"Detected WEEKEND (day={day}, hour={hour})")
            return "weekend"
        
        # Nightly: Weekday after 8 PM or before 6 AM
        if hour >= 20 or hour < 6:
            logger.info(f"Detected NIGHTLY (day={day}, hour={hour})")
            return "nightly"
        
        # Otherwise, don't auto-run batch
        logger.info(f"Detected TRADING HOURS (day={day}, hour={hour}) - no batch")
        return "none"
    
    def wait_for_pusher(self, timeout: int = 120) -> bool:
        """Wait for IB Data Pusher to be connected."""
        logger.info("Waiting for IB Data Pusher to connect...")
        
        start = time.time()
        while time.time() - start < timeout:
            try:
                resp = requests.get(f"{self.api_base}/ib/pushed-data", timeout=5)
                if resp.ok:
                    data = resp.json()
                    if data.get("connected"):
                        logger.info("IB Data Pusher CONNECTED!")
                        return True
            except Exception as e:
                pass
            
            elapsed = int(time.time() - start)
            if elapsed % 10 == 0:
                logger.info(f"Still waiting for pusher... ({elapsed}s)")
            time.sleep(2)
        
        logger.warning(f"Pusher not connected after {timeout}s")
        return False
    
    def trigger_smart_collection(self) -> dict:
        """Start Smart Collection (ADV-filtered stocks)."""
        logger.info("=" * 50)
        logger.info("STARTING SMART COLLECTION")
        logger.info("=" * 50)
        
        try:
            # First get the plan
            resp = requests.get(f"{self.api_base}/ib-collector/smart-collection-plan", timeout=30)
            if resp.ok:
                plan = resp.json()
                logger.info(f"Smart Collection Plan:")
                logger.info(f"  Total Requests: {plan.get('total_requests', 'N/A')}")
                logger.info(f"  Estimated Time: {plan.get('total_estimated_hours', 'N/A')} hours")
            
            # Start the collection
            resp = requests.post(
                f"{self.api_base}/ib-collector/smart-collection-run?days=30",
                timeout=30
            )
            
            if resp.ok:
                result = resp.json()
                logger.info(f"Smart Collection started: {result}")
                return result
            else:
                logger.error(f"Failed to start: {resp.status_code} - {resp.text}")
                return {"success": False, "error": resp.text}
                
        except Exception as e:
            logger.error(f"Error starting Smart Collection: {e}")
            return {"success": False, "error": str(e)}
    
    def trigger_full_market_collection(self) -> dict:
        """Start Full Market Collection (all stocks)."""
        logger.info("=" * 50)
        logger.info("STARTING FULL MARKET COLLECTION")
        logger.info("=" * 50)
        
        try:
            resp = requests.post(
                f"{self.api_base}/ib-collector/full-market-collection?days=30&bar_size=1%20day",
                timeout=30
            )
            
            if resp.ok:
                result = resp.json()
                logger.info(f"Full Market Collection started: {result}")
                return result
            else:
                logger.error(f"Failed to start: {resp.status_code} - {resp.text}")
                return {"success": False, "error": resp.text}
                
        except Exception as e:
            logger.error(f"Error starting Full Market Collection: {e}")
            return {"success": False, "error": str(e)}
    
    def monitor_collection(self, poll_interval: int = 30, timeout_hours: float = 12) -> bool:
        """Monitor collection progress until complete."""
        logger.info("Monitoring collection progress...")
        
        start = time.time()
        timeout_secs = timeout_hours * 3600
        last_completed = 0
        stall_count = 0
        
        while time.time() - start < timeout_secs:
            try:
                resp = requests.get(f"{self.api_base}/ib-collector/queue-progress", timeout=10)
                if resp.ok:
                    data = resp.json()
                    completed = data.get("completed", 0)
                    pending = data.get("pending", 0)
                    failed = data.get("failed", 0)
                    processing = data.get("claimed", 0)
                    total = completed + pending + failed + processing
                    
                    if total > 0:
                        pct = (completed + failed) / total * 100
                        logger.info(f"Progress: {pct:.1f}% | Completed: {completed} | Pending: {pending} | Failed: {failed}")
                        
                        # Check if done
                        if pending == 0 and processing == 0:
                            logger.info("=" * 50)
                            logger.info(f"COLLECTION COMPLETE!")
                            logger.info(f"  Total Completed: {completed}")
                            logger.info(f"  Total Failed: {failed}")
                            logger.info("=" * 50)
                            return True
                        
                        # Check for stalls
                        if completed == last_completed:
                            stall_count += 1
                            if stall_count >= 10:  # 5 minutes of no progress
                                logger.warning("Collection appears stalled - pusher may be disconnected")
                        else:
                            stall_count = 0
                            last_completed = completed
                    
            except Exception as e:
                logger.warning(f"Error checking progress: {e}")
            
            time.sleep(poll_interval)
        
        logger.error(f"Collection timed out after {timeout_hours} hours")
        return False
    
    def trigger_model_training(self) -> dict:
        """Trigger Time-Series AI model retraining."""
        logger.info("=" * 50)
        logger.info("TRIGGERING MODEL RETRAINING")
        logger.info("=" * 50)
        
        try:
            resp = requests.post(f"{self.api_base}/ai-modules/timeseries/train", timeout=60)
            
            if resp.ok:
                result = resp.json()
                logger.info(f"Model training started: {result}")
                return result
            else:
                logger.error(f"Failed to start training: {resp.status_code}")
                return {"success": False, "error": resp.text}
                
        except Exception as e:
            logger.error(f"Error triggering training: {e}")
            return {"success": False, "error": str(e)}
    
    def get_simulation_universe(self) -> list:
        """
        Get the list of symbols to run simulations on.
        Uses the Smart Collection universe (ADV-filtered stocks).
        """
        try:
            # Get the smart collection plan which has the symbol universe
            resp = requests.get(f"{self.api_base}/ib-collector/smart-collection-plan", timeout=30)
            if resp.ok:
                plan = resp.json()
                symbols = set()
                
                # Collect symbols from all tiers
                for tier_name, tier_data in plan.get("plan", {}).items():
                    tier_symbols = tier_data.get("symbols", [])
                    symbols.update(tier_symbols)
                
                logger.info(f"Got {len(symbols)} symbols from Smart Collection universe")
                return list(symbols)
        except Exception as e:
            logger.warning(f"Could not get Smart Collection universe: {e}")
        
        # Fallback: Get the curated/default symbols
        try:
            resp = requests.get(f"{self.api_base}/ib-collector/default-symbols", timeout=30)
            if resp.ok:
                data = resp.json()
                symbols = data.get("symbols", [])
                logger.info(f"Fallback: Using {len(symbols)} curated symbols")
                return symbols
        except Exception as e:
            logger.warning(f"Could not get curated symbols: {e}")
        
        # Last resort fallback
        logger.warning("Using hardcoded top symbols as last resort")
        return ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META", "GOOGL", "AMZN",
                "NFLX", "JPM", "BAC", "WFC", "GS", "V", "MA", "DIS", "PYPL", "INTC"]
    
    def run_simulations(self, symbols: list = None, max_symbols: int = None) -> dict:
        """
        Run batch simulations on collected data.
        
        Args:
            symbols: List of symbols to simulate. If None, uses Smart Collection universe.
            max_symbols: Maximum number of symbols to simulate (None = all)
        """
        logger.info("=" * 50)
        logger.info("RUNNING BATCH SIMULATIONS")
        logger.info("=" * 50)
        
        if symbols is None:
            symbols = self.get_simulation_universe()
        
        # Optionally limit the number of symbols
        if max_symbols and len(symbols) > max_symbols:
            logger.info(f"Limiting simulations to {max_symbols} symbols (from {len(symbols)})")
            # Prioritize liquid names - they're usually first in the list
            symbols = symbols[:max_symbols]
        
        logger.info(f"Running simulations for {len(symbols)} symbols...")
        
        results = {"success": 0, "failed": 0, "errors": []}
        
        for i, symbol in enumerate(symbols):
            try:
                resp = requests.post(
                    f"{self.api_base}/simulation/run",
                    json={
                        "symbol": symbol,
                        "days": 30,
                        "strategy": "momentum"
                    },
                    timeout=60
                )
                
                if resp.ok:
                    results["success"] += 1
                    # Log progress every 50 symbols
                    if (i + 1) % 50 == 0:
                        logger.info(f"  Progress: {i + 1}/{len(symbols)} simulations triggered")
                else:
                    results["failed"] += 1
                    if len(results["errors"]) < 10:  # Keep first 10 errors
                        results["errors"].append(f"{symbol}: HTTP {resp.status_code}")
                    
            except Exception as e:
                results["failed"] += 1
                if len(results["errors"]) < 10:
                    results["errors"].append(f"{symbol}: {str(e)[:50]}")
            
            time.sleep(0.5)  # Rate limit - 2 per second
        
        logger.info(f"Simulations complete: {results['success']} succeeded, {results['failed']} failed")
        if results["errors"]:
            logger.warning(f"Sample errors: {results['errors'][:5]}")
        
        return results
    
    def sync_learning_connections(self) -> dict:
        """Trigger learning connection sync."""
        logger.info("=" * 50)
        logger.info("SYNCING LEARNING CONNECTIONS")
        logger.info("=" * 50)
        
        try:
            resp = requests.post(f"{self.api_base}/learning/sync-all", timeout=60)
            
            if resp.ok:
                result = resp.json()
                logger.info(f"Learning sync triggered: {result}")
                return result
            else:
                logger.warning(f"Learning sync failed: {resp.status_code}")
                return {"success": False}
                
        except Exception as e:
            logger.warning(f"Error syncing learning connections: {e}")
            return {"success": False, "error": str(e)}
    
    def run_weekend_batch(self):
        """Full weekend batch: Collection + Training + Simulations."""
        logger.info("=" * 60)
        logger.info("   WEEKEND BATCH MODE")
        logger.info("   Full data refresh + training + simulations")
        logger.info("=" * 60)
        
        # Wait for pusher
        if not self.wait_for_pusher():
            logger.error("Cannot proceed without IB Data Pusher")
            return False
        
        # Start Smart Collection
        result = self.trigger_smart_collection()
        if not result.get("success"):
            logger.error("Failed to start collection")
            return False
        
        # Monitor until complete
        if not self.monitor_collection():
            logger.error("Collection did not complete")
            return False
        
        # Retrain model with new data
        self.trigger_model_training()
        time.sleep(5)
        
        # Run simulations
        self.run_simulations()
        
        # Sync learning connections
        self.sync_learning_connections()
        
        logger.info("=" * 60)
        logger.info("   WEEKEND BATCH COMPLETE!")
        logger.info("=" * 60)
        return True
    
    def run_nightly_batch(self):
        """Nightly batch: Quick Smart Collection refresh."""
        logger.info("=" * 60)
        logger.info("   NIGHTLY BATCH MODE")
        logger.info("   Quick Smart Collection refresh")
        logger.info("=" * 60)
        
        # Wait for pusher
        if not self.wait_for_pusher():
            logger.error("Cannot proceed without IB Data Pusher")
            return False
        
        # Start Smart Collection
        result = self.trigger_smart_collection()
        if not result.get("success"):
            logger.error("Failed to start collection")
            return False
        
        # Monitor until complete
        if not self.monitor_collection(timeout_hours=6):
            logger.error("Collection did not complete in time")
            return False
        
        logger.info("=" * 60)
        logger.info("   NIGHTLY BATCH COMPLETE!")
        logger.info("=" * 60)
        return True


def main():
    parser = argparse.ArgumentParser(description="Weekend/Nightly Batch Automation")
    parser.add_argument("--cloud-url", required=True, help="Cloud platform URL")
    parser.add_argument("--mode", choices=["auto", "weekend", "nightly", "manual"], 
                        default="auto", help="Batch mode")
    parser.add_argument("--skip-wait", action="store_true", help="Skip waiting for pusher")
    
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("   TRADECOMMAND WEEKEND BATCH AUTOMATION")
    logger.info(f"   Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"   Cloud URL: {args.cloud_url}")
    logger.info(f"   Mode: {args.mode}")
    logger.info("=" * 60)
    
    runner = WeekendBatchRunner(args.cloud_url)
    
    # Determine mode
    if args.mode == "auto":
        mode = runner.detect_mode()
    else:
        mode = args.mode
    
    # Execute based on mode
    if mode == "weekend":
        success = runner.run_weekend_batch()
    elif mode == "nightly":
        success = runner.run_nightly_batch()
    elif mode == "manual":
        logger.info("Manual mode - showing what would run:")
        detected = runner.detect_mode()
        logger.info(f"  Auto-detected mode: {detected}")
        logger.info("  No actions taken.")
        success = True
    else:
        logger.info("Not a batch time - skipping automated tasks")
        logger.info("Use --mode weekend or --mode nightly to force")
        success = True
    
    if success:
        logger.info("Batch completed successfully!")
    else:
        logger.error("Batch completed with errors")
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
