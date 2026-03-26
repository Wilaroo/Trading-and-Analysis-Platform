"""
AI Training Pipeline API Router

Endpoints to trigger bulk model training, monitor progress,
and view results. All training runs asynchronously in the background.
"""

import logging
import asyncio
from typing import Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai-training", tags=["AI Training"])

# Global training task reference
_training_task: Optional[asyncio.Task] = None
_last_result = None


class TrainingRequest(BaseModel):
    phases: Optional[List[str]] = None  # e.g., ["generic", "volatility", "exit"]
    bar_sizes: Optional[List[str]] = None  # e.g., ["1 day", "5 mins"]
    max_symbols: Optional[int] = None


@router.post("/start")
async def start_training(request: TrainingRequest):
    """
    Start the bulk training pipeline in the background.
    Returns immediately with a task ID.
    """
    global _training_task, _last_result

    if _training_task and not _training_task.done():
        return {
            "success": False,
            "error": "Training already in progress",
            "status": "running",
        }

    try:
        from server import db as mongo_db
        if mongo_db is None:
            raise HTTPException(status_code=503, detail="Database not connected")

        from services.ai_modules.training_pipeline import run_training_pipeline

        async def _run():
            global _last_result
            _last_result = await run_training_pipeline(
                db=mongo_db,
                phases=request.phases,
                bar_sizes=request.bar_sizes,
                max_symbols_override=request.max_symbols,
            )

        _training_task = asyncio.create_task(_run())

        return {
            "success": True,
            "message": "Training pipeline started",
            "phases": request.phases or ["generic", "setup", "volatility", "exit", "sector", "gap_fill", "risk"],
            "bar_sizes": request.bar_sizes or "all",
        }

    except Exception as e:
        logger.error(f"Failed to start training: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_training_status():
    """Get current training pipeline status."""
    global _training_task, _last_result

    try:
        from server import db as mongo_db

        # Check pipeline status from DB
        status_doc = None
        if mongo_db is not None:
            status_doc = mongo_db["training_pipeline_status"].find_one(
                {"_id": "pipeline"}, {"_id": 0}
            )

        task_status = "idle"
        if _training_task:
            if _training_task.done():
                task_status = "completed"
                if _training_task.exception():
                    task_status = "failed"
            else:
                task_status = "running"

        return {
            "success": True,
            "task_status": task_status,
            "pipeline_status": status_doc,
            "last_result": _last_result,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/stop")
async def stop_training():
    """Cancel the running training pipeline."""
    global _training_task

    if _training_task and not _training_task.done():
        _training_task.cancel()
        return {"success": True, "message": "Training cancelled"}

    return {"success": False, "message": "No training in progress"}


@router.get("/models")
async def list_trained_models():
    """List all trained models with their metrics."""
    try:
        from server import db as mongo_db
        if mongo_db is None:
            raise HTTPException(status_code=503, detail="Database not connected")

        models = list(mongo_db["timeseries_models"].find(
            {},
            {"_id": 0, "model_data": 0}  # Exclude heavy binary data
        ).sort("promoted_at", -1))

        return {
            "success": True,
            "count": len(models),
            "models": models,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/data-readiness")
async def check_data_readiness():
    """
    Check how much training data is available per bar size.
    Helps decide when to start training.
    """
    try:
        from server import db as mongo_db
        if mongo_db is None:
            raise HTTPException(status_code=503, detail="Database not connected")

        pipeline = [
            {"$group": {
                "_id": "$bar_size",
                "total_bars": {"$sum": 1},
                "unique_symbols": {"$addToSet": "$symbol"},
            }},
            {"$project": {
                "_id": 0,
                "bar_size": "$_id",
                "total_bars": 1,
                "symbol_count": {"$size": "$unique_symbols"},
            }},
            {"$sort": {"total_bars": -1}},
        ]

        results = list(mongo_db["ib_historical_data"].aggregate(pipeline, allowDiskUse=True))

        total_bars = sum(r["total_bars"] for r in results)

        return {
            "success": True,
            "total_bars": total_bars,
            "by_bar_size": results,
            "recommendation": (
                "Ready for training" if total_bars > 1_000_000
                else "Collecting more data recommended"
            ),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/regime-live")
async def get_live_regime():
    """
    Get live market regime classification from SPY, QQQ, IWM daily bars.
    Returns the current regime (bull/bear/range/high_vol) plus per-index metrics.
    """
    try:
        from server import db as mongo_db
        if mongo_db is None:
            raise HTTPException(status_code=503, detail="Database not connected")

        import numpy as np
        from services.ai_modules.regime_conditional_model import classify_regime
        from services.ai_modules.regime_features import compute_single_index_features

        def _load_index(symbol):
            # Use aggregation to get one bar per date, much faster than pulling 3000 raw bars
            pipeline = [
                {"$match": {"symbol": symbol, "bar_size": "1 day"}},
                {"$addFields": {"date_key": {"$substr": [{"$toString": "$date"}, 0, 10]}}},
                {"$sort": {"date": -1}},
                {"$group": {
                    "_id": "$date_key",
                    "close": {"$first": "$close"},
                    "high": {"$first": "$high"},
                    "low": {"$first": "$low"},
                    "date": {"$first": "$date_key"},
                }},
                {"$sort": {"_id": -1}},
                {"$limit": 30},
            ]
            try:
                real = list(mongo_db["ib_historical_data"].aggregate(pipeline, allowDiskUse=True))
            except Exception:
                return None, None, None, None

            if len(real) < 25:
                return None, None, None, None
            return (
                np.array([b["close"] for b in real], dtype=float),
                np.array([b["high"] for b in real], dtype=float),
                np.array([b["low"] for b in real], dtype=float),
                real[0].get("date", ""),
            )

        spy_c, spy_h, spy_l, spy_date = _load_index("SPY")
        qqq_c, qqq_h, qqq_l, qqq_date = _load_index("QQQ")
        iwm_c, iwm_h, iwm_l, iwm_date = _load_index("IWM")

        regime = "unknown"
        if spy_c is not None:
            regime = classify_regime(spy_c, spy_h, spy_l)

        # Per-index features
        indexes = {}
        for name, c, h, lo, dt in [
            ("SPY", spy_c, spy_h, spy_l, spy_date),
            ("QQQ", qqq_c, qqq_h, qqq_l, qqq_date),
            ("IWM", iwm_c, iwm_h, iwm_l, iwm_date),
        ]:
            if c is not None:
                feats = compute_single_index_features(f"regime_{name.lower()}", c, h, lo)
                indexes[name] = {
                    "price": float(c[0]),
                    "date": dt,
                    "trend": feats.get(f"regime_{name.lower()}_trend", 0),
                    "rsi": feats.get(f"regime_{name.lower()}_rsi", 0),
                    "momentum": feats.get(f"regime_{name.lower()}_momentum", 0),
                    "volatility": feats.get(f"regime_{name.lower()}_volatility", 0),
                    "vol_expansion": feats.get(f"regime_{name.lower()}_vol_expansion", 0),
                    "breadth": feats.get(f"regime_{name.lower()}_breadth", 0),
                }
            else:
                indexes[name] = {"price": 0, "date": "", "trend": 0, "rsi": 0,
                                 "momentum": 0, "volatility": 0, "vol_expansion": 0, "breadth": 0}

        # Cross-correlations
        cross = {}
        if spy_c is not None and qqq_c is not None and iwm_c is not None:
            from services.ai_modules.regime_features import compute_cross_features
            cross_feats = compute_cross_features(spy_c, qqq_c, iwm_c)
            cross = {
                "spy_qqq_corr": cross_feats.get("regime_corr_spy_qqq", 0),
                "spy_iwm_corr": cross_feats.get("regime_corr_spy_iwm", 0),
                "qqq_iwm_corr": cross_feats.get("regime_corr_qqq_iwm", 0),
                "rotation_qqq_spy": cross_feats.get("regime_rotation_qqq_spy", 0),
                "rotation_iwm_spy": cross_feats.get("regime_rotation_iwm_spy", 0),
                "rotation_qqq_iwm": cross_feats.get("regime_rotation_qqq_iwm", 0),
            }

        return {
            "success": True,
            "regime": regime,
            "indexes": indexes,
            "cross": cross,
        }

    except Exception as e:
        logger.error(f"Live regime error: {e}")
        return {"success": False, "error": str(e)}


@router.get("/model-inventory")
async def get_model_inventory():
    """
    Get complete inventory of all model definitions with their training status.
    Shows which models are defined, which are trained, and their accuracy.
    """
    try:
        from server import db as mongo_db

        # Get trained models from DB
        trained_models = {}
        if mongo_db is not None:
            for doc in mongo_db["timeseries_models"].find({}, {"_id": 0, "model_data": 0}):
                trained_models[doc.get("model_name", "")] = {
                    "accuracy": doc.get("accuracy", 0),
                    "training_samples": doc.get("training_samples", 0),
                    "promoted_at": doc.get("promoted_at", ""),
                }

        from services.ai_modules.volatility_model import VOL_MODEL_CONFIGS
        from services.ai_modules.exit_timing_model import EXIT_MODEL_CONFIGS
        from services.ai_modules.sector_relative_model import SECTOR_MODEL_CONFIGS
        from services.ai_modules.gap_fill_model import GAP_MODEL_CONFIGS
        from services.ai_modules.risk_of_ruin_model import RISK_MODEL_CONFIGS
        from services.ai_modules.ensemble_model import ENSEMBLE_MODEL_CONFIGS

        categories = {
            "generic_directional": {
                "label": "Generic Directional",
                "description": "Predicts UP/DOWN per timeframe",
                "models": [],
            },
            "setup_specific": {
                "label": "Setup-Specific",
                "description": "Per setup type + timeframe",
                "models": [],
            },
            "volatility": {
                "label": "Volatility Prediction",
                "description": "Predicts high/low vol for position sizing",
                "models": [],
            },
            "exit_timing": {
                "label": "Exit Timing",
                "description": "Predicts optimal holding period",
                "models": [],
            },
            "sector_relative": {
                "label": "Sector-Relative",
                "description": "Outperform/underperform vs sector ETF",
                "models": [],
            },
            "gap_fill": {
                "label": "Gap Fill Probability",
                "description": "Gap fill vs continuation prediction",
                "models": [],
            },
            "risk_of_ruin": {
                "label": "Risk-of-Ruin",
                "description": "Stop-loss hit probability",
                "models": [],
            },
            "ensemble": {
                "label": "Ensemble Meta-Learner",
                "description": "Stacks multi-timeframe signals",
                "models": [],
            },
        }

        # Generic directional
        for bs in ["1 min", "5 mins", "15 mins", "30 mins", "1 hour", "1 day", "1 week"]:
            name = f"direction_predictor_{bs.replace(' ', '_')}"
            categories["generic_directional"]["models"].append({
                "name": name, "bar_size": bs,
                "trained": name in trained_models,
                **(trained_models.get(name, {})),
            })

        # Setup-specific (from existing config)
        from services.ai_modules.setup_training_config import SETUP_TRAINING_PROFILES, get_setup_profiles, get_model_name
        for st in SETUP_TRAINING_PROFILES.keys():
            profiles = get_setup_profiles(st)
            for profile in profiles:
                bs = profile.get("bar_size", "1 day")
                name = get_model_name(st, bs)
                categories["setup_specific"]["models"].append({
                    "name": name, "setup_type": st, "bar_size": bs,
                    "trained": name in trained_models,
                    **(trained_models.get(name, {})),
                })

        # New model categories
        for config_map, category_key in [
            (VOL_MODEL_CONFIGS, "volatility"),
            (EXIT_MODEL_CONFIGS, "exit_timing"),
            (SECTOR_MODEL_CONFIGS, "sector_relative"),
            (GAP_MODEL_CONFIGS, "gap_fill"),
            (RISK_MODEL_CONFIGS, "risk_of_ruin"),
            (ENSEMBLE_MODEL_CONFIGS, "ensemble"),
        ]:
            for key, cfg in config_map.items():
                name = cfg["model_name"]
                categories[category_key]["models"].append({
                    "name": name, "config_key": key,
                    "trained": name in trained_models,
                    **(trained_models.get(name, {})),
                })

        # Summary stats
        total_defined = sum(len(c["models"]) for c in categories.values())
        total_trained = sum(
            sum(1 for m in c["models"] if m.get("trained"))
            for c in categories.values()
        )

        return {
            "success": True,
            "total_defined": total_defined,
            "total_trained": total_trained,
            "categories": categories,
        }

    except Exception as e:
        logger.error(f"Model inventory error: {e}")
        return {"success": False, "error": str(e)}



# ============ CONFIDENCE GATE ENDPOINTS ============

@router.get("/confidence-gate/summary")
async def get_confidence_gate_summary():
    """
    Get SentCom's current trading mode, today's decision stats, and recent streak.
    Used by the NIA SentCom Intelligence panel header.
    """
    try:
        from services.ai_modules.confidence_gate import get_confidence_gate
        gate = get_confidence_gate()
        return {"success": True, **gate.get_summary()}
    except Exception as e:
        logger.error(f"Confidence gate summary error: {e}")
        return {"success": False, "error": str(e)}


@router.get("/confidence-gate/decisions")
async def get_confidence_gate_decisions(limit: int = 30):
    """
    Get recent confidence gate decisions for the NIA decision log.
    Shows what SentCom evaluated, what it decided, and why.
    """
    try:
        from services.ai_modules.confidence_gate import get_confidence_gate
        gate = get_confidence_gate()
        decisions = gate.get_decision_log(limit=limit)
        # Strip heavy fields for API response
        clean = []
        for d in decisions:
            clean.append({
                "decision": d.get("decision"),
                "confidence_score": d.get("confidence_score"),
                "symbol": d.get("symbol"),
                "setup_type": d.get("setup_type"),
                "direction": d.get("direction"),
                "regime_state": d.get("regime_state"),
                "ai_regime": d.get("ai_regime"),
                "trading_mode": d.get("trading_mode"),
                "position_multiplier": d.get("position_multiplier"),
                "reasoning": d.get("reasoning"),
                "timestamp": d.get("timestamp"),
            })
        return {"success": True, "decisions": clean, "count": len(clean)}
    except Exception as e:
        logger.error(f"Confidence gate decisions error: {e}")
        return {"success": False, "error": str(e)}


@router.get("/confidence-gate/stats")
async def get_confidence_gate_stats():
    """
    Get lifetime and daily statistics for the confidence gate.
    """
    try:
        from services.ai_modules.confidence_gate import get_confidence_gate
        gate = get_confidence_gate()
        return {"success": True, **gate.get_stats()}
    except Exception as e:
        logger.error(f"Confidence gate stats error: {e}")
        return {"success": False, "error": str(e)}


@router.post("/confidence-gate/evaluate")
async def evaluate_trade_confidence(symbol: str, setup_type: str, direction: str = "long", quality_score: int = 70):
    """
    Manually evaluate a symbol+setup through the confidence gate.
    Useful for testing or manual pre-trade checks.
    """
    try:
        from server import db as mongo_db
        from services.ai_modules.confidence_gate import get_confidence_gate
        gate = get_confidence_gate()
        if mongo_db is not None and gate._db is None:
            gate.set_db(mongo_db)

        # Try to get regime engine
        regime_engine = None
        try:
            from server import market_regime_engine
            regime_engine = market_regime_engine
        except ImportError:
            pass

        result = await gate.evaluate(
            symbol=symbol,
            setup_type=setup_type,
            direction=direction,
            quality_score=quality_score,
            regime_engine=regime_engine,
        )
        return {"success": True, **result}
    except Exception as e:
        logger.error(f"Confidence gate evaluate error: {e}")
        return {"success": False, "error": str(e)}
