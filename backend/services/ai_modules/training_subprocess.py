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
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("training_subprocess")


def main():
    parser = argparse.ArgumentParser(description="Run AI training pipeline in isolated process")
    parser.add_argument("--phases", default=None, help="Comma-separated phase list")
    parser.add_argument("--bar-sizes", default=None, help="Comma-separated bar sizes")
    parser.add_argument("--max-symbols", type=int, default=None)
    args = parser.parse_args()

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
