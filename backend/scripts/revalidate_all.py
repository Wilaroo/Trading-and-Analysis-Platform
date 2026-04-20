"""
Stand-alone Re-Validation Script
================================

Re-runs Phase 13 (Auto-Validation) against models that are ALREADY TRAINED,
without kicking off the full 10-hour training pipeline.

Uses the NEW validator (fail-closed, MC bootstrap, direction-aware backtest)
to give you honest promote/reject decisions on models that were previously
rubber-stamped by the fail-open bug.

Usage:
    cd ~/Trading-and-Analysis-Platform
    python3 backend/scripts/revalidate_all.py

Expected runtime: ~90 minutes for full catalog (34 setup types × 3 backtest phases each).

What it does:
    1. Connects to MongoDB using backend/.env
    2. Scans `timeseries_models` and results from previous training for setup types
    3. For each (setup_type, bar_size), runs:
         - AI Comparison backtest
         - Monte Carlo (now with bootstrap resampling)
         - Walk-Forward
    4. Feeds results through the new promotion validator
    5. Writes verdicts to `model_validations` collection
    6. Prints a summary at the end

Safe to run while other things are happening — it only reads trained models,
writes validation records, and doesn't touch live trading state.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Make backend package importable when run from repo root
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / "backend" / ".env")

from pymongo import MongoClient

# Logging to stdout with timestamps so progress is visible
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("revalidate")


async def main():
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "tradecommand")
    if not mongo_url:
        logger.error("MONGO_URL not set in backend/.env")
        sys.exit(1)

    client = MongoClient(mongo_url)
    db = client[db_name]
    logger.info(f"Connected to MongoDB: {db_name}")

    # Lazy imports to avoid heavy startup when just checking help
    from services.ai_modules.post_training_validator import validate_trained_model
    from services.slow_learning.advanced_backtest_engine import get_advanced_backtest_engine
    from services.ai_modules.timeseries_gbm import TimeSeriesGBM
    from services.ai_modules.setup_training_config import (
        get_model_name,
        SETUP_TRAINING_PROFILES,
    )

    # ── 1. Load the timeseries AI model into the backtest engine ────
    backtest_engine = get_advanced_backtest_engine()
    backtest_engine.set_db(db)

    ts_model = TimeSeriesGBM(model_name="direction_predictor_5min")
    ts_model.set_db(db)
    if ts_model._model is not None:
        backtest_engine.set_timeseries_model(ts_model)
        logger.info(f"Loaded timeseries model: version={getattr(ts_model, '_version', '?')}")
    else:
        logger.warning("Timeseries AI model not found — AI comparison phase will still run but without predictions")

    # ── 2. Figure out which setup types have trained models in Mongo ────
    # Each trained setup has a model saved by `_train_and_save_model` under
    # name like "momentum_5min_predictor". We match that to our profile catalog.
    # Note: SETUP_TRAINING_PROFILES[setup] is a list of profile dicts, each
    # with a "bar_size" key — we extract the bar_size string per profile.
    trained = []
    for setup_type, profiles in SETUP_TRAINING_PROFILES.items():
        for profile in profiles:
            bar_size = profile["bar_size"] if isinstance(profile, dict) else profile
            model_name = get_model_name(setup_type, bar_size)
            doc = db["timeseries_models"].find_one({"name": model_name}, {"_id": 0, "name": 1, "metrics": 1})
            if doc:
                acc = (doc.get("metrics") or {}).get("accuracy", 0) or 0
                trained.append((setup_type, bar_size, acc))

    if not trained:
        logger.error("No trained models found in timeseries_models collection — nothing to revalidate.")
        sys.exit(2)

    logger.info(f"Found {len(trained)} trained (setup_type, bar_size) pairs to revalidate")

    # Keep the best bar_size per setup_type (matches Phase 13 behavior)
    best_by_setup = {}
    for st, bs, acc in trained:
        if st not in best_by_setup or acc > best_by_setup[st][1]:
            best_by_setup[st] = (bs, acc)
    logger.info(f"Will validate {len(best_by_setup)} unique setup types (best bar_size per setup)")

    # ── 3. Run validation loop ────
    promoted = rejected = errored = 0
    all_results = []
    for i, (setup_type, (bar_size, accuracy)) in enumerate(best_by_setup.items(), start=1):
        logger.info(
            f"[{i}/{len(best_by_setup)}] Validating {setup_type}/{bar_size} "
            f"(training_acc={accuracy:.1%})"
        )
        try:
            val_result = await validate_trained_model(
                db=db,
                timeseries_service=None,  # rollback not needed for re-validation
                backtest_engine=backtest_engine,
                setup_type=setup_type,
                bar_size=bar_size,
                training_result={"metrics": {"accuracy": accuracy}},
            )
            status_str = val_result.get("status", "?")
            reason = val_result.get("reason", "")[:120]
            logger.info(f"  → {status_str.upper()}: {reason}")
            if status_str == "promoted":
                promoted += 1
            elif status_str.startswith("reject"):
                rejected += 1
            all_results.append(val_result)
        except Exception as e:
            errored += 1
            logger.error(f"  → ERROR: {e}", exc_info=True)

    # ── 4. Summary ────
    total = promoted + rejected + errored
    promote_rate = (promoted / total * 100) if total else 0.0
    logger.info("=" * 70)
    logger.info(f"REVALIDATION COMPLETE — {total} models processed")
    logger.info(f"  Promoted:  {promoted} ({promote_rate:.1f}%)")
    logger.info(f"  Rejected:  {rejected}")
    logger.info(f"  Errored:   {errored}")
    logger.info("=" * 70)
    logger.info("Check the Validation Summary Dashboard in NIA for detailed breakdown,")
    logger.info("or query: db.model_validations.find({'status': 'promoted'}).sort('validated_at', -1)")


if __name__ == "__main__":
    asyncio.run(main())
