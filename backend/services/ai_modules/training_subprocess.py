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
    parser.add_argument("--mongo-url", required=True)
    parser.add_argument("--db-name", required=True)
    parser.add_argument("--phases", default=None, help="Comma-separated phase list")
    parser.add_argument("--bar-sizes", default=None, help="Comma-separated bar sizes")
    parser.add_argument("--max-symbols", type=int, default=None)
    args = parser.parse_args()

    # Connect to MongoDB independently
    from pymongo import MongoClient
    client = MongoClient(args.mongo_url, serverSelectionTimeoutMS=30000)
    db = client[args.db_name]

    # Verify connection
    try:
        db.command("ping")
        logger.info(f"[SUBPROCESS] Connected to MongoDB: {args.db_name}")
    except Exception as e:
        logger.error(f"[SUBPROCESS] MongoDB connection failed: {e}")
        _write_result(db, {"error": f"MongoDB connection failed: {e}"})
        sys.exit(1)

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
