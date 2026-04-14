"""
Training subprocess runner.

Runs run_training_pipeline in a completely isolated process.
Connects to MongoDB independently. Writes status via _persist() as usual.
The main FastAPI process stays 100% responsive.

Usage (from ai_training.py):
    process = subprocess.Popen([sys.executable, '-m', 'services.ai_modules.training_subprocess',
                                '--mongo-url', MONGO_URL, '--db-name', DB_NAME, ...])
"""
import argparse
import asyncio
import json
import logging
import os
import subprocess as _subprocess
import sys
import warnings

import numpy as np

# Silence NumPy divide-by-zero warnings in correlation calculations
# (constant-value features produce stddev=0, which is handled by XGBoost natively)
warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*invalid value encountered in divide.*")

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("training_subprocess")


def _system_preflight():
    """Run system-level checks and optimizations before training starts."""
    if os.name == 'nt':
        return  # Windows — skip Linux-specific tuning

    my_pid = os.getpid()

    # 1. Kill orphaned training processes (from crashed previous runs)
    try:
        result = _subprocess.run(
            ['pgrep', '-f', 'services.ai_modules.training_subprocess'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            pids = [p.strip() for p in result.stdout.strip().split('\n') if p.strip()]
            orphans = [p for p in pids if int(p) != my_pid]
            if orphans:
                logger.warning(f"[PREFLIGHT] Found {len(orphans)} orphaned training process(es): {orphans}")
                for pid in orphans:
                    try:
                        os.kill(int(pid), 9)
                        logger.info(f"[PREFLIGHT] Killed orphan PID {pid}")
                    except (ProcessLookupError, ValueError):
                        pass
    except Exception as e:
        logger.warning(f"[PREFLIGHT] Orphan check failed (non-fatal): {e}")

    # 2. Set swappiness low — prefer RAM over swap for training workloads
    try:
        current = open('/proc/sys/vm/swappiness').read().strip()
        if int(current) > 10:
            _subprocess.run(['sysctl', '-w', 'vm.swappiness=10'],
                           capture_output=True, timeout=5)
            logger.info(f"[PREFLIGHT] Set vm.swappiness=10 (was {current})")
        else:
            logger.info(f"[PREFLIGHT] vm.swappiness already {current}")
    except Exception:
        pass  # Not root or sysctl not available — fine

    # 3. Log system memory state
    try:
        with open('/proc/meminfo') as f:
            lines = f.readlines()
        mem_total = mem_avail = swap_total = swap_free = 0
        for line in lines:
            if line.startswith('MemTotal:'):
                mem_total = int(line.split()[1]) // 1024 // 1024  # GB
            elif line.startswith('MemAvailable:'):
                mem_avail = int(line.split()[1]) // 1024 // 1024
            elif line.startswith('SwapTotal:'):
                swap_total = int(line.split()[1]) // 1024 // 1024
            elif line.startswith('SwapFree:'):
                swap_free = int(line.split()[1]) // 1024 // 1024
        logger.info(f"[PREFLIGHT] RAM: {mem_total - mem_avail}GB / {mem_total}GB used | "
                    f"Swap: {swap_total - swap_free}GB / {swap_total}GB used | "
                    f"Available: {mem_avail}GB")
        if mem_avail < 20:
            logger.warning(f"[PREFLIGHT] LOW MEMORY WARNING: Only {mem_avail}GB available!")
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="Run AI training pipeline in isolated process")
    parser.add_argument("--phases", default=None, help="Comma-separated phase list")
    parser.add_argument("--bar-sizes", default=None, help="Comma-separated bar sizes")
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--force-retrain", action="store_true", default=False,
                        help="Force retrain all models, ignoring resume cache")
    parser.add_argument("--resume-max-age", type=float, default=24.0,
                        help="Skip models trained within this many hours (default: 24)")
    parser.add_argument("--test-mode", action="store_true", default=False,
                        help="Quick test: cap symbols to 50, bars to 5000")
    args = parser.parse_args()

    # System-level safety checks before anything else
    _system_preflight()

    # Verify GPU/CUDA availability for XGBoost
    try:
        import xgboost as xgb
        _test_X = np.random.rand(100, 5).astype(np.float32)
        _test_y = np.random.randint(0, 2, 100).astype(np.float32)
        _test_dm = xgb.DMatrix(_test_X, label=_test_y)
        _test_params = {'tree_method': 'hist', 'device': 'cuda', 'objective': 'binary:logistic', 'max_depth': 3, 'verbosity': 0}
        _test_model = xgb.train(_test_params, _test_dm, num_boost_round=2)
        del _test_model, _test_dm, _test_X, _test_y
        logger.info("[PREFLIGHT] XGBoost CUDA GPU: AVAILABLE and WORKING in subprocess")
    except Exception as e:
        logger.warning(f"[PREFLIGHT] XGBoost CUDA GPU: NOT AVAILABLE in subprocess ({e}) — training will use CPU")

    # Read MongoDB connection from environment (avoids shell escaping issues with special chars)
    mongo_url = os.environ.get("TRAINING_MONGO_URL") or os.environ.get("MONGO_URL", "")
    db_name = os.environ.get("TRAINING_DB_NAME") or os.environ.get("DB_NAME", "sentcom")

    if not mongo_url:
        logger.error("[SUBPROCESS] No MONGO_URL configured")
        sys.exit(1)

    # Connect to MongoDB independently
    from pymongo import MongoClient
    client = MongoClient(mongo_url, serverSelectionTimeoutMS=30000)
    db = client[db_name]

    # Verify connection
    try:
        db.command("ping")
        logger.info(f"[SUBPROCESS] Connected to MongoDB: {db_name}")
    except Exception as e:
        logger.error(f"[SUBPROCESS] MongoDB connection failed: {e}")
        _write_result(db, {"error": f"MongoDB connection failed: {e}"})
        sys.exit(1)

    # Ensure critical indexes exist before heavy queries
    try:
        from pymongo import ASCENDING
        
        # Check existing indexes first — skip creation if already present (saves minutes on 178M+ docs)
        existing_indexes = {idx["name"] for idx in db["ib_historical_data"].list_indexes()}
        
        if "symbol_barsize_date" in existing_indexes or "symbol_1_bar_size_1_date_1" in existing_indexes:
            logger.info("[SUBPROCESS] ib_historical_data compound index already exists — skipping")
        else:
            logger.info("[SUBPROCESS] Building index on ib_historical_data (178M+ docs — may take 5-15 minutes)...")
            db["ib_historical_data"].create_index(
                [("symbol", ASCENDING), ("bar_size", ASCENDING), ("date", ASCENDING)],
                name="symbol_barsize_date"
            )
            logger.info("[SUBPROCESS] ib_historical_data index built")
        
        # Feature cache index (small collection, fast)
        existing_cache_indexes = {idx["name"] for idx in db["feature_cache"].list_indexes()}
        if "cache_key_idx" not in existing_cache_indexes and "cache_key_1" not in existing_cache_indexes:
            logger.info("[SUBPROCESS] Building index on feature_cache...")
            try:
                db["feature_cache"].create_index(
                    [("cache_key", ASCENDING)],
                    name="cache_key_idx", unique=True
                )
            except Exception:
                # Duplicates exist — create non-unique
                db["feature_cache"].create_index(
                    [("cache_key", ASCENDING)],
                    name="cache_key_idx"
                )
            logger.info("[SUBPROCESS] feature_cache index ready")
        else:
            logger.info("[SUBPROCESS] feature_cache index already exists — skipping")
            
    except Exception as idx_err:
        logger.warning(f"[SUBPROCESS] Index check/creation (non-fatal): {idx_err}")

    phases = args.phases.split(",") if args.phases else None
    bar_sizes = args.bar_sizes.split(",") if args.bar_sizes else None

    # Run the pipeline
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        from services.ai_modules.training_pipeline import run_training_pipeline
        logger.info(f"[SUBPROCESS] Starting pipeline: phases={phases}, bar_sizes={bar_sizes}")
        result = loop.run_until_complete(
            run_training_pipeline(
                db=db,
                phases=phases,
                bar_sizes=bar_sizes,
                max_symbols_override=args.max_symbols,
                force_retrain=args.force_retrain,
                resume_max_age_hours=args.resume_max_age,
                test_mode=args.test_mode,
            )
        )
        logger.info("[SUBPROCESS] Pipeline completed successfully")
        _write_result(db, result)
    except Exception as e:
        logger.error(f"[SUBPROCESS] Pipeline error: {e}", exc_info=True)
        _write_result(db, {"error": str(e)})
        sys.exit(1)
    finally:
        loop.close()
        client.close()


def _write_result(db, result):
    """Write final result to MongoDB so the main process can read it."""
    from datetime import datetime, timezone
    try:
        db["training_pipeline_result"].update_one(
            {"_id": "latest"},
            {"$set": {"result": result, "completed_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
    except Exception as e:
        logger.error(f"[SUBPROCESS] Failed to write result: {e}")


if __name__ == "__main__":
    main()
