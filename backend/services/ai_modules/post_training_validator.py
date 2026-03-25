"""
Post-Training Model Validator

After a setup model is trained, this module automatically:
1. Runs a focused backtest using the newly trained model
2. Compares results against stored baseline (if any)
3. Promotes the model if it improves key metrics, or rolls back to previous
4. Stores the validation results for future comparisons

Triggered automatically from the worker after successful training.
"""

import logging
import uuid
import pickle
import base64
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# Minimum improvement thresholds to promote a new model
PROMOTION_CRITERIA = {
    "min_trades": 10,          # Must generate at least 10 trades in backtest
    "min_win_rate": 0.35,      # Must have at least 35% win rate
    "min_sharpe": -0.5,        # Must not have terrible risk-adjusted returns
    "improvement_required": False,  # If True, must beat baseline to promote
}

# Validation backtest config
VALIDATION_CONFIG = {
    "num_symbols": 20,         # Top N liquid symbols to test
    "lookback_days": 180,      # Days of history for backtest
    "starting_capital": 100000,
    "ai_confidence_threshold": 0.5,
    "ai_lookback_bars": 50,
}


async def validate_trained_model(
    db,
    timeseries_service,
    backtest_engine,
    setup_type: str,
    bar_size: str,
    training_result: Dict,
    job_id: str = None,
    progress_callback=None,
) -> Dict[str, Any]:
    """
    Validate a newly trained model by running a backtest and comparing
    against the stored baseline.
    
    Args:
        db: MongoDB database
        timeseries_service: TimeSeriesAI instance (has the newly loaded model)
        backtest_engine: AdvancedBacktestEngine instance
        setup_type: e.g. "SCALP"
        bar_size: e.g. "5 mins"
        training_result: Result dict from _train_single_setup_profile
        job_id: Optional job ID for progress updates
        progress_callback: async fn(percent, message) for progress
    
    Returns:
        Dict with validation results, promoted/rejected status
    """
    validation_id = f"val_{uuid.uuid4().hex[:8]}"
    start_time = datetime.now(timezone.utc)
    
    logger.info(f"[VALIDATE] Starting validation {validation_id} for {setup_type}/{bar_size}")
    
    if progress_callback:
        await progress_callback(92, f"Validating {setup_type}/{bar_size} model...")
    
    try:
        # Step 1: Get validation symbols (top liquid from ADV cache)
        symbols = _get_validation_symbols(db, bar_size)
        if not symbols:
            logger.warning(f"[VALIDATE] No symbols found for validation of {setup_type}/{bar_size}")
            return _make_result(validation_id, setup_type, bar_size, "skipped",
                               reason="No validation symbols available")
        
        logger.info(f"[VALIDATE] Using {len(symbols)} symbols for validation")
        
        if progress_callback:
            await progress_callback(93, f"Running validation backtest ({len(symbols)} symbols)...")
        
        # Step 2: Run AI comparison backtest
        backtest_result = await _run_validation_backtest(
            backtest_engine, symbols, setup_type, bar_size
        )
        
        if not backtest_result:
            return _make_result(validation_id, setup_type, bar_size, "skipped",
                               reason="Backtest returned no results")
        
        # Step 3: Extract key metrics from backtest
        new_metrics = _extract_validation_metrics(backtest_result)
        
        logger.info(
            f"[VALIDATE] {setup_type}/{bar_size} backtest: "
            f"trades={new_metrics['total_trades']}, win_rate={new_metrics['win_rate']:.1%}, "
            f"return={new_metrics['total_return']:.2%}, sharpe={new_metrics['sharpe_ratio']:.2f}"
        )
        
        if progress_callback:
            await progress_callback(96, "Comparing against baseline...")
        
        # Step 4: Load baseline (previous validation for this model)
        baseline = _load_baseline(db, setup_type, bar_size)
        
        # Step 5: Decide: promote or reject
        decision = _make_promotion_decision(new_metrics, baseline)
        
        if progress_callback:
            status_msg = "PROMOTED" if decision["promote"] else "KEPT (baseline better)"
            await progress_callback(98, f"{setup_type}/{bar_size}: {status_msg}")
        
        # Step 6: If promoted, save new baseline. If rejected, rollback model.
        if decision["promote"]:
            _save_baseline(db, setup_type, bar_size, new_metrics, validation_id)
            logger.info(f"[VALIDATE] {setup_type}/{bar_size} PROMOTED — {decision['reason']}")
        else:
            # Rollback: restore previous model from backup
            rolled_back = await _rollback_model(db, timeseries_service, setup_type, bar_size)
            if rolled_back:
                logger.info(f"[VALIDATE] {setup_type}/{bar_size} REJECTED + ROLLED BACK — {decision['reason']}")
            else:
                # No previous model to rollback to, keep the new one
                decision["promote"] = True
                decision["reason"] += " (no previous model to rollback to, keeping new)"
                _save_baseline(db, setup_type, bar_size, new_metrics, validation_id)
                logger.info(f"[VALIDATE] {setup_type}/{bar_size} kept (first model, no baseline)")
        
        # Step 7: Store validation record
        validation_record = _make_result(
            validation_id, setup_type, bar_size,
            "promoted" if decision["promote"] else "rejected",
            reason=decision["reason"],
            new_metrics=new_metrics,
            baseline_metrics=baseline,
            backtest_trades=new_metrics.get("total_trades", 0),
            training_accuracy=training_result.get("metrics", {}).get("accuracy", 0),
        )
        _save_validation_record(db, validation_record)
        
        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.info(f"[VALIDATE] Validation complete in {elapsed:.1f}s: {validation_record['status']}")
        
        return validation_record
        
    except Exception as e:
        logger.error(f"[VALIDATE] Validation failed for {setup_type}/{bar_size}: {e}", exc_info=True)
        return _make_result(validation_id, setup_type, bar_size, "error", reason=str(e))


def _get_validation_symbols(db, bar_size: str) -> List[str]:
    """Get top liquid symbols for validation backtest."""
    from services.ai_modules.setup_training_config import get_adv_threshold
    
    threshold = get_adv_threshold(bar_size)
    cursor = db["symbol_adv_cache"].find(
        {"avg_volume": {"$gte": threshold}},
        {"_id": 0, "symbol": 1, "avg_volume": 1}
    ).sort("avg_volume", -1).limit(VALIDATION_CONFIG["num_symbols"])
    
    return [doc["symbol"] for doc in cursor]


async def _run_validation_backtest(
    backtest_engine, symbols: List[str], setup_type: str, bar_size: str
) -> Optional[Any]:
    """Run a focused AI comparison backtest for validation."""
    from services.slow_learning.advanced_backtest_engine import (
        StrategyConfig, BacktestFilters
    )
    
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=VALIDATION_CONFIG["lookback_days"])
    
    strategy = StrategyConfig(
        name=f"{setup_type}_validation",
        setup_type=setup_type.lower(),
        entry_rules={"setup_confirmation": True},
        exit_rules={"target_r": 2.0, "stop_r": 1.0},
        risk_per_trade=0.01,
    )
    
    filters = BacktestFilters(
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d"),
    )
    
    try:
        result = await backtest_engine.run_ai_comparison_backtest(
            symbols=symbols,
            strategy=strategy,
            filters=filters,
            starting_capital=VALIDATION_CONFIG["starting_capital"],
            ai_confidence_threshold=VALIDATION_CONFIG["ai_confidence_threshold"],
            ai_lookback_bars=VALIDATION_CONFIG["ai_lookback_bars"],
        )
        return result
    except Exception as e:
        logger.error(f"Validation backtest failed: {e}")
        return None


def _extract_validation_metrics(backtest_result) -> Dict[str, float]:
    """Extract key metrics from an AI comparison backtest result."""
    metrics = {
        "total_trades": 0,
        "win_rate": 0.0,
        "total_return": 0.0,
        "sharpe_ratio": 0.0,
        "max_drawdown": 0.0,
        "avg_r_multiple": 0.0,
        "ai_vs_setup_edge": 0.0,
    }
    
    try:
        result_dict = backtest_result.to_dict() if hasattr(backtest_result, 'to_dict') else backtest_result
        
        # AI+Setup metrics (the main model being validated)
        ai_filtered = result_dict.get("ai_filtered_metrics", {})
        setup_only = result_dict.get("setup_only_metrics", {})
        
        metrics["total_trades"] = ai_filtered.get("total_trades", 0)
        metrics["win_rate"] = ai_filtered.get("win_rate", 0)
        metrics["total_return"] = ai_filtered.get("total_return", 0)
        metrics["sharpe_ratio"] = ai_filtered.get("sharpe_ratio", 0)
        metrics["max_drawdown"] = ai_filtered.get("max_drawdown", 0)
        metrics["avg_r_multiple"] = ai_filtered.get("avg_r_multiple", 0)
        
        # Edge over setup-only (how much value does AI add?)
        setup_return = setup_only.get("total_return", 0)
        ai_return = ai_filtered.get("total_return", 0)
        metrics["ai_vs_setup_edge"] = ai_return - setup_return
        
    except Exception as e:
        logger.error(f"Error extracting validation metrics: {e}")
    
    return metrics


def _load_baseline(db, setup_type: str, bar_size: str) -> Optional[Dict]:
    """Load the stored baseline metrics for this model."""
    doc = db["model_baselines"].find_one(
        {"setup_type": setup_type, "bar_size": bar_size},
        {"_id": 0}
    )
    return doc.get("metrics") if doc else None


def _save_baseline(db, setup_type: str, bar_size: str, metrics: Dict, validation_id: str):
    """Save new baseline metrics after promotion."""
    db["model_baselines"].update_one(
        {"setup_type": setup_type, "bar_size": bar_size},
        {"$set": {
            "setup_type": setup_type,
            "bar_size": bar_size,
            "metrics": metrics,
            "validation_id": validation_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True
    )


def _make_promotion_decision(new_metrics: Dict, baseline: Optional[Dict]) -> Dict:
    """Decide whether to promote the new model based on metrics."""
    # Check minimum thresholds first
    if new_metrics["total_trades"] < PROMOTION_CRITERIA["min_trades"]:
        return {
            "promote": True,  # Promote anyway — insufficient data to reject
            "reason": f"Insufficient backtest trades ({new_metrics['total_trades']}), promoting by default"
        }
    
    if new_metrics["win_rate"] < PROMOTION_CRITERIA["min_win_rate"]:
        return {
            "promote": False,
            "reason": f"Win rate {new_metrics['win_rate']:.1%} below minimum {PROMOTION_CRITERIA['min_win_rate']:.0%}"
        }
    
    # No baseline → first model, always promote
    if baseline is None:
        return {
            "promote": True,
            "reason": "First model for this profile — no baseline to compare against"
        }
    
    # Compare against baseline using composite score
    new_score = _composite_score(new_metrics)
    old_score = _composite_score(baseline)
    
    if new_score >= old_score:
        improvement = ((new_score - old_score) / max(abs(old_score), 0.01)) * 100
        return {
            "promote": True,
            "reason": (
                f"Improved: score {new_score:.3f} vs baseline {old_score:.3f} "
                f"(+{improvement:.1f}%). "
                f"WR: {new_metrics['win_rate']:.1%} vs {baseline.get('win_rate', 0):.1%}, "
                f"Sharpe: {new_metrics['sharpe_ratio']:.2f} vs {baseline.get('sharpe_ratio', 0):.2f}"
            )
        }
    else:
        regression = ((old_score - new_score) / max(abs(old_score), 0.01)) * 100
        return {
            "promote": False,
            "reason": (
                f"Regression: score {new_score:.3f} vs baseline {old_score:.3f} "
                f"(-{regression:.1f}%). "
                f"WR: {new_metrics['win_rate']:.1%} vs {baseline.get('win_rate', 0):.1%}, "
                f"Sharpe: {new_metrics['sharpe_ratio']:.2f} vs {baseline.get('sharpe_ratio', 0):.2f}"
            )
        }


def _composite_score(metrics: Dict) -> float:
    """
    Composite score for model comparison.
    Weights: Sharpe (40%), Win Rate (30%), Total Return (20%), AI Edge (10%)
    """
    sharpe = metrics.get("sharpe_ratio", 0)
    win_rate = metrics.get("win_rate", 0)
    total_return = metrics.get("total_return", 0)
    ai_edge = metrics.get("ai_vs_setup_edge", 0)
    
    return (
        0.40 * sharpe +
        0.30 * (win_rate * 4 - 1) +  # Normalize: 50% WR → 1.0, 75% → 2.0
        0.20 * total_return * 10 +     # Scale returns
        0.10 * ai_edge * 10            # Scale edge
    )


async def _rollback_model(db, timeseries_service, setup_type: str, bar_size: str) -> bool:
    """Rollback to the backup model (stored before training)."""
    try:
        backup = db["setup_type_models_backup"].find_one(
            {"setup_type": setup_type, "bar_size": bar_size},
            {"_id": 0}
        )
        if not backup or not backup.get("model_data"):
            return False
        
        # Restore the backup to the active collection
        db["setup_type_models"].update_one(
            {"setup_type": setup_type, "bar_size": bar_size},
            {"$set": backup},
            upsert=True
        )
        
        # Reload the model in memory
        model_bytes = base64.b64decode(backup["model_data"])
        restored_model = pickle.loads(model_bytes)
        
        model_key = setup_type.upper()
        if model_key in timeseries_service._setup_models:
            timeseries_service._setup_models[model_key]._model = restored_model
            if backup.get("feature_names"):
                timeseries_service._setup_models[model_key]._feature_names = backup["feature_names"]
            logger.info(f"[VALIDATE] Rolled back {setup_type}/{bar_size} to previous model")
        
        return True
    except Exception as e:
        logger.error(f"Model rollback failed: {e}")
        return False


def _save_validation_record(db, record: Dict):
    """Save validation record for audit trail."""
    db["model_validations"].insert_one(record)


def _make_result(
    validation_id: str, setup_type: str, bar_size: str, status: str,
    reason: str = "", new_metrics: Dict = None, baseline_metrics: Dict = None,
    backtest_trades: int = 0, training_accuracy: float = 0,
) -> Dict:
    """Build a validation result dict."""
    return {
        "validation_id": validation_id,
        "setup_type": setup_type,
        "bar_size": bar_size,
        "status": status,
        "reason": reason,
        "new_metrics": new_metrics or {},
        "baseline_metrics": baseline_metrics or {},
        "backtest_trades": backtest_trades,
        "training_accuracy": training_accuracy,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }


async def backup_current_model(db, setup_type: str, bar_size: str):
    """
    Backup the current model before training starts.
    Called by the worker before running training.
    """
    try:
        current = db["setup_type_models"].find_one(
            {"setup_type": setup_type, "bar_size": bar_size},
            {"_id": 0}
        )
        if current and current.get("model_data"):
            db["setup_type_models_backup"].update_one(
                {"setup_type": setup_type, "bar_size": bar_size},
                {"$set": current},
                upsert=True
            )
            logger.info(f"[VALIDATE] Backed up {setup_type}/{bar_size} model before training")
    except Exception as e:
        logger.warning(f"Model backup failed: {e}")
