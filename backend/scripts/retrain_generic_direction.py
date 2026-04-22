"""
Targeted retrain of `direction_predictor_{bar_size}` via train_full_universe.

Why: the active `direction_predictor_5min` has recall_down=0.0 / recall_up=0.07
(model collapsed to predicting FLAT). The class-balance fix + protection gate
are both live in code. This script just drives a single-timeframe retrain
without having to go through the job queue / UI.

Usage (on Spark, from repo root):
  PYTHONPATH=backend /home/spark-1a60/venv/bin/python \
      backend/scripts/retrain_generic_direction.py --bar-size "5 mins"

Flags:
  --bar-size  Timeframe to retrain (default "5 mins")
  --batch     Symbol batch size (default 500)
  --max-bars  Max bars per symbol. 0 = use TIMEFRAME_SETTINGS default (recommended).

Expected: ~30–90 min on Spark for "5 mins". Verify promoted model metrics
afterwards with:
  db.timeseries_models.find_one({"name":"direction_predictor_5min"},
      {"_id":0,"version":1,"metrics":1})
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_ROOT = HERE.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_ROOT / ".env")
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("retrain_generic")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bar-size", default="5 mins",
                    help='timeframe: "1 min" | "5 mins" | "15 mins" | "1 hour" | "1 day"')
    ap.add_argument("--batch", type=int, default=500, help="symbol batch size")
    ap.add_argument("--max-bars", type=int, default=0,
                    help="max bars per symbol (0 = per-TF default)")
    args = ap.parse_args()

    from motor.motor_asyncio import AsyncIOMotorClient
    from services.ai_modules.timeseries_service import TimeSeriesAIService

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "tradecommand")
    if not mongo_url:
        logger.error("MONGO_URL not set")
        sys.exit(2)

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    logger.info(f"Connected to MongoDB: {db_name}")

    svc = TimeSeriesAIService()
    svc.set_db(db)
    if not svc._ml_available:
        logger.error("XGBoost not available — cannot train.")
        sys.exit(3)

    logger.info(f"Kicking train_full_universe(bar_size={args.bar_size!r}, "
                f"batch={args.batch}, max_bars={args.max_bars})")
    result = await svc.train_full_universe(
        bar_size=args.bar_size,
        symbol_batch_size=args.batch,
        max_bars_per_symbol=args.max_bars,
    )

    logger.info("=" * 70)
    logger.info(f"SUCCESS={result.get('success')}")
    metrics = result.get("metrics", {}) or {}
    for k in ("accuracy", "recall_up", "recall_down", "recall_flat",
              "f1_up", "f1_down", "f1_flat", "macro_f1"):
        v = metrics.get(k)
        if v is not None:
            logger.info(f"  {k} = {v}")
    if result.get("error"):
        logger.error(f"  error = {result['error']}")
    logger.info("=" * 70)

    # Show what's active now
    import pymongo
    sync_db = pymongo.MongoClient(mongo_url)[db_name]
    active = sync_db.timeseries_models.find_one(
        {"name": {"$regex": "^direction_predictor_"}, "saved_at": {"$exists": True}},
        sort=[("saved_at", -1)],
        projection={"_id": 0, "name": 1, "version": 1, "saved_at": 1, "metrics": 1},
    )
    if active:
        logger.info(f"Most-recently-saved active direction_predictor: {active}")


if __name__ == "__main__":
    asyncio.run(main())
